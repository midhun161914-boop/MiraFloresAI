"""Return health: area summaries, variance flags, the check suite and finding dispositions."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.review_routes import _run
from app.services.actors import Actor, current_actor, require_staff
from app.services.checks import CheckRun
from app.services.health import Health, HealthService, VarianceReport

router = APIRouter(prefix="/api", dependencies=[Depends(require_staff)])


def _health(request: Request) -> HealthService:
    return request.app.state.health


@router.get("/return-health", response_model=Health)
def return_health(request: Request, version: Optional[str] = None) -> Health:
    return _health(request).health(version)


@router.get("/checks", response_model=CheckRun)
def checks(request: Request, version: Optional[str] = None, actor: Actor = Depends(current_actor)) -> CheckRun:
    run = _health(request).checks(version)
    if actor.sensitive_data_clearance:
        return run
    red = request.app.state.redactor  # findings quote printed pages; mask for uncleared staff
    out = run.model_copy(deep=True)
    for f in out.findings:
        f.facts = [red.text(x) for x in f.facts]
        f.summary = red.text(f.summary)
    return out


@router.get("/variance", response_model=VarianceReport)
def variance(request: Request, version: Optional[str] = None) -> VarianceReport:
    return _health(request).variance(version)


class DispositionIn(BaseModel):
    disposition: Literal["resolved", "accepted", "not_an_issue", "reopened"]
    note: str = ""


@router.post("/findings/{finding_id}/disposition")
def disposition(finding_id: str, body: DispositionIn, request: Request, actor: Actor = Depends(current_actor)) -> dict:
    run = _health(request).checks()
    f = next((x for x in run.findings if x.id == finding_id), None)
    if f is None:
        raise HTTPException(404, f"No finding {finding_id}")
    return _run(request.app.state.review.disposition_finding, actor, finding_id, f.severity,
                body.disposition, body.note, f.lines)


class ExplainIn(BaseModel):
    text: str
    version: Optional[str] = None


@router.post("/variance/{line}/explain")
def explain(line: str, body: ExplainIn, request: Request, actor: Actor = Depends(current_actor)) -> dict:
    if line not in request.app.state.index.lines[body.version or request.app.state.index.current_version]:
        raise HTTPException(404, f"No line {line}")
    return _run(request.app.state.review.explain_variance, actor, line, body.version, body.text)
