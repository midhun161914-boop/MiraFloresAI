"""Status and time endpoints: return status at a glance, time vs budget."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.api.review_routes import _run
from app.services.actors import Actor, current_actor, require_staff
from app.services.budget import Budget, TimeEntry
from app.services.status import Status

router = APIRouter(prefix="/api", dependencies=[Depends(require_staff)])


class TimeIn(BaseModel):
    bucket: str
    hours: float
    date: Optional[str] = None
    note: str


@router.get("/status", response_model=Status)
def status(request: Request) -> Status:
    return request.app.state.status.status()


@router.get("/budget", response_model=Budget)
def budget(request: Request) -> Budget:
    return request.app.state.time.budget()


@router.post("/time", response_model=TimeEntry)
def log_time(body: TimeIn, request: Request, actor: Actor = Depends(current_actor)) -> TimeEntry:
    t = request.app.state.time
    return _run(lambda: t.log(actor, body.bucket, body.hours, body.date, body.note))


@router.post("/time/{entry_id}/void", response_model=TimeEntry)
def void_time(entry_id: str, request: Request, actor: Actor = Depends(current_actor)) -> TimeEntry:
    t = request.app.state.time
    return _run(lambda: t.void(actor, entry_id))
