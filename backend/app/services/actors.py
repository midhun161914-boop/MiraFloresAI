"""Who is acting. Every request carries an ``X-Actor-Id`` header set by the
role switcher; the server decides what that actor may see and do.
Identity is resolved server-side so visibility is enforced, not cosmetic."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import HTTPException, Request
from pydantic import BaseModel

from app.services.loader import PacketIndex

ACTOR_HEADER = "X-Actor-Id"


class Actor(BaseModel):
    id: str
    name: str
    kind: Literal["staff", "client"]
    role: str
    credential: Optional[str] = None
    sensitive_data_clearance: bool
    assignments: list[str] = []  # e.g. ["preparer"] from firm.assignment_at_start
    note: Optional[str] = None


def all_actors(idx: PacketIndex) -> list[Actor]:
    firm = idx.packet.firm
    assigned = firm.assignment_at_start.model_dump()
    out = [
        Actor(
            id=s.id, name=s.name, kind="staff", role=s.role, credential=s.credential,
            sensitive_data_clearance=s.sensitive_data_clearance,
            assignments=[k for k, v in assigned.items() if v == s.id], note=s.note,
        )
        for s in firm.staff
    ]
    # Assumption: client users see their own household's identifiers unmasked
    # (they supplied them); they get no firm permissions.
    out += [
        Actor(id=c.id, name=c.name, kind="client", role=c.role, sensitive_data_clearance=True)
        for c in firm.client_users
    ]
    return out


def default_actor_id(idx: PacketIndex) -> str:
    return idx.packet.firm.assignment_at_start.preparer


def require_staff(request: Request) -> None:
    """Router-level guard: client users only reach the client surface (/api/client/...)."""
    if current_actor(request).kind != "staff":
        raise HTTPException(403, detail={"code": "CLIENT_SURFACE_ONLY",
                                         "message": "Client users can only use the client surface."})


def current_actor(request: Request) -> Actor:
    idx: PacketIndex = request.app.state.index
    actors: dict[str, Actor] = request.app.state.actors
    actor_id = request.headers.get(ACTOR_HEADER) or default_actor_id(idx)
    actor = actors.get(actor_id)
    if actor is None:
        raise HTTPException(400, f"Unknown actor {actor_id!r}")
    return actor
