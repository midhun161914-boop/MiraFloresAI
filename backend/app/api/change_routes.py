"""Change endpoints: adjustments, version compare + saved states, what-ifs, the
since-you-last-looked digest and bulk actions with undo. Staff only; every
write is a rule-checked event."""

from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.review_routes import _run
from app.services.actors import Actor, current_actor, require_staff
from app.services.changes import Adjustment, BulkResult, BulkSummary, ChangeIn, ChangeService, Digest
from app.services.events import Event
from app.services.versions import Compare, Estimate, EstimateItem, StateRef, VersionService

router = APIRouter(prefix="/api", dependencies=[Depends(require_staff)])


def _changes(request: Request) -> ChangeService:
    return request.app.state.changes


def _versions(request: Request) -> VersionService:
    return request.app.state.versions


# ------------------------------------------------------------------ adjustments
class AdjustmentIn(BaseModel):
    title: str = ""
    reason: str
    changes: list[ChangeIn]
    version: Optional[str] = None
    finding_id: Optional[str] = None
    refs: list[str] = []


class FromFindingIn(BaseModel):
    reason: str


class DecisionIn(BaseModel):
    note: str = ""


@router.get("/adjustments", response_model=list[Adjustment])
def adjustments(request: Request) -> list[Adjustment]:
    return _changes(request).list_adjustments()


@router.post("/adjustments", response_model=Adjustment)
def propose(body: AdjustmentIn, request: Request, actor: Actor = Depends(current_actor)) -> Adjustment:
    c = _changes(request)
    return _run(lambda: c.propose(actor, version=body.version, title=body.title, reason=body.reason, changes=body.changes,
                                  finding_id=body.finding_id, refs=body.refs))


@router.post("/adjustments/from-finding/{finding_id}", response_model=Adjustment)
def from_finding(finding_id: str, body: FromFindingIn, request: Request, actor: Actor = Depends(current_actor)) -> Adjustment:
    """Turn a finding's computed fix into a proposed adjustment, carrying its evidence and tax effect."""
    c = _changes(request)
    f = next((x for x in request.app.state.health.checks().findings if x.id == finding_id), None)
    if f is None:
        raise HTTPException(404, f"No finding {finding_id}")
    if f.fix is None:
        raise HTTPException(409, detail={"code": "NO_FIX", "message": "This finding has no determinable line fix; "
                                                                      "record a disposition or adjust lines by hand."})
    changes = [ChangeIn(key=ch.key, to_value=ch.to_value, label=ch.label) for ch in f.fix.changes]
    return _run(lambda: c.propose(actor, version=None, title=f"{f.fix.description} ({f.code})", reason=body.reason,
                                  changes=changes, finding_id=finding_id))


@router.post("/adjustments/{adj_id}/{kind}", response_model=Adjustment)
def decide(adj_id: str, kind: Literal["approve", "reject", "reverse"], body: DecisionIn, request: Request,
           actor: Actor = Depends(current_actor)) -> Adjustment:
    return _run(_changes(request).decide, actor, adj_id, kind, body.note)


# ------------------------------------------------------------------ states + compare
class SaveStateIn(BaseModel):
    name: str
    version: Optional[str] = None


@router.get("/states", response_model=list[StateRef])
def states(request: Request) -> list[StateRef]:
    return _versions(request).states()


@router.post("/states")
def save_state(body: SaveStateIn, request: Request, actor: Actor = Depends(current_actor)) -> dict:
    return _run(_changes(request).save_state, actor, body.name, body.version)


@router.get("/compare", response_model=Compare)
def compare(request: Request, a: str, b: str) -> Compare:
    try:
        return _versions(request).compare(a, b)
    except KeyError as exc:
        raise HTTPException(404, f"Unknown state {exc}")


# ------------------------------------------------------------------ what-ifs
class EstimateIn(BaseModel):
    items: list[EstimateItem]
    version: Optional[str] = None


@router.get("/whatif")
def whatif(request: Request) -> dict:
    return _versions(request).scripted()


@router.post("/whatif/estimate", response_model=Estimate)
def estimate(body: EstimateIn, request: Request) -> Estimate:
    try:
        return _versions(request).estimate(body.items, body.version)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


# ------------------------------------------------------------------ digest
def describe(e: Event) -> str:
    p = e.payload
    t = e.type
    return {
        "verification.recorded": lambda: f"verified {e.node} ({str(p.get('method', '')).replace('_', ' ')})",
        "verification.withdrawn": lambda: f"withdrew a verification on {e.node}",
        "note.opened": lambda: f"{'blocking ' if p.get('blocking') else ''}note on {e.node}: {p.get('text', '')}",
        "note.replied": lambda: f"replied on {e.node}: {p.get('text', '')}",
        "note.resolved": lambda: f"resolved a note on {e.node}",
        "note.reopened": lambda: f"reopened a note on {e.node}",
        "signoff.recorded": lambda: f"signed off {e.node} as {p.get('level')}",
        "signoff.reopened": lambda: f"sign-off on {e.node} reopened: {p.get('reason', '')}",
        "signoff.withdrawn": lambda: f"withdrew a sign-off on {e.node}",
        "value.corrected": lambda: f"corrected {e.node}: {p.get('from')} → {p.get('to')}",
        "value.correction_reverted": lambda: f"reverted the correction on {e.node}",
        "finding.dispositioned": lambda: f"{str(p.get('disposition', '')).replace('_', ' ')} finding {e.node}",
        "variance.explained": lambda: f"explained the variance on {e.node}",
        "adjustment.proposed": lambda: f"proposed {p.get('adj_id')}: {p.get('title')}"
                                       + (" — needs partner sign-off" if p.get("requires_partner") else ""),
        "adjustment.approved": lambda: f"approved {p.get('adj_id')}",
        "adjustment.rejected": lambda: f"rejected {p.get('adj_id')}",
        "adjustment.reversed": lambda: f"reversed {p.get('adj_id')}",
        "state.saved": lambda: f"saved the state “{p.get('name')}”",
    }.get(t, lambda: t)()


@router.get("/digest", response_model=Digest)
def digest(request: Request, actor: Actor = Depends(current_actor)) -> Digest:
    return _changes(request).digest(actor, describe)


class SeenIn(BaseModel):
    seq: Optional[int] = None


@router.post("/digest/seen")
def seen(body: SeenIn, request: Request, actor: Actor = Depends(current_actor)) -> dict:
    return {"last_seen_seq": _changes(request).mark_seen(actor, body.seq)}


# ------------------------------------------------------------------ bulk
class BulkVerifyIn(BaseModel):
    nodes: list[str]
    method: str
    note: str = ""
    version: Optional[str] = None


class BulkDispositionIn(BaseModel):
    finding_ids: list[str]
    disposition: Literal["resolved", "accepted", "not_an_issue"]
    note: str


@router.post("/bulk/verify", response_model=BulkResult)
def bulk_verify(body: BulkVerifyIn, request: Request, actor: Actor = Depends(current_actor)) -> BulkResult:
    return _run(_changes(request).bulk_verify, actor, body.nodes, body.method, body.note, body.version)


@router.post("/bulk/disposition", response_model=BulkResult)
def bulk_disposition(body: BulkDispositionIn, request: Request, actor: Actor = Depends(current_actor)) -> BulkResult:
    return _run(_changes(request).bulk_disposition, actor, body.finding_ids, body.disposition, body.note)


@router.get("/bulk", response_model=list[BulkSummary])
def bulks(request: Request) -> list[BulkSummary]:
    return _changes(request).list_bulks()


@router.post("/bulk/{bulk_id}/undo", response_model=BulkResult)
def undo(bulk_id: str, request: Request, actor: Actor = Depends(current_actor)) -> BulkResult:
    return _run(_changes(request).undo_bulk, actor, bulk_id)


__all__ = ["router", "describe", "Any"]
