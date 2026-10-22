"""Change management: adjustments, bulk actions with undo, saved states and the
per-user "since you last looked" digest. Every command is a rule-checked event in
the same append-only store; nothing here mutates state directly.

Adjustments vs corrections
--------------------------
* A *correction* (review layer) fixes what the pipeline misread on a document.
* An *adjustment* changes a value on the return. The engine's original value is
  preserved (the adjustment records from → to), the tax effect is computed with the
  packet's ``tax_effect_rates``, and an adjustment whose effect exceeds the firm's
  threshold in either jurisdiction stays *pending* until a partner — not the
  proposer — signs it off. Pending adjustments block filing.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel

from app.services.actors import Actor
from app.services.checks import Ctx, TaxEffect, tax_category
from app.services.review import PREPARE_ROLES, REVIEW_ROLES, SYSTEM, Conflict, ReviewService, RuleViolation


class ChangeIn(BaseModel):
    key: str
    to_value: float
    label: Optional[str] = None


class Adjustment(BaseModel):
    id: str
    seq: int
    version: str
    title: str
    reason: str
    finding_id: Optional[str] = None
    refs: list[str] = []
    changes: list[dict[str, Any]]
    tax_effect: dict[str, Any]
    requires_partner: bool
    threshold: float
    status: Literal["pending_partner", "active", "rejected", "reversed"]
    actor: str
    actor_name: str
    at: str
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    history: list[dict[str, Any]]


class BulkResult(BaseModel):
    bulk_id: str
    action: str
    applied: int
    refused: list[dict[str, str]]


class BulkSummary(BaseModel):
    id: str
    action: str
    params: dict[str, Any]
    actor: str
    actor_name: str
    at: str
    count: int
    refused: list[dict[str, str]]
    undone: bool
    undo: Optional[dict[str, Any]] = None


class Digest(BaseModel):
    last_seen_seq: int
    current_seq: int
    count: int
    items: list[dict[str, Any]]
    by_type: dict[str, int]


def partner_threshold(review: ReviewService) -> float:
    """From the firm's own rule text ("…tax effect over 1,000…")."""
    for rule in review.idx.packet.firm.starter_standards.rules:
        m = re.search(r"tax effect over \$?([\d,]+)", rule)
        if m:
            return float(m.group(1).replace(",", ""))
    return 1000.0


class ChangeService:
    def __init__(self, review: ReviewService, health: Any):
        self.review, self.health = review, health
        self.store = review.store
        self.threshold = partner_threshold(review)

    # ================================================================ adjustments
    def _adj(self, a: dict[str, Any]) -> Adjustment:
        return Adjustment(**{k: a.get(k) for k in Adjustment.model_fields if k in a and k != "threshold"},
                          threshold=a.get("threshold", self.threshold))

    def list_adjustments(self) -> list[Adjustment]:
        return [self._adj(a) for a in sorted(self.review.adjustments.values(), key=lambda a: -a["seq"])]

    def estimate(self, version: str, changes: list[dict[str, Any]]) -> TaxEffect:
        """Tax effect of line changes via tax_effect_rates (the engine cannot be rerun)."""
        ctx = Ctx(self.review.idx, self.review.trace, self.review, version)
        fed = ca = fed_due = ca_due = 0.0
        parts = []
        total = 0.0
        for ch in changes:
            delta = ch["to_value"] - (ch.get("from_value") or 0.0)
            cat = tax_category(ch["key"])
            e = ctx.effect(cat, delta, f"{ch['key']} {delta:+,.0f}")
            fed, ca = fed + e.federal_tax, ca + e.california_tax
            fed_due, ca_due = fed_due + e.federal_balance_due, ca_due + e.california_balance_due
            total += delta
            parts.append(e.basis)
        return TaxEffect(category="mixed" if len({tax_category(c["key"]) for c in changes}) > 1 else tax_category(changes[0]["key"]),
                         change=round(total, 2), federal_tax=fed, california_tax=ca, federal_balance_due=fed_due,
                         california_balance_due=ca_due, basis="; ".join(parts))

    def propose(self, actor: Actor, *, version: Optional[str], title: str, reason: str, changes: list[ChangeIn],
                finding_id: Optional[str] = None, refs: Optional[list[str]] = None) -> Adjustment:
        r = self.review
        v = version or r.idx.current_version
        lines = r.idx.lines[v]
        if not reason.strip():
            raise RuleViolation("REASON", "An adjustment needs a reason — it is the workpaper's explanation of the change.")
        if not changes:
            raise RuleViolation("EMPTY", "No line changes.")
        current = r.adjusted_values(v)
        rows = []
        for ch in changes:
            if ch.key not in lines and not ch.label:
                raise RuleViolation("UNKNOWN_LINE", f"{ch.key} is not a line in {v}; a new line needs a label.")
            base = current[ch.key]["value"] if ch.key in current else (lines[ch.key].value if ch.key in lines else None)
            if base is not None and not isinstance(base, (int, float)):
                raise RuleViolation("NOT_NUMERIC", f"{ch.key} is not an amount.")
            rows.append({"key": ch.key, "label": ch.label or lines[ch.key].label if ch.key in lines else ch.label,
                         "from_value": float(base) if base is not None else None, "to_value": ch.to_value,
                         "new_line": ch.key not in lines})
        effect: dict[str, Any]
        finding = None
        if finding_id:
            finding = next((f for f in self.health.checks(v).findings if f.id == finding_id), None)
            if finding is None:
                raise RuleViolation("UNKNOWN_FINDING", f"No finding {finding_id}.")
        if finding is not None and finding.tax_effect is not None and finding.fix is not None and \
                [c.key for c in finding.fix.changes] == [c["key"] for c in rows]:
            effect = {**finding.tax_effect.model_dump(), "source": f"finding {finding.id}"}
        else:
            effect = {**self.estimate(v, rows).model_dump(), "source": "tax_effect_rates estimate"}
        needs_partner = abs(effect["federal_balance_due"]) > self.threshold or abs(effect["california_balance_due"]) > self.threshold
        adj_id = "ADJ-" + uuid.uuid4().hex[:6].upper()

        def guard() -> None:
            r._staff(actor)
            if actor.role not in PREPARE_ROLES:
                raise RuleViolation("ROLE", f"A {actor.role.replace('_', ' ')} does not adjust the return.")
            now = r.adjusted_values(v)
            for row in rows:  # no lost writes: the line must still hold the value the proposer saw
                cur = now[row["key"]]["value"] if row["key"] in now else (lines[row["key"]].value if row["key"] in lines else None)
                if (cur is None) != (row["from_value"] is None) or (cur is not None and abs(float(cur) - row["from_value"]) > 0.005):
                    raise Conflict("STALE", f"{row['key']} changed since you loaded it.")

        refs_all = list(dict.fromkeys((refs or []) + (finding.refs if finding else [])))
        ev = self.store.append(actor=actor.id, actor_role=actor.role, type="adjustment.proposed", node=rows[0]["key"], version=v,
                          payload={"adj_id": adj_id, "version": v, "title": title.strip() or (finding.title if finding else "Adjustment"),
                                   "reason": reason.strip(), "finding_id": finding_id, "refs": refs_all, "changes": rows,
                                   "tax_effect": effect, "requires_partner": needs_partner, "threshold": self.threshold},
                          guard=guard)
        if not needs_partner:              # applied at once: the signed return changed
            r.reopen_return_signoffs(ev)
        return self._adj(r.adjustments[adj_id])

    def decide(self, actor: Actor, adj_id: str, kind: Literal["approve", "reject", "reverse"], note: str) -> Adjustment:
        r = self.review
        a = r.adjustments.get(adj_id)
        if a is None:
            raise RuleViolation("UNKNOWN", f"No adjustment {adj_id}.")

        def guard() -> None:
            r._staff(actor)
            if kind in ("approve", "reject"):
                if a["status"] != "pending_partner":
                    raise Conflict("NOT_PENDING", f"{adj_id} is {a['status'].replace('_', ' ')}, not awaiting sign-off.")
                if actor.role != "partner":
                    raise RuleViolation("PARTNER_REQUIRED", f"An adjustment with tax effect over {self.threshold:,.0f} needs "
                                                            "partner sign-off.")
                if actor.id == a["actor"]:
                    raise RuleViolation("NO_SELF_REVIEW", "A partner can't sign off an adjustment they proposed.")
                if kind == "approve" and not note.strip():
                    raise RuleViolation("NOTE", "Record the basis for approving.")
            else:  # reverse = undo, under the same rules as making it
                if a["status"] in ("rejected", "reversed"):
                    raise Conflict("NOT_ACTIVE", f"{adj_id} is already {a['status']}.")
                if a["status"] == "active" and a.get("requires_partner") and actor.role != "partner":
                    raise RuleViolation("PARTNER_REQUIRED", "Reversing a partner-approved adjustment needs a partner too.")
                if actor.id != a["actor"] and actor.role not in REVIEW_ROLES:
                    raise RuleViolation("NOT_YOURS", "Only the proposer, a reviewer or a partner can reverse an adjustment.")
                if not note.strip():
                    raise RuleViolation("NOTE", "Say why it is being reversed.")

        type_ = {"approve": "adjustment.approved", "reject": "adjustment.rejected", "reverse": "adjustment.reversed"}[kind]
        ev = self.store.append(actor=actor.id, actor_role=actor.role, type=type_, node=a["changes"][0]["key"],
                               version=a["version"], reverts=a.get("id") if kind == "reverse" else None,
                               payload={"adj_id": adj_id, "note": note.strip()}, guard=guard)
        if kind in ("approve", "reverse"):  # took effect, or stopped having effect
            r.reopen_return_signoffs(ev)
        return self._adj(r.adjustments[adj_id])

    # ================================================================ saved states + digest
    def save_state(self, actor: Actor, name: str, version: Optional[str]) -> dict[str, Any]:
        if not name.strip():
            raise RuleViolation("NAME", "Name the state.")

        def guard() -> None:
            self.review._staff(actor)

        seq = self.store.last_seq()
        self.store.append(actor=actor.id, actor_role=actor.role, type="state.saved", node="return",
                          version=version or self.review.idx.current_version,
                          payload={"name": name.strip(), "as_of_seq": seq}, guard=guard)
        return self.review.saved_states[-1]

    def mark_seen(self, actor: Actor, seq: Optional[int] = None) -> int:
        to = seq if seq is not None else self.store.last_seq()
        self.store.append(actor=actor.id, actor_role=actor.role, type="user.seen", node="engagement", payload={"seq": to})
        return to

    QUIET = {"view.logged", "user.seen", "bulk.started", "bulk.undone", "assignment.set"}

    def digest(self, actor: Actor, describe: Any) -> Digest:
        last = self.review.seen.get(actor.id, 0)
        events = [e for e in self.store.query(since=last, limit=2000, newest_first=False)
                  if e.actor != actor.id and e.type not in self.QUIET]
        items = [{"seq": e.seq, "at": e.at, "type": e.type, "node": e.node, "actor": e.actor,
                  "actor_name": self.review.name(e.actor), "text": describe(e)} for e in reversed(events)]
        by_type: dict[str, int] = {}
        for e in events:
            k = e.type.split(".")[0]
            by_type[k] = by_type.get(k, 0) + 1
        return Digest(last_seen_seq=last, current_seq=self.store.last_seq(), count=len(items), items=items, by_type=by_type)

    # ================================================================ bulk actions
    def _bulk_start(self, actor: Actor, action: str, params: dict[str, Any], refused: list[dict[str, str]]) -> str:
        bulk_id = "B-" + uuid.uuid4().hex[:6].upper()
        self.store.append(actor=actor.id, actor_role=actor.role, type="bulk.started", node="engagement",
                          payload={"bulk_id": bulk_id, "action": action, "params": params, "refused": refused})
        return bulk_id

    def bulk_verify(self, actor: Actor, nodes: list[str], method: str, note: str, version: Optional[str]) -> BulkResult:
        r = self.review
        v = version or r.idx.current_version
        if method not in r.methods:
            raise RuleViolation("METHOD", f"Use one of: {', '.join(r.methods)}.")
        refused, ok = [], []
        for n in dict.fromkeys(nodes):
            try:
                r._check_verify(actor, n, v)
                ok.append(n)
            except (RuleViolation, Conflict) as exc:
                refused.append({"item": n, "reason": exc.message})
        if not ok:
            raise RuleViolation("NONE_ALLOWED", refused[0]["reason"] if refused else "Nothing to verify.")
        bulk_id = self._bulk_start(actor, "verify", {"method": method, "note": note, "count": len(ok)}, refused)
        for n in ok:
            self.store.append(actor=actor.id, actor_role=actor.role, type="verification.recorded", node=n, version=v,
                              payload={"method": method, "note": note.strip(), "evidence": r.snapshot(n, v),
                                       "fingerprint": r.fingerprint(n, v), "bulk_id": bulk_id},
                              guard=lambda n=n: r._check_verify(actor, n, v))
        return BulkResult(bulk_id=bulk_id, action="verify", applied=len(ok), refused=refused)

    def bulk_disposition(self, actor: Actor, finding_ids: list[str], disposition: str, note: str) -> BulkResult:
        r = self.review
        run = self.health.checks()
        findings = {f.id: f for f in run.findings}
        refused, ok = [], []
        for fid in dict.fromkeys(finding_ids):
            f = findings.get(fid)
            if f is None:
                refused.append({"item": fid, "reason": "No such finding."})
                continue
            if f.status != "open":
                refused.append({"item": fid, "reason": f"Already {f.status.replace('_', ' ')}."})
                continue
            try:
                self._check_disposition(actor, f.severity, disposition, f.lines)
                ok.append(f)
            except (RuleViolation, Conflict) as exc:
                refused.append({"item": fid, "reason": exc.message})
        if not note.strip():
            raise RuleViolation("NOTE", "Say why — the note becomes the evidence for every finding in the batch.")
        if not ok:
            raise RuleViolation("NONE_ALLOWED", refused[0]["reason"] if refused else "Nothing to do.")
        bulk_id = self._bulk_start(actor, "disposition", {"disposition": disposition, "note": note, "count": len(ok)}, refused)
        for f in ok:
            self.store.append(actor=actor.id, actor_role=actor.role, type="finding.dispositioned", node=f.id,
                              payload={"finding_id": f.id, "disposition": disposition, "note": note.strip(),
                                       "severity": f.severity, "bulk_id": bulk_id})
        return BulkResult(bulk_id=bulk_id, action="disposition", applied=len(ok), refused=refused)

    def _check_disposition(self, actor: Actor, severity: str, disposition: str, lines: list[str]) -> None:
        r = self.review
        r._staff(actor)
        if actor.role not in PREPARE_ROLES:
            raise RuleViolation("ROLE", f"A {actor.role.replace('_', ' ')} does not disposition findings.")
        if disposition == "not_an_issue" and severity == "error":
            if actor.role not in REVIEW_ROLES:
                raise RuleViolation("REVIEW_REQUIRED", "Only a reviewer or partner can mark an error finding 'not an issue'.")
            if any(actor.id in r.preparers(k, None) for k in lines):
                raise RuleViolation("NO_SELF_REVIEW", "You prepared the lines this finding affects.")

    def list_bulks(self) -> list[BulkSummary]:
        return [BulkSummary(id=b["id"], action=b["action"], params=b["params"], actor=b["actor"], actor_name=b["actor_name"],
                            at=b["at"], count=len(b["events"]), refused=b["refused"], undone=b["undone"], undo=b["undo"])
                for b in sorted(self.review.bulks.values(), key=lambda b: -b["seq"])]

    def undo_bulk(self, actor: Actor, bulk_id: str) -> BulkResult:
        """Reverse every event of a bulk action. Each reversal is checked against the
        same rule that governs undoing that action singly; items the actor may not
        undo are reported, not silently skipped."""
        r = self.review
        b = r.bulks.get(bulk_id)
        if b is None:
            raise RuleViolation("UNKNOWN", f"No bulk action {bulk_id}.")
        if b["undone"]:
            raise Conflict("ALREADY_UNDONE", f"{bulk_id} was already undone.")
        r._staff(actor)
        plan, refused = [], []
        for ev in b["events"]:
            if ev["type"] == "verification.recorded":
                rec = r.verifications.get(ev["id"])
                if rec is None or rec["withdrawn"]:
                    continue
                if rec["actor"] != actor.id:
                    refused.append({"item": ev["node"], "reason": "Only the person who recorded a verification can withdraw it."})
                    continue
                plan.append(("verification.withdrawn", ev["node"], ev["id"], {}))
            elif ev["type"] == "finding.dispositioned":
                fid = ev["payload"]["finding_id"]
                cur = r.dispositions.get(fid)
                if not cur or cur.get("seq") is None:
                    continue
                try:  # undoing a disposition needs the same authority as making it
                    self._check_disposition(actor, ev["payload"].get("severity", "warning"), ev["payload"]["disposition"],
                                            [ev["node"] or ""])
                    plan.append(("finding.dispositioned", fid, None, {"finding_id": fid, "disposition": "reopened",
                                                                       "note": f"Undo of bulk {bulk_id}"}))
                except (RuleViolation, Conflict) as exc:
                    refused.append({"item": fid, "reason": exc.message})
        if not plan and refused:
            raise RuleViolation("UNDO_NOT_ALLOWED", refused[0]["reason"])
        for type_, node, reverts, payload in plan:
            self.store.append(actor=actor.id, actor_role=actor.role, type=type_, node=node, reverts=reverts,
                              payload={**payload, "undo_of": bulk_id})
        self.store.append(actor=actor.id, actor_role=actor.role, type="bulk.undone", node="engagement",
                          payload={"bulk_id": bulk_id, "reversed": len(plan), "refused": refused})
        return BulkResult(bulk_id=bulk_id, action="undo", applied=len(plan), refused=refused)


__all__ = ["ChangeService", "ChangeIn", "Adjustment", "BulkResult", "BulkSummary", "Digest", "SYSTEM"]
