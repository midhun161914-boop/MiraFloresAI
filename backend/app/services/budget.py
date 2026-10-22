"""Time vs budget. Staff log time against the firm's budget buckets
(``firm.budget_hours``); entries are events, a wrong entry is voided by the person
who logged it (append-only, like everything else)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict

from app.services.actors import Actor
from app.services.events import Event
from app.services.review import Conflict, ReviewService, RuleViolation

BUCKET_LABELS = {
    "intake_and_engagement": ("Intake & engagement", None),
    "wages_and_stock_compensation": ("Wages & stock comp", "wages"),
    "investments_and_digital_assets": ("Investments & digital assets", "investments"),
    "business": ("Business", "business"),
    "rentals_and_sale": ("Rentals & sale", "rentals"),
    "pass_throughs_and_basis": ("Pass-throughs & basis", "pass_throughs"),
    "deductions_and_credits": ("Deductions & credits", "deductions"),
    "california": ("California", "california"),
    "partner_review": ("Partner review", None),
}
NEAR = 0.85   # 85% of budget used = "near"


class TimeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    seq: int
    bucket: str
    hours: float
    date: str
    note: str
    actor: str
    actor_name: str
    at: str
    voided: bool


class BucketRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bucket: str
    label: str
    area: Optional[str]
    budget: float
    logged: float
    remaining: float
    pct: float
    status: Literal["under", "near", "over", "not_started"]
    by_person: dict[str, float]


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_budget: float
    total_logged: float
    pct: float
    status: Literal["under", "near", "over", "not_started"]
    buckets: list[BucketRow]
    entries: list[TimeEntry]


def _status(logged: float, budget: float) -> Literal["under", "near", "over", "not_started"]:
    if logged == 0:
        return "not_started"
    if logged > budget:
        return "over"
    return "near" if logged >= NEAR * budget else "under"


class TimeService:
    def __init__(self, review: ReviewService):
        self.review = review
        self.store = review.store
        self.budgets = {k: float(v) for k, v in review.idx.packet.firm.budget_hours.items()}
        self.entries: dict[str, dict[str, Any]] = {}
        for ev in self.store.all():
            self._apply(ev)
        self.store.subscribe(self._apply)

    def _apply(self, e: Event) -> None:
        p = e.payload
        if e.type == "time.logged":
            self.entries[p["entry_id"]] = {**{k: v for k, v in p.items() if k != "entry_id"}, "id": p["entry_id"], "seq": e.seq, "actor": e.actor,
                                           "actor_name": self.review.name(e.actor), "at": e.at, "voided": False}
        elif e.type == "time.voided" and p.get("entry_id") in self.entries:
            self.entries[p["entry_id"]]["voided"] = True

    def log(self, actor: Actor, bucket: str, hours: float, day: Optional[str], note: str) -> TimeEntry:
        entry_id = "T-" + uuid.uuid4().hex[:6].upper()
        d = day or date.today().isoformat()

        def guard() -> None:
            self.review._staff(actor)
            if bucket not in self.budgets:
                raise RuleViolation("BUCKET", f"Log time to one of the firm's budget areas: {', '.join(self.budgets)}.")
            if not (0 < hours <= 16):
                raise RuleViolation("HOURS", "Hours must be more than 0 and at most 16 per entry.")
            if round(hours * 4) != hours * 4:
                raise RuleViolation("HOURS", "Log time in quarter hours.")
            try:
                date.fromisoformat(d)
            except ValueError:
                raise RuleViolation("DATE", "Use a YYYY-MM-DD date.")
            if not note.strip():
                raise RuleViolation("NOTE", "Say what the time was spent on.")

        self.store.append(actor=actor.id, actor_role=actor.role, type="time.logged", node=bucket,
                          payload={"entry_id": entry_id, "bucket": bucket, "hours": hours, "date": d, "note": note.strip()},
                          guard=guard)
        return TimeEntry(**self.entries[entry_id])

    def void(self, actor: Actor, entry_id: str) -> TimeEntry:
        e = self.entries.get(entry_id)

        def guard() -> None:
            self.review._staff(actor)
            if e is None:
                raise RuleViolation("UNKNOWN", f"No time entry {entry_id}.")
            if e["voided"]:
                raise Conflict("ALREADY_VOIDED", "Already voided.")
            if e["actor"] != actor.id:
                raise RuleViolation("NOT_YOURS", "Only the person who logged time can void it.")

        self.store.append(actor=actor.id, actor_role=actor.role, type="time.voided", node=e["bucket"] if e else None,
                          reverts=entry_id, payload={"entry_id": entry_id}, guard=guard)
        return TimeEntry(**self.entries[entry_id])

    def budget(self) -> Budget:
        live = [x for x in self.entries.values() if not x["voided"]]
        rows = []
        for key, budget in self.budgets.items():
            mine = [x for x in live if x["bucket"] == key]
            logged = round(sum(x["hours"] for x in mine), 2)
            people: dict[str, float] = {}
            for x in mine:
                people[x["actor_name"]] = round(people.get(x["actor_name"], 0) + x["hours"], 2)
            label, area = BUCKET_LABELS.get(key, (key.replace("_", " ").capitalize(), None))
            rows.append(BucketRow(bucket=key, label=label, area=area, budget=budget, logged=logged,
                                  remaining=round(budget - logged, 2), pct=round(100 * logged / budget, 1) if budget else 0,
                                  status=_status(logged, budget), by_person=people))
        tb = round(sum(self.budgets.values()), 2)
        tl = round(sum(r.logged for r in rows), 2)
        return Budget(total_budget=tb, total_logged=tl, pct=round(100 * tl / tb, 1) if tb else 0, status=_status(tl, tb),
                      buckets=rows, entries=[TimeEntry(**x) for x in sorted(self.entries.values(), key=lambda x: -x["seq"])])
