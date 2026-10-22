"""Review layer + event log + client surface endpoints.

Every write goes through ReviewService, which checks the firm's rules and then
appends an event. A refused write returns 403 (rule) or 409 (someone changed
the item since you loaded it) with a message the UI shows verbatim.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.services.actors import Actor, current_actor, require_staff
from app.services.events import Event
from app.services.review import (
    Assignment, Conflict, Correction, Note, NodeReview, NodeSummary, Readiness, ReviewService, RuleViolation,
    SignOff, Verification,
)

router = APIRouter(prefix="/api", dependencies=[Depends(require_staff)])
client_router = APIRouter(prefix="/api/client")

LOG_READERS = {"firm_administrator", "partner", "quality_reviewer"}


def _review(request: Request) -> ReviewService:
    return request.app.state.review


def _run(fn: Any, *args: Any) -> Any:
    try:
        return fn(*args)
    except RuleViolation as exc:
        raise HTTPException(403, detail={"code": exc.code, "message": exc.message})
    except Conflict as exc:
        raise HTTPException(409, detail={"code": exc.code, "message": exc.message})


# ------------------------------------------------------------------- inputs
class VerifyIn(BaseModel):
    node: str
    version: Optional[str] = None
    method: str
    note: str = ""


class NoteIn(BaseModel):
    node: str
    version: Optional[str] = None
    text: str
    blocking: bool = False


class NoteActionIn(BaseModel):
    text: str = ""
    expected_seq: Optional[int] = None


class SignOffIn(BaseModel):
    node: str
    version: Optional[str] = None
    level: Literal["preparer", "reviewer", "partner"]
    expected_fingerprint: Optional[str] = None


class CorrectionIn(BaseModel):
    ev: str
    to: Any
    reason: str


class RevertIn(BaseModel):
    reason: str = ""


class EventOut(Event):
    actor_name: str


class EventsPage(BaseModel):
    last_seq: int
    items: list[EventOut]


class Queue(BaseModel):
    open_notes: list[Note]
    reopened_signoffs: list[SignOff]
    stale_verifications: list[Verification]
    active_signoffs: list[SignOff]
    corrections: list[Correction]
    readiness: Readiness
    assignments: list[Assignment]


# ------------------------------------------------------------------- reads
@router.get("/review/node", response_model=NodeReview)
def node_review(request: Request, node: str, version: Optional[str] = None,
                actor: Actor = Depends(current_actor)) -> NodeReview:
    r = _review(request)
    if not r.node_exists(node, version):
        raise HTTPException(404, f"No node {node}")
    return r.node_review(node, version, actor)


@router.get("/review/methods", response_model=list[str])
def methods(request: Request) -> list[str]:
    return _review(request).methods


@router.get("/review/summary", response_model=dict[str, NodeSummary])
def summary(request: Request, version: Optional[str] = None) -> dict[str, NodeSummary]:
    return _review(request).summary(version)


@router.get("/review/queue", response_model=Queue)
def queue(request: Request, version: Optional[str] = None) -> Queue:
    r = _review(request)
    return Queue(**r.queue(), readiness=r.readiness(version), assignments=r.assignment_list())


@router.get("/review/readiness", response_model=Readiness)
def readiness(request: Request, version: Optional[str] = None) -> Readiness:
    return _review(request).readiness(version)


@router.get("/events", response_model=EventsPage)
def events(request: Request, since: int = 0, node: Optional[str] = None, actor_id: Optional[str] = None,
           type: Optional[str] = Query(None, description="type prefix, e.g. note. or view."),
           limit: int = Query(200, ge=1, le=2000), actor: Actor = Depends(current_actor)) -> EventsPage:
    """The audit trail. View-log entries are visible to administrators, partners and
    quality reviewers, and to each person for their own views."""
    r = _review(request)
    red = None if actor.sensitive_data_clearance else request.app.state.redactor
    items = []
    for e in r.store.query(since=since, node=node, actor=actor_id, type_prefix=type, limit=limit):
        if e.type == "view.logged" and actor.role not in LOG_READERS and e.actor != actor.id:
            continue
        payload = red.obj(e.payload) if red else e.payload
        items.append(EventOut(**e.model_dump(exclude={"payload"}), payload=payload, actor_name=r.name(e.actor)))
    return EventsPage(last_seq=r.store.last_seq(), items=items)


@router.get("/viewlog", response_model=EventsPage)
def viewlog(request: Request, limit: int = Query(500, ge=1, le=5000),
            actor: Actor = Depends(current_actor)) -> EventsPage:
    return events(request, type="view.", limit=limit, actor=actor)


# ------------------------------------------------------------------- writes
@router.post("/review/verify", response_model=Verification)
def verify(body: VerifyIn, request: Request, actor: Actor = Depends(current_actor)) -> Verification:
    return _run(_review(request).verify, actor, body.node, body.version, body.method, body.note)


@router.post("/review/verifications/{vid}/withdraw", response_model=Verification)
def withdraw_verification(vid: str, request: Request, actor: Actor = Depends(current_actor)) -> Verification:
    return _run(_review(request).withdraw_verification, actor, vid)


@router.post("/review/notes", response_model=Note)
def open_note(body: NoteIn, request: Request, actor: Actor = Depends(current_actor)) -> Note:
    return _run(_review(request).open_note, actor, body.node, body.version, body.text, body.blocking)


@router.post("/review/notes/{note_id}/{action}", response_model=Note)
def note_action(note_id: str, action: Literal["reply", "resolve", "reopen"], body: NoteActionIn,
                request: Request, actor: Actor = Depends(current_actor)) -> Note:
    return _run(_review(request).note_action, actor, note_id, action, body.text, body.expected_seq)


@router.post("/review/signoffs", response_model=SignOff)
def signoff(body: SignOffIn, request: Request, actor: Actor = Depends(current_actor)) -> SignOff:
    return _run(_review(request).signoff, actor, body.node, body.version, body.level, body.expected_fingerprint)


@router.post("/review/signoffs/{sid}/withdraw", response_model=SignOff)
def withdraw_signoff(sid: str, request: Request, actor: Actor = Depends(current_actor)) -> SignOff:
    return _run(_review(request).withdraw_signoff, actor, sid)


@router.post("/review/corrections", response_model=Correction)
def correct(body: CorrectionIn, request: Request, actor: Actor = Depends(current_actor)) -> Correction:
    return _run(_review(request).correct_value, actor, body.ev, body.to, body.reason)


@router.post("/review/corrections/{ev}/revert", response_model=Correction)
def revert(ev: str, body: RevertIn, request: Request, actor: Actor = Depends(current_actor)) -> Correction:
    return _run(_review(request).revert_correction, actor, ev, body.reason)


# ------------------------------------------------------------------- client surface
class ClientDoc(BaseModel):
    id: str
    title: str
    received_at: str
    uploaded_by: str
    belongs_to: str


class ClientHome(BaseModel):
    household_name: str
    tax_year: int
    you: str
    documents: list[ClientDoc]
    questionnaire: list[dict[str, Any]]
    messages: list[dict[str, Any]]


@client_router.get("/home", response_model=ClientHome)
def client_home(request: Request, actor: Actor = Depends(current_actor)) -> ClientHome:
    """The client's own surface: what they sent, what they answered, their messages.
    No workpaper internals (lines, notes, sign-offs, other staff work)."""
    if actor.kind != "client":
        raise HTTPException(403, detail={"code": "CLIENT_ONLY", "message": "This is the client surface."})
    p = request.app.state.index.packet
    return ClientHome(
        household_name=p.packet.name.split(" - ")[0], tax_year=p.household.tax_year, you=actor.name,
        documents=[ClientDoc(id=d.id, title=d.title, received_at=d.received_at, uploaded_by=d.uploaded_by,
                             belongs_to=d.belongs_to)
                   for d in p.documents if d.uploaded_by == "client"],
        questionnaire=[q.model_dump() for q in p.client.questionnaire],
        messages=[m.model_dump(by_alias=True) for m in p.client.messages],
    )
