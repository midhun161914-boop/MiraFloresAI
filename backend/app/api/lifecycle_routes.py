"""Filing-lifecycle endpoints: extension, pre-file gate, due diligence, approval + 8879, e-file,
the frozen filed return, amendments, notice responses and the carry-forward.
Staff routes under /api; the taxpayers' approval lives on the client surface."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.review_routes import _run
from app.services.actors import Actor, current_actor, require_staff
from app.api import lifecycle_schemas as LS
from app.services.lifecycle import LifecycleService

router = APIRouter(prefix="/api", dependencies=[Depends(require_staff)])
client_router = APIRouter(prefix="/api/client")


def _lc(request: Request) -> LifecycleService:
    return request.app.state.lifecycle


class LifecycleNoteIn(BaseModel):
    note: str = ""


class DiligenceIn(BaseModel):
    answers: dict[str, bool]
    note: str
    refs: list[str] = []


class IdentityIn(BaseModel):
    person: str
    field: str = "ssn"
    evidence: str
    reason: str


class ReasonIn(BaseModel):
    reason: str


class AmendLineIn(BaseModel):
    key: str
    to_value: float
    reason: str
    refs: list[str] = []
    label: Optional[str] = None


class ApproveIn(BaseModel):
    pin: str
    agree: bool


# ------------------------------------------------------------------ filing
@router.get("/filing", response_model=LS.Filing)
def filing(request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    return _lc(request).filing_for(actor)


@router.get("/filing/gate", response_model=LS.Gate)
def gate(request: Request) -> Any:
    return _lc(request).gate()


@router.get("/filing/extension", response_model=LS.ExtensionView)
def extension(request: Request) -> dict[str, Any]:
    return _lc(request).extension_view()


@router.post("/filing/extension", response_model=LS.ExtensionView)
def file_extension(body: LifecycleNoteIn, request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    lc = _lc(request)
    return _run(lambda: lc.file_extension(actor, body.note))


@router.post("/filing/diligence/{item}", response_model=LS.DiligenceRecord)
def diligence(item: str, body: DiligenceIn, request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    lc = _lc(request)
    return _run(lambda: lc.complete_diligence(actor, item, body.answers, body.note, body.refs))


@router.post("/filing/present", response_model=LS.Filing)
def present(body: LifecycleNoteIn, request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    lc = _lc(request)
    _run(lambda: lc.present(actor, body.note))
    return lc.filing_for(actor)


@router.post("/filing/ero-sign", response_model=LS.Filing)
def ero_sign(body: LifecycleNoteIn, request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    lc = _lc(request)
    _run(lambda: lc.ero_sign(actor, body.note))
    return lc.filing_for(actor)


@router.post("/filing/transmit", response_model=LS.Filing)
def transmit(request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    lc = _lc(request)
    _run(lambda: lc.transmit(actor))
    return lc.filing_for(actor)


@router.post("/filing/identity", response_model=LS.Filing)
def identity(body: IdentityIn, request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    lc = _lc(request)
    return _run(lambda: lc.correct_identity(actor, body.person, body.field, body.evidence, body.reason))


@router.get("/filing/filed", response_model=LS.FiledReturn)
def filed(request: Request) -> dict[str, Any]:
    lc = _lc(request)
    return _run(lc.filed_return)


# ------------------------------------------------------------------ amendments
@router.get("/amendments", response_model=list[LS.Amendment])
def amendments(request: Request) -> list[dict[str, Any]]:
    return _lc(request).list_amendments()


@router.post("/amendments", response_model=LS.Amendment)
def open_amendment(body: ReasonIn, request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    lc = _lc(request)
    return _run(lambda: lc.open_amendment(actor, body.reason))


@router.post("/amendments/{amd_id}/lines", response_model=LS.Amendment)
def amend_line(amd_id: str, body: AmendLineIn, request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    lc = _lc(request)
    return _run(lambda: lc.amend_line(actor, amd_id, body.key, body.to_value, body.reason, body.refs, label=body.label))


@router.delete("/amendments/{amd_id}/lines/{key}", response_model=LS.Amendment)
def remove_line(amd_id: str, key: str, request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    lc = _lc(request)
    return _run(lambda: lc.remove_amend_line(actor, amd_id, key))


@router.post("/amendments/{amd_id}/from-finding/{finding_id}", response_model=LS.Amendment)
def amend_from_finding(amd_id: str, finding_id: str, body: ReasonIn, request: Request,
                       actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    lc = _lc(request)
    return _run(lambda: lc.amend_from_finding(actor, amd_id, finding_id, body.reason))


@router.post("/amendments/{amd_id}/approve", response_model=LS.Amendment)
def approve_amendment(amd_id: str, body: LifecycleNoteIn, request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    lc = _lc(request)
    return _run(lambda: lc.approve_amendment(actor, amd_id, body.note))


# ------------------------------------------------------------------ notices + carry forward
@router.get("/notices", response_model=list[LS.Notice])
def notices(request: Request) -> list[dict[str, Any]]:
    return _lc(request).notices()


@router.post("/notices/{notice_id}/assemble", response_model=LS.NoticeResponse)
def assemble(notice_id: str, request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    lc = _lc(request)
    return _run(lambda: lc.assemble_response(actor, notice_id))


@router.post("/notices/{notice_id}/sent", response_model=LS.NoticeResponse)
def sent(notice_id: str, body: LifecycleNoteIn, request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    lc = _lc(request)
    return _run(lambda: lc.mark_response_sent(actor, notice_id, body.note))


@router.get("/carryforward", response_model=LS.CarryForward)
def carryforward(request: Request) -> dict[str, Any]:
    return _lc(request).carryforward()


@router.post("/carryforward/roll", response_model=LS.CarryForward)
def roll(body: LifecycleNoteIn, request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    lc = _lc(request)
    return _run(lambda: lc.roll_forward(actor, body.note))


# ------------------------------------------------------------------ client surface
def _client(actor: Actor) -> None:
    if actor.kind != "client":
        raise HTTPException(403, detail={"code": "CLIENT_ONLY", "message": "This is the client surface."})


@client_router.get("/filing", response_model=LS.ClientFiling)
def client_filing(request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    _client(actor)
    return _lc(request).client_filing(actor)


@client_router.post("/filing/approve", response_model=LS.ClientFiling)
def client_approve(body: ApproveIn, request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    _client(actor)
    lc = _lc(request)
    return _run(lambda: lc.client_approve(actor, body.pin, body.agree))
