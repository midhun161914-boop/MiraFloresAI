"""Filing & after: extension, the pre-file gate, due diligence, client approval
and Form 8879, e-file with the packet's real reject, freeze at filing, amendments,
the Letter 566 response, and the carry-forward into 2026.

Every step is an event in the same append-only store, checked inside the write lock.
Once the return is filed a store-level policy refuses anything that would change the
filed return; further work goes into an *amendment*, layered on the frozen snapshot.

What comes from the packet (never invented here):
* the extension figures — ``what_if.extension``;
* agency responses — ``tax_agency_records.efile`` (the first federal transmission is
  answered by the recorded R0000-504-02 reject when the return still carries a
  dependent TIN that does not match the SSA record; the resubmission by the recorded
  acceptances);
* the SSA record itself — Theo's Social Security card (D71, ev-1080);
* the notice — ``tax_agency_records.notices`` (Letter 566, D72);
* carryovers — ``prior_years.carryovers_into_2025`` and each version's ``carryovers_out``;
* next-year planning — ``planning_reference_2026``; interest/penalty rates —
  ``post_filing_rates``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel

from app.services.actors import Actor
from app.services.events import Event
from app.services.redact import mask_keep_last4
from app.services.review import PREPARE_ROLES, REVIEW_ROLES, SYSTEM, Conflict, ReviewService, RuleViolation

# Event types that would change the filed return. After filing they are refused unless
# they target an amendment ("amend:<id>" as the version).
FROZEN_TYPES = {
    "adjustment.proposed", "adjustment.approved", "adjustment.rejected", "adjustment.reversed",
    "value.corrected", "value.correction_reverted", "signoff.recorded", "signoff.withdrawn",
    "verification.recorded", "verification.withdrawn", "identity.corrected", "diligence.completed",
    "filing.presented", "filing.client_approved", "filing.ero_signed", "efile.transmitted", "extension.filed",
}

DD_CREDITS = {  # firm rule: due diligence for these credits / statuses
    "ctc": ("Child tax credit", "F8812.4"),
    "odc": ("Credit for other dependents", "F8812.6"),
    "aotc": ("American opportunity credit", "F8863.7"),
    "eic": ("Earned income credit", "F1040.27"),
    "hoh": ("Head of household status", None),
}
DD_QUESTIONS = [
    "Interviewed the taxpayer and recorded the answers",
    "Relationship, age and residency of each qualifying person confirmed (months lived in the home)",
    "Each qualifying person's TIN agreed to an SSA document",
    "No other person can claim the qualifying person (tie-breaker considered)",
    "Records kept: documents relied on are in this file",
]


class GateItem(BaseModel):
    kind: str
    title: str
    detail: str = ""
    node: Optional[str] = None
    ref_id: Optional[str] = None
    link: Optional[str] = None


class Gate(BaseModel):
    clear: bool
    blockers: list[GateItem]
    steps: list[dict[str, Any]]   # the firm's required_steps with status


def _fp(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _round_up(x: float, step: int) -> int:
    return int(math.ceil(x / step) * step) if x > 0 else 0


class LifecycleService:
    def __init__(self, review: ReviewService, health: Any, changes: Any, redactor: Any = None):
        self.review, self.health, self.changes, self.redactor = review, health, changes, redactor
        self.store = review.store
        self.idx = review.idx
        self.p = review.idx.packet
        self.raw = review.idx.raw
        self._reset()
        for ev in self.store.all():
            self._apply(ev)
        self.store.subscribe(self._apply)
        self.store.add_policy(self._freeze_policy)

    # ================================================================ projection
    def _reset(self) -> None:
        self.extension: Optional[dict[str, Any]] = None
        self.diligence: dict[str, dict[str, Any]] = {}
        self.identity: dict[str, list[dict[str, Any]]] = {}     # "<person>.<field>" -> corrections
        self.presented: Optional[dict[str, Any]] = None
        self.approvals: dict[str, dict[str, Any]] = {}           # client id -> approval
        self.ero: Optional[dict[str, Any]] = None
        self.submissions: list[dict[str, Any]] = []
        self.filed: Optional[dict[str, Any]] = None
        self.amendments: dict[str, dict[str, Any]] = {}
        self.responses: dict[str, dict[str, Any]] = {}
        self.rolled: Optional[dict[str, Any]] = None

    def _apply(self, e: Event) -> None:
        p, t = e.payload, e.type
        who = {"actor": e.actor, "actor_name": self.review.name(e.actor), "at": e.at, "seq": e.seq}
        if t == "extension.filed":
            self.extension = {**p, **who}
        elif t == "diligence.completed":
            self.diligence[p["item"]] = {**p, **who}
        elif t == "identity.corrected":
            self.identity.setdefault(f"{p['person']}.{p['field']}", []).append({**p, **who})
        elif t == "filing.presented":
            self.presented = {**p, **who}
            self.approvals, self.ero = {}, None          # a new presentation needs new signatures
        elif t == "filing.client_approved":
            self.approvals[e.actor] = {**p, **who}
        elif t == "filing.ero_signed":
            self.ero = {**p, **who}
        elif t == "efile.transmitted":
            self.submissions.append({"id": p["submission_id"], "jurisdiction": p["jurisdiction"], "attempt": p["attempt"],
                                     "transmitted": who, "status": "transmitted", "response": None,
                                     "fingerprint": p.get("fingerprint")})
        elif t == "efile.response":
            for s in self.submissions:
                if s["id"] == p["submission_id"]:
                    s.update(status=p["status"], response={**p, **who})
        elif t == "return.filed":
            self.filed = {**p, **who}
        elif t == "amendment.opened":
            self.amendments[p["amd_id"]] = {**p, **who, "id": p["amd_id"], "changes": [], "status": "draft",
                                            "history": [{**who, "kind": "opened", "note": p.get("reason", "")}]}
        elif t in ("amendment.changed", "amendment.change_removed", "amendment.approved", "amendment.filed") \
                and p.get("amd_id") in self.amendments:
            a = self.amendments[p["amd_id"]]
            kind = t.split(".")[1]
            if kind == "changed":
                a["changes"] = [c for c in a["changes"] if c["key"] != p["key"]] + [{**p, **who}]
            elif kind == "change_removed":
                a["changes"] = [c for c in a["changes"] if c["key"] != p["key"]]
            elif kind == "approved":
                a["status"] = "approved"
            elif kind == "filed":
                a["status"] = "filed"
            a["history"].append({**who, "kind": kind, "note": p.get("reason") or p.get("note") or p.get("key", "")})
        elif t == "notice.response_assembled":
            self.responses[p["notice_id"]] = {**p, **who, "sent": None}
        elif t == "notice.response_sent" and p.get("notice_id") in self.responses:
            self.responses[p["notice_id"]]["sent"] = {**p, **who}
        elif t == "carryforward.rolled":
            self.rolled = {**p, **who}

    # ================================================================ freeze policy
    def _freeze_policy(self, draft: dict[str, Any]) -> None:
        if self.filed is None or draft["actor"] == SYSTEM.id:
            return
        if draft["type"] in FROZEN_TYPES and not str(draft.get("version") or "").startswith("amend:"):
            raise RuleViolation("FROZEN", f"The return was filed (accepted {self.filed['accepted_at'][:10]}) and is frozen. "
                                          "Changes go into an amendment.")

    # ================================================================ helpers
    @property
    def version(self) -> str:
        return self.idx.current_version

    def person(self, pid: str) -> dict[str, Any]:
        return next(x for x in self.raw["household"]["people"] if x["id"] == pid)

    def identity_value(self, pid: str, field: str) -> Any:
        hist = self.identity.get(f"{pid}.{field}")
        return hist[-1]["to"] if hist else self.person(pid).get(field)

    def return_values(self, as_of_seq: Optional[int] = None) -> dict[str, Any]:
        v = self.version
        vals = {k: ln.value for k, ln in self.idx.lines[v].items()}
        for k, row in self.review.adjusted_values(v, as_of_seq).items():
            vals[k] = row["value"]
        return vals

    def figures(self, as_of_seq: Optional[int] = None) -> dict[str, Any]:
        """Headline figures as presented: the engine summary plus the tax effect of the
        workpaper's active adjustments (tax_effect_rates — the engine cannot be rerun)."""
        s = self.idx.versions[self.version].summary
        fed, ca = s.federal.model_dump(), s.california.model_dump()
        adjs = self.review.active_adjustments(self.version, as_of_seq)
        dft = sum(a["tax_effect"].get("federal_tax", 0) for a in adjs)
        dfb = sum(a["tax_effect"].get("federal_balance_due", 0) for a in adjs)
        dct = sum(a["tax_effect"].get("california_tax", 0) for a in adjs)
        dcb = sum(a["tax_effect"].get("california_balance_due", 0) for a in adjs)
        income = [a for a in adjs if a["tax_effect"].get("category") not in ("payment", "ca_payment")]
        dagi = sum(a["tax_effect"].get("change", 0) for a in income)
        dca_agi = sum(a["tax_effect"].get("change", 0) for a in income if a["tax_effect"].get("california_tax"))
        out = {
            "federal": {"agi": round(fed["agi"] + dagi), "total_tax": round(fed["total_tax"] + dft), "payments": fed["payments"],
                        "balance_due": round(fed["balance_due"] + dfb)},
            "california": {"agi": round(ca["ca_agi"] + dca_agi), "total_tax": round(ca["total_tax"] + dct), "payments": ca["payments"],
                           "balance_due": round(ca["balance_due"] + dcb)},
            "adjustments": [a["id"] for a in adjs],
            "basis": "engine summary" + (f" + {len(adjs)} adjustment(s): income change added to AGI (CA AGI only where the "
                                         "change is California-taxed), tax and balance via tax_effect_rates" if adjs else ""),
        }
        return out

    def fingerprint(self) -> str:
        return _fp({"values": self.return_values(), "figures": self.figures()})

    def _dd_items(self) -> list[dict[str, Any]]:
        lines = self.idx.lines[self.version]
        out = []
        for key, (label, line) in DD_CREDITS.items():
            val = lines[line].value if line and line in lines else None
            claimed = isinstance(val, (int, float)) and val > 0
            if key == "aotc":    # phased out: computed but not claimed
                claimed = False
            if key == "hoh":
                claimed = self.raw["household"]["filing_status"] == "head_of_household"
            done = self.diligence.get(key)
            out.append({"id": key, "label": label, "line": line, "claimed": claimed, "value": val,
                        "status": "complete" if done else ("required" if claimed else "not_applicable"),
                        "record": done})
        return out

    def _require(self, actor: Actor, roles: set[str], what: str) -> None:
        self.review._staff(actor)
        if actor.role not in roles:
            raise RuleViolation("ROLE", f"A {actor.role.replace('_', ' ')} can't {what}.")

    # ================================================================ extension
    def extension_view(self) -> dict[str, Any]:
        w = self.raw["what_if"]["extension"]
        fed, ca = w["federal"], w["california"]
        return {
            "source": "what_if.extension", "computed_at": w["computed_at"], "based_on_version": w["based_on_version"],
            "federal": {**fed, "recomputed_payment": _round_up(fed["estimated_balance"], 500)},
            "california": {**ca, "recomputed_payment": _round_up(ca["estimated_balance"], 500)},
            "extended_due": next((d.date for d in self.p.firm.deadlines if d.what.startswith("Extended due date")), None),
            "note": self.raw["post_filing_rates"]["note"],
            "filed": self.extension,
        }

    def file_extension(self, actor: Actor, note: str) -> dict[str, Any]:
        view = self.extension_view()

        def guard() -> None:
            self._require(actor, REVIEW_ROLES, "file an extension")
            if self.extension:
                raise Conflict("ALREADY_FILED", "The extension is already recorded.")

        self.store.append(actor=actor.id, actor_role=actor.role, type="extension.filed", node="return", version=self.version,
                          payload={"forms": ["Form 4868", "FTB 3519"],
                                   "federal_payment": view["federal"]["paid_with_form_4868"],
                                   "california_payment": view["california"]["paid_with_ftb_3519"],
                                   "based_on_version": view["based_on_version"], "estimate": view,
                                   "extended_due": view["extended_due"], "note": note.strip(),
                                   "source": "what_if.extension"}, guard=guard)
        return self.extension_view()

    # ================================================================ due diligence
    def complete_diligence(self, actor: Actor, item: str, answers: dict[str, bool], note: str, refs: list[str]) -> dict[str, Any]:
        items = {d["id"]: d for d in self._dd_items()}

        def guard() -> None:
            self._require(actor, PREPARE_ROLES, "complete due diligence")
            if item not in items:
                raise RuleViolation("UNKNOWN", f"No due-diligence item {item}.")
            if items[item]["status"] == "not_applicable":
                raise Conflict("NOT_APPLICABLE", f"{items[item]['label']} is not claimed on this return.")
            missing = [q for q in DD_QUESTIONS if not answers.get(q)]
            if missing:
                raise RuleViolation("INCOMPLETE", f"Not every question is answered yes: {missing[0]}.")
            if not note.strip():
                raise RuleViolation("NOTE", "Record what was asked and what the client said (Form 8867).")

        self.store.append(actor=actor.id, actor_role=actor.role, type="diligence.completed", node="F8867.status",
                          version=self.version, payload={"item": item, "answers": answers, "note": note.strip(),
                                                         "refs": refs, "form": "8867"}, guard=guard)
        return self.diligence[item]

    # ================================================================ pre-file gate
    def gate(self) -> Gate:
        r = self.review
        v = self.version
        blockers: list[GateItem] = []
        rd = r.readiness(v)
        for b in rd.blockers:
            blockers.append(GateItem(kind=b.kind, title=b.title, detail=b.detail, node=b.node, ref_id=b.ref_id,
                                     link="/adjustments" if b.kind == "pending_adjustment"
                                     else "/review#return-signoff" if b.node == "return" else "/review"))
        run = self.health.checks(v)
        errors = [f for f in run.findings if f.severity == "error" and f.status in ("open", "adjustment_pending")]
        for f in errors:
            blockers.append(GateItem(kind="error_finding", title=f.title, detail=f"{f.code} — {f.status.replace('_', ' ')}",
                                     ref_id=f.id, link=f"/findings?status=open"))
        for level in ("reviewer", "partner"):
            if not any(s["node"] == "return" and s["level"] == level and s["status"] == "active" for s in r.signoffs.values()):
                blockers.append(GateItem(kind="missing_signoff", node="return", title=f"{level.title()} sign-off on the return",
                                         detail="Required by the firm's review levels.", link="/review#return-signoff"))
        for d in self._dd_items():
            if d["status"] == "required":
                blockers.append(GateItem(kind="due_diligence", title=f"Due diligence: {d['label']}",
                                         detail="Form 8867 not completed.", node="F8867.status", ref_id=d["id"],
                                         link="/filing#diligence"))
        kinds = {b.kind for b in blockers}
        unexplained = self.health.health(v).counts["variance_unexplained"]
        warn_open = [f for f in run.findings if f.severity == "warning" and f.status == "open"]
        step_status = {
            "Engagement letter and consents signed": ("done", "D01, D02 in file"),
            "Identity verified": ("done", "Taxpayer IDs in file") ,
            "Prior-year return reviewed": ("done", "D06 traced; variance computed"),
            "All documents accounted for": ("done" if not any(f.code == "INPUTS_INCOMPLETE" and f.status == "open" for f in run.findings)
                                            else "open", "completeness checks"),
            "Prior-year variances explained": ("done" if unexplained == 0 else "open", f"{unexplained} unexplained"),
            "Carryovers agreed to prior year": ("done", "carryovers_into_2025 vs 2024 return"),
            "Estimated payments agreed to IRS and FTB records": (
                "open" if any(f.check_id == "RECON_PAYMENTS" and f.status == "open" for f in run.findings) else "done",
                "payments reconciliation"),
            "Due diligence completed": ("open" if "due_diligence" in kinds else "done", "Form 8867"),
            "Diagnostics resolved": ("open" if "error_finding" in kinds else "done",
                                     f"{len(errors)} error finding(s) open; {len(warn_open)} warning(s) open"),
            "Reviewer sign-off": ("done" if not any(b.title.startswith("Reviewer sign-off on the return") for b in blockers)
                                  else "open", ""),
            "Partner sign-off": ("done" if not any(b.title.startswith("Partner sign-off on the return") for b in blockers)
                                 else "open", ""),
            "Client approval and e-file authorization": ("done" if self._authorized() else "open", "Form 8879"),
        }
        steps = [{"step": s, "status": step_status.get(s, ("open", ""))[0], "detail": step_status.get(s, ("", ""))[1]}
                 for s in self.p.firm.starter_standards.required_steps]
        return Gate(clear=not blockers, blockers=blockers, steps=steps)

    # ================================================================ approval + 8879
    def present(self, actor: Actor, note: str) -> dict[str, Any]:
        """Freeze the figures shown to the client for approval (the 8879 amounts)."""
        def guard() -> None:
            self._require(actor, REVIEW_ROLES, "present the return for client approval")
            g = self.gate()
            if not g.clear:
                raise RuleViolation("GATE_BLOCKED", f"The pre-file gate has {len(g.blockers)} item(s) outstanding: "
                                                    f"{g.blockers[0].title}.")

        self.store.append(actor=actor.id, actor_role=actor.role, type="filing.presented", node="return", version=self.version,
                          payload={"figures": self.figures(), "fingerprint": self.fingerprint(), "note": note.strip(),
                                   "as_of_seq": self.store.last_seq()}, guard=guard)
        return self.filing()

    def _signers(self) -> list[str]:
        return [c.id for c in self.p.firm.client_users]

    def _authorized(self) -> bool:
        return bool(self.presented and self.ero and all(c in self.approvals for c in self._signers())
                    and self.presented["fingerprint"] == self.fingerprint())

    def client_approve(self, actor: Actor, pin: str, agree: bool) -> dict[str, Any]:
        def guard() -> None:
            if actor.kind != "client":
                raise RuleViolation("CLIENT_ONLY", "Only the taxpayers approve their return and sign Form 8879.")
            if self.presented is None:
                raise Conflict("NOT_PRESENTED", "The firm has not presented the return for approval yet.")
            if self.presented["fingerprint"] != self.fingerprint():
                raise Conflict("CHANGED", "The return changed after it was presented; the firm must present it again.")
            if actor.id in self.approvals:
                raise Conflict("ALREADY_SIGNED", "You already approved and signed.")
            if not agree:
                raise RuleViolation("AGREE", "Confirm you reviewed the return and the amounts are correct.")
            if not re.fullmatch(r"[1-9]\d{4}", pin):
                raise RuleViolation("PIN", "Choose a five-digit self-select PIN (not all zeros).")

        self.store.append(actor=actor.id, actor_role=actor.role, type="filing.client_approved", node="return",
                          version=self.version,
                          payload={"form": "8879 / FTB 8879", "role": "taxpayer" if actor.id == self._signers()[0] else "spouse",
                                   "pin_hash": hashlib.sha256(f"{actor.id}:{pin}".encode()).hexdigest()[:16],
                                   "fingerprint": self.presented["fingerprint"] if self.presented else None,
                                   "figures": self.presented["figures"] if self.presented else None}, guard=guard)
        return self.client_filing(actor)

    def ero_sign(self, actor: Actor, note: str) -> dict[str, Any]:
        signer = self.raw["firm"]["firm_identity"].get("paid_preparer_signing_returns")

        def guard() -> None:
            self._require(actor, {"partner"}, "sign as the ERO / paid preparer")
            if signer and actor.id != signer:
                raise RuleViolation("NOT_SIGNER", f"The firm's signing preparer is {self.review.name(signer)}.")
            if not self.presented or not all(c in self.approvals for c in self._signers()):
                raise Conflict("CLIENT_FIRST", "Both taxpayers sign Form 8879 before the ERO signs.")
            if self.ero:
                raise Conflict("ALREADY_SIGNED", "The ERO already signed.")

        efin = self.raw["firm"]["firm_identity"]["efin"]
        self.store.append(actor=actor.id, actor_role=actor.role, type="filing.ero_signed", node="return", version=self.version,
                          payload={"efin": efin, "note": note.strip(), "fingerprint": self.fingerprint()}, guard=guard)
        return self.filing()

    # ================================================================ e-file
    def _agency(self) -> list[dict[str, Any]]:
        return self.raw["tax_agency_records"]["efile"]

    def _ssa_record(self, pid: str) -> Optional[dict[str, Any]]:
        """The SSA document for a dependent in the file (identity_document belonging to them)."""
        for d in self.p.documents:
            if d.belongs_to == f"dependent:{pid}" and d.document_type == "identity_document":
                for ev in self.idx.values_by_doc.get(d.id, []):
                    if ev.field == "ssn":
                        return {"document_id": d.id, "ev": ev.id, "ssn": self.review.effective(ev.id)}
        return None

    def tin_checks(self) -> list[dict[str, Any]]:
        out = []
        for person in self.raw["household"]["people"]:
            if person["role"] != "dependent":
                continue
            rec = self._ssa_record(person["id"])
            on_return = self.identity_value(person["id"], "ssn")
            out.append({"person": person["id"], "name": person["name"], "on_return": on_return,
                        "ssa": rec["ssn"] if rec else None, "evidence": rec,
                        "match": rec is None or rec["ssn"] == on_return})
        return out

    def transmit(self, actor: Actor) -> dict[str, Any]:
        """Transmit federal + California. The agency's answer is the packet's record."""
        fed_ok = any(s["jurisdiction"] == "federal" and s["status"] == "accepted" for s in self.submissions)
        attempt = 1 + max((s["attempt"] for s in self.submissions), default=0)

        def guard() -> None:
            self._require(actor, REVIEW_ROLES, "transmit the return")
            if not self._authorized():
                raise RuleViolation("NOT_AUTHORIZED", "Transmission needs the current return presented, both taxpayers' "
                                                      "8879 signatures and the ERO signature.")
            if fed_ok:
                raise Conflict("ALREADY_ACCEPTED", "The federal return is already accepted.")

        records = self._agency()
        mismatched = [c for c in self.tin_checks() if not c["match"]]
        if mismatched:   # the packet's recorded reject + state hold
            fed_rec = next(x for x in records if x["jurisdiction"] == "federal" and x["status"] == "rejected")
            ca_rec = next(x for x in records if x["jurisdiction"] == "california" and x["status"] == "not_transmitted")
        else:
            fed_rec = next(x for x in records if x["jurisdiction"] == "federal" and x["status"] == "accepted")
            ca_rec = next(x for x in records if x["jurisdiction"] == "california" and x["status"] == "accepted")
        fp = self.fingerprint()
        first = True
        for rec in (fed_rec, ca_rec):
            g = guard if first else None
            first = False
            self.store.append(actor=actor.id, actor_role=actor.role, type="efile.transmitted", node="return",
                              version=self.version, guard=g,
                              payload={"submission_id": rec["submission_id"], "jurisdiction": rec["jurisdiction"],
                                       "attempt": attempt, "fingerprint": fp})
            self.store.append(actor=SYSTEM.id, actor_role=SYSTEM.role, type="efile.response", node="return",
                              version=self.version,
                              payload={"submission_id": rec["submission_id"], "jurisdiction": rec["jurisdiction"],
                                       "status": rec["status"], "errors": rec.get("errors", []),
                                       "agency_date": rec["date"], "source": f"tax_agency_records.efile[{records.index(rec)}]",
                                       "tin_checks": [{k: v for k, v in c.items() if k in ("person", "match")} for c in self.tin_checks()]})
        self._maybe_freeze()
        return self.filing()

    def correct_identity(self, actor: Actor, person: str, field: str, evidence_ev: str, reason: str) -> dict[str, Any]:
        """Fix a TIN on the return from an SSA document in the file (the reject fix)."""
        if evidence_ev not in self.idx.values:
            raise RuleViolation("EVIDENCE", "Point at the extracted value on the SSA document.")
        to = self.review.effective(evidence_ev)

        def guard() -> None:
            self._require(actor, PREPARE_ROLES, "correct identity data")
            if not actor.sensitive_data_clearance:
                raise RuleViolation("CLEARANCE", "Correcting a TIN needs sensitive-data clearance.")
            if field != "ssn":
                raise RuleViolation("FIELD", "Only TINs are corrected here.")
            if not reason.strip():
                raise RuleViolation("REASON", "Say why (cite the reject and the document).")
            if self.identity_value(person, field) == to:
                raise Conflict("SAME", "The return already carries that number.")

        self.store.append(actor=actor.id, actor_role=actor.role, type="identity.corrected", node=f"household:{person}",
                          version=self.version,
                          payload={"person": person, "field": field, "from": self.identity_value(person, field), "to": to,
                                   "evidence": evidence_ev, "document_id": self.idx.values[evidence_ev].document_id,
                                   "reason": reason.strip()}, guard=guard)
        return self.filing_for(actor)

    def _maybe_freeze(self) -> None:
        acc = {s["jurisdiction"]: s for s in self.submissions if s["status"] == "accepted"}
        if self.filed is None and "federal" in acc and "california" in acc:
            seq = self.store.last_seq()
            snap = {"version": self.version, "as_of_seq": seq, "values": self.return_values(),
                    "figures": self.figures(), "adjustments": [a["id"] for a in self.review.active_adjustments(self.version)],
                    "identity": {f"{c['person']}.ssn": c["on_return"] for c in self.tin_checks()}}
            self.store.append(actor=SYSTEM.id, actor_role=SYSTEM.role, type="return.filed", node="return",
                              version=self.version,
                              payload={"accepted_at": acc["federal"]["response"]["agency_date"],
                                       "submissions": {k: v["id"] for k, v in acc.items()},
                                       "snapshot": snap, "snapshot_hash": _fp(snap)})

    def interest_estimate(self) -> Optional[dict[str, Any]]:
        """Interest + failure-to-pay on a federal balance paid after 2026-04-15 (the engine
        doesn't compute these; IRS will). Payment date from the packet timeline."""
        if not self.filed:
            return None
        bal = self.filed["snapshot"]["figures"]["federal"]["balance_due"]
        if bal <= 0:
            return {"balance_due": bal, "interest": 0, "penalty": 0, "note": "No balance due on the filed return."}
        rates = self.raw["post_filing_rates"]
        paid = next((t["at"][:10] for t in self.raw["timeline"] if t["event"] == "federal_balance_paid"), None)
        if not paid:
            return None
        days = (date.fromisoformat(paid) - date(2026, 4, 15)).days
        months = math.ceil(days / 30.4375)
        return {"balance_due": bal, "paid": paid, "days_late": days,
                "interest": round(bal * rates["irs_underpayment_interest_rate_annual"] * days / 365, 2),
                "penalty": round(bal * rates["irs_failure_to_pay_penalty_per_month"] * months, 2),
                "basis": f"{rates['irs_underpayment_interest_rate_annual']:.0%}/yr simple for {days} days; "
                         f"{rates['irs_failure_to_pay_penalty_per_month']:.1%} × {months} month(s). ESTIMATE — IRS computes "
                         "(transcript code 196/276)."}

    # ================================================================ views
    def _mask(self, actor: Actor, ssn: Optional[str]) -> Optional[str]:
        if ssn is None:
            return None
        return ssn if actor.sensitive_data_clearance else mask_keep_last4(ssn)

    def filing_for(self, actor: Actor) -> dict[str, Any]:
        f = self.filing()
        for c in f["tin_checks"]:
            c["on_return"], c["ssa"] = self._mask(actor, c["on_return"]), self._mask(actor, c["ssa"])
        for k, hist in f["identity"].items():
            for h in hist:
                h["from"], h["to"] = self._mask(actor, h["from"]), self._mask(actor, h["to"])
        return f

    def filing(self) -> dict[str, Any]:
        stage = ("filed" if self.filed else "transmitted" if self.submissions else
                 "authorized" if self._authorized() else "presented" if self.presented else "preparing")
        return {
            "stage": stage,
            "figures": self.figures(),
            "fingerprint": self.fingerprint(),
            "presented": self.presented,
            "presented_current": bool(self.presented and self.presented["fingerprint"] == self.fingerprint()),
            "signers": [{"id": c.id, "name": c.name, "approval": {k: v for k, v in self.approvals[c.id].items() if k != "pin_hash"}
                         if c.id in self.approvals else None} for c in self.p.firm.client_users],
            "ero": self.ero,
            "ero_signer": self.review.name(self.raw["firm"]["firm_identity"].get("paid_preparer_signing_returns", "")),
            "submissions": self.submissions,
            "tin_checks": self.tin_checks(),
            "identity": json.loads(json.dumps(self.identity)),
            "filed": {k: v for k, v in self.filed.items() if k != "snapshot"} if self.filed else None,
            "interest": self.interest_estimate(),
            "diligence": self._dd_items(),
            "diligence_questions": DD_QUESTIONS,
            "extension": self.extension,
        }

    def client_filing(self, actor: Actor) -> dict[str, Any]:
        """The client's view: the figures they approve and their own signature status only."""
        return {
            "presented": bool(self.presented),
            "current": bool(self.presented and self.presented["fingerprint"] == self.fingerprint()),
            "figures": self.presented["figures"] if self.presented else None,
            "presented_at": self.presented["at"] if self.presented else None,
            "you_signed": actor.id in self.approvals,
            "signed_at": self.approvals.get(actor.id, {}).get("at"),
            "others_signed": [self.review.name(k) for k in self.approvals if k != actor.id],
            "filed": bool(self.filed),
            "accepted_at": self.filed["accepted_at"] if self.filed else None,
        }

    def filed_return(self) -> dict[str, Any]:
        if not self.filed:
            raise Conflict("NOT_FILED", "The return has not been filed.")
        snap = self.filed["snapshot"]
        lines = self.idx.lines[snap["version"]]
        rows = [{"key": k, "label": lines[k].label if k in lines else k, "form": lines[k].form if k in lines else k.split(".")[0],
                 "value": v, "engine_value": lines[k].value if k in lines else None} for k, v in snap["values"].items()]
        return {"accepted_at": self.filed["accepted_at"], "submissions": self.filed["submissions"],
                "snapshot_hash": self.filed["snapshot_hash"], "figures": snap["figures"], "adjustments": snap["adjustments"],
                "as_of_seq": snap["as_of_seq"], "version": snap["version"], "lines": rows,
                "intact": _fp(snap) == self.filed["snapshot_hash"]}

    # ================================================================ amendments
    def open_amendment(self, actor: Actor, reason: str) -> dict[str, Any]:
        amd_id = "AMD-" + uuid.uuid4().hex[:6].upper()

        def guard() -> None:
            self._require(actor, PREPARE_ROLES, "open an amendment")
            if not self.filed:
                raise Conflict("NOT_FILED", "Amend a filed return; before filing, use an adjustment.")
            if any(a["status"] != "filed" for a in self.amendments.values()):
                raise Conflict("OPEN_AMENDMENT", "Finish the open amendment first.")
            if not reason.strip():
                raise RuleViolation("REASON", "Say why the return is being amended.")

        self.store.append(actor=actor.id, actor_role=actor.role, type="amendment.opened", node="return",
                          version=f"amend:{amd_id}",
                          payload={"amd_id": amd_id, "reason": reason.strip(), "base_snapshot": self.filed["snapshot_hash"],
                                   "forms": ["1040-X", "540NR (amended)"]}, guard=guard)
        return self.amendment(amd_id)

    def _amd_open(self, actor: Actor, amd_id: str) -> dict[str, Any]:
        a = self.amendments.get(amd_id)
        if a is None:
            raise RuleViolation("UNKNOWN", f"No amendment {amd_id}.")
        return a

    def amend_line(self, actor: Actor, amd_id: str, key: str, to_value: float, reason: str,
                   refs: Optional[list[str]] = None, finding_id: Optional[str] = None, label: Optional[str] = None) -> dict[str, Any]:
        a = self._amd_open(actor, amd_id)
        filed = self.filed["snapshot"]["values"] if self.filed else {}
        if key not in filed and not label:
            raise RuleViolation("UNKNOWN_LINE", f"{key} is not on the filed return; a new line needs a label.")
        frm = filed.get(key)
        if frm is not None and not isinstance(frm, (int, float)):
            raise RuleViolation("NOT_NUMERIC", f"{key} is not an amount.")
        effect = self.changes.estimate(self.version, [{"key": key, "from_value": float(frm or 0), "to_value": to_value}])

        def guard() -> None:
            self._require(actor, PREPARE_ROLES, "change an amendment")
            if a["status"] != "draft":
                raise Conflict("LOCKED", f"{amd_id} is {a['status']}; it can't change.")
            if not reason.strip():
                raise RuleViolation("REASON", "Every amended line records why.")

        self.store.append(actor=actor.id, actor_role=actor.role, type="amendment.changed", node=key, version=f"amend:{amd_id}",
                          payload={"amd_id": amd_id, "key": key, "label": label or (self.idx.lines[self.version][key].label
                                                                                    if key in self.idx.lines[self.version] else key),
                                   "as_filed": frm, "to_value": to_value, "reason": reason.strip(), "refs": refs or [],
                                   "finding_id": finding_id, "tax_effect": effect.model_dump()}, guard=guard)
        return self.amendment(amd_id)

    def amend_from_finding(self, actor: Actor, amd_id: str, finding_id: str, reason: str) -> dict[str, Any]:
        f = next((x for x in self.health.checks(self.version).findings if x.id == finding_id), None)
        if f is None or f.fix is None:
            raise Conflict("NO_FIX", "That finding has no computed fix.")
        out: dict[str, Any] = {}
        for ch in f.fix.changes:
            out = self.amend_line(actor, amd_id, ch.key, ch.to_value, reason or f.title, refs=f.refs, finding_id=f.id,
                                  label=ch.label)
        return out

    def remove_amend_line(self, actor: Actor, amd_id: str, key: str) -> dict[str, Any]:
        a = self._amd_open(actor, amd_id)

        def guard() -> None:
            self._require(actor, PREPARE_ROLES, "change an amendment")
            if a["status"] != "draft":
                raise Conflict("LOCKED", f"{amd_id} is {a['status']}.")
            if not any(c["key"] == key for c in a["changes"]):
                raise Conflict("NOT_CHANGED", f"{key} is not changed in {amd_id}.")

        self.store.append(actor=actor.id, actor_role=actor.role, type="amendment.change_removed", node=key,
                          version=f"amend:{amd_id}", payload={"amd_id": amd_id, "key": key}, guard=guard)
        return self.amendment(amd_id)

    def approve_amendment(self, actor: Actor, amd_id: str, note: str) -> dict[str, Any]:
        a = self._amd_open(actor, amd_id)

        def guard() -> None:
            self._require(actor, {"partner"}, "approve an amendment")
            if a["status"] != "draft":
                raise Conflict("NOT_DRAFT", f"{amd_id} is {a['status']}.")
            if not a["changes"]:
                raise Conflict("EMPTY", "Nothing is amended yet.")
            if actor.id == a["actor"] or any(c["actor"] == actor.id for c in a["changes"]):
                raise RuleViolation("NO_SELF_REVIEW", "You prepared this amendment.")
            if not note.strip():
                raise RuleViolation("NOTE", "Record the basis for approving.")

        self.store.append(actor=actor.id, actor_role=actor.role, type="amendment.approved", node="return",
                          version=f"amend:{amd_id}", payload={"amd_id": amd_id, "note": note.strip()}, guard=guard)
        return self.amendment(amd_id)

    def amendment(self, amd_id: str) -> dict[str, Any]:
        a = self.amendments[amd_id]
        rows = []
        fed = ca = 0.0
        for c in a["changes"]:
            frm = c["as_filed"] if isinstance(c["as_filed"], (int, float)) else 0
            fx = c["tax_effect"]
            fed += fx["federal_balance_due"]
            ca += fx["california_balance_due"]
            rows.append({"key": c["key"], "label": c["label"], "as_filed": c["as_filed"], "net_change": round(c["to_value"] - frm, 2),
                         "corrected": c["to_value"], "reason": c["reason"], "refs": c["refs"], "finding_id": c.get("finding_id"),
                         "actor_name": c["actor_name"], "at": c["at"], "tax_effect": fx})
        base = self.filed["snapshot"]["figures"] if self.filed else None
        return {"id": a["id"], "status": a["status"], "reason": a["reason"], "actor_name": a["actor_name"], "at": a["at"],
                "base_snapshot": a["base_snapshot"], "intact_base": bool(self.filed and self.filed["snapshot_hash"] == a["base_snapshot"]),
                "rows": rows, "history": a["history"],
                "effect": {"federal_balance_due": round(fed, 2), "california_balance_due": round(ca, 2),
                           "basis": "tax_effect_rates estimate per line (ESTIMATE — not an engine recompute)"},
                "as_filed": base,
                "requires_partner": abs(fed) > self.changes.threshold or abs(ca) > self.changes.threshold}

    def list_amendments(self) -> list[dict[str, Any]]:
        return [self.amendment(k) for k in sorted(self.amendments, key=lambda k: -self.amendments[k]["seq"])]

    # ================================================================ notices
    NOTICE_LINES = {   # which return lines each Letter 566 item examines
        0: ["SchA.12", "SchA.11", "SchA.14", "F8283.A1.stock", "F8283.A1.vehicle"],
        1: ["SchC.1"],
    }

    def notices(self) -> list[dict[str, Any]]:
        out = []
        for i, n in enumerate(self.raw["tax_agency_records"]["notices"]):
            out.append({**n, "index": i, "response": self.responses.get(n["id"])})
        return out

    def _line_record(self, key: str, as_filed: dict[str, Any]) -> dict[str, Any]:
        r = self.review
        v = self.version
        lines = self.idx.lines[v]
        ln = lines.get(key)
        _keys, evs = r.closure(key, v)
        direct = [s for s in (ln.sources if ln else [])]
        evidence = []
        for ev in sorted(evs, key=lambda e: (self.idx.values[e].document_id, self.idx.values[e].page)):
            val = self.idx.values[ev]
            doc = self.idx.documents[val.document_id]
            verifs = [r._verification(r.verifications[i]).model_dump() for i in r.by_node.get(ev, {}).get("verifications", [])]
            corr = r.active_correction(ev)
            red = val.value_type in ("ssn", "account_number")
            evidence.append({
                "ev": ev, "document_id": doc.id, "document": doc.title, "issuer": doc.issuer, "page": val.page,
                "position": val.position.model_dump(), "field": val.field, "label": val.label,
                "value": mask_keep_last4(str(val.value)) if red else val.value,
                "text_as_read": mask_keep_last4(val.text_as_read) if red else val.text_as_read,
                "effective": r.effective(ev) if not red else None, "correction": corr,
                "confidence": val.confidence, "direct": ev in direct,
                "verifications": [x for x in verifs if x.get("status") != "withdrawn"],
            })
        line_verifs = [r._verification(r.verifications[i]).model_dump() for i in r.by_node.get(key, {}).get("verifications", [])]
        signoffs = [r._signoff(r.signoffs[i]).model_dump() for i in r.by_node.get(key, {}).get("signoffs", [])]
        notes = [r._note(r.notes[i]).model_dump() for i in r.by_node.get(key, {}).get("notes", [])]
        adjs = [{"id": a["id"], "title": a["title"], "reason": a["reason"], "approved_by": a.get("approved_by")}
                for a in r.active_adjustments(v) if any(c["key"] == key for c in a["changes"])]
        return {"key": key, "label": ln.label if ln else key, "as_filed": as_filed.get(key),
                "engine_value": ln.value if ln else None, "rule": ln.rule if ln else None,
                "inputs": ln.inputs if ln else [], "evidence": evidence,
                "verifications": [x for x in line_verifs if x.get("status") != "withdrawn"], "signoffs": signoffs,
                "notes": notes, "adjustments": adjs}

    def _schc_reconciliation(self, rec: dict[str, Any], question: str) -> dict[str, Any]:
        """Schedule C gross receipts vs the third-party forms the letter names.

        The engine's rule for SchC.1 (its note on the line): books revenue plus Form 1099-K
        amounts not matched to a books deposit. The 1099-NECs are inside books revenue, so
        the bridge is: NEC per IRS + other books revenue + unmatched 1099-K = reported."""
        irs = {k: float(v.replace(",", "")) for k, v in
               re.findall(r"Forms? (1099-NEC|1099-K) \(([\d,]+)\)", question)}
        docs: dict[str, float] = {}
        books = nec = k1099 = 0.0
        for e in rec["evidence"]:
            if not (e["direct"] and isinstance(e["effective"], (int, float))):
                continue
            title = self.idx.documents[e["document_id"]].title
            docs[title] = docs.get(title, 0) + float(e["effective"])
            if "1099-NEC" in title:
                nec += float(e["effective"])
            elif "1099-K" in title:
                k1099 += float(e["effective"])
            else:
                books += float(e["effective"])
        filed = float(rec["as_filed"]) if isinstance(rec["as_filed"], (int, float)) else 0.0
        line = self.idx.lines[self.version].get(rec["key"])
        irs_nec, irs_k = irs.get("1099-NEC", nec), irs.get("1099-K", k1099)
        bridge = [
            {"label": "Forms 1099-NEC (per IRS letter)", "amount": irs_nec},
            {"label": "Other books revenue not on a 1099-NEC (books − NEC)", "amount": round(books - nec, 2)},
            {"label": "Form 1099-K receipts not matched to a books deposit", "amount": round(filed - books, 2)},
        ]
        return {"reported": filed, "irs_1099_nec": irs_nec, "irs_1099_k": irs_k, "books_revenue": books,
                "file_1099_nec": nec, "file_1099_k": k1099, "by_document": docs, "bridge": bridge,
                "bridge_total": round(sum(b["amount"] for b in bridge), 2),
                "file_agrees_with_irs": abs(nec - irs_nec) < 0.5 and abs(k1099 - irs_k) < 0.5,
                "engine_rule": line.note if line else None,
                "observation": (f"The unmatched 1099-K amount ({filed - books:,.0f}) equals the whole 1099-K ({k1099:,.0f}). "
                                "Confirm none of those card receipts were already deposited into the books — "
                                "if they were, gross receipts are overstated."
                                if abs((filed - books) - k1099) < 0.5 and k1099 else None)}

    def assemble_response(self, actor: Actor, notice_id: str) -> dict[str, Any]:
        notices = {n["id"]: (i, n) for i, n in enumerate(self.raw["tax_agency_records"]["notices"])}
        if notice_id not in notices:
            raise RuleViolation("UNKNOWN", f"No notice {notice_id}.")
        i, n = notices[notice_id]
        if not self.filed:
            raise Conflict("NOT_FILED", "A notice response is assembled from the filed return.")
        as_filed = self.filed["snapshot"]["values"]
        items = []
        for k, text in enumerate(n.get("items_under_examination", [])):
            recs = [self._line_record(key, as_filed) for key in self.NOTICE_LINES.get(k, [])
                    if key in as_filed or key in self.idx.lines[self.version]]
            item = {"index": k, "question": text, "lines": recs}
            if k == 1 and recs:
                item["reconciliation"] = self._schc_reconciliation(recs[0], text)
            docs = sorted({e["document_id"] for r_ in recs for e in r_["evidence"]})
            item["documents"] = [{"id": d, "title": self.idx.documents[d].title, "issuer": self.idx.documents[d].issuer,
                                  "pages": self.idx.documents[d].page_count} for d in docs]
            unverified = [e["ev"] for r_ in recs for e in r_["evidence"] if not e["verifications"]]
            item["gaps"] = ([f"{len(unverified)} source value(s) have no verification recorded"] if unverified else [])
            items.append(item)
        record = {"notice": n, "household": self.raw["household"]["people"][0]["name"] + " & " +
                  self.raw["household"]["people"][1]["name"], "tax_year": n["tax_year"],
                  "filed": {"accepted_at": self.filed["accepted_at"], "submissions": self.filed["submissions"],
                            "snapshot_hash": self.filed["snapshot_hash"]},
                  "items": items, "firm": {"name": self.raw["firm"]["name"],
                                           "address": self.raw["firm"]["firm_identity"]["address"]},
                  "assembled_by": actor.name}
        rhash = _fp(record)

        def guard() -> None:
            self._require(actor, PREPARE_ROLES, "assemble a notice response")

        self.store.append(actor=actor.id, actor_role=actor.role, type="notice.response_assembled", node=notice_id,
                          version=self.version, payload={"notice_id": notice_id, "record": record, "record_hash": rhash,
                                                         "as_of_seq": self.store.last_seq()}, guard=guard)
        return self.responses[notice_id]

    def mark_response_sent(self, actor: Actor, notice_id: str, note: str) -> dict[str, Any]:
        def guard() -> None:
            self._require(actor, {"partner"}, "send a notice response")
            if notice_id not in self.responses:
                raise Conflict("NOT_ASSEMBLED", "Assemble the response first.")
            if self.responses[notice_id]["sent"]:
                raise Conflict("ALREADY_SENT", "Already sent.")

        self.store.append(actor=actor.id, actor_role=actor.role, type="notice.response_sent", node=notice_id,
                          payload={"notice_id": notice_id, "note": note.strip()}, guard=guard)
        return self.responses[notice_id]

    # ================================================================ carry forward
    CO_LABELS = {
        "capital_loss_short": "Short-term capital loss", "capital_loss_long": "Long-term capital loss",
        "passive_1450_fremont": "Passive loss — 1450 Fremont Way", "passive_1200_barton_hills": "Passive loss — 1200 Barton Hills",
        "minimum_tax_credit_from_2025_amt": "Minimum tax credit (Form 8801)", "charitable": "Charitable contributions",
        "section_179": "Section 179", "ira_nondeductible_basis_ngozi": "IRA nondeductible basis (Ngozi)",
        "scorp_stock_basis_end": "S corporation stock basis (end of year)",
        "ridgeline_capital_account_end": "Ridgeline capital account (end of year)",
        "sep_contribution_not_deductible_for_2025": "SEP contribution not deductible for 2025",
    }
    CO_IN = {"capital_loss_short": "capital_loss_short", "capital_loss_long": "capital_loss_long",
             "passive_1450_fremont": "passive_1450_fremont", "passive_1200_barton_hills": "passive_1200_barton_hills",
             "minimum_tax_credit_from_2025_amt": "amt_credit", "charitable": "charitable"}

    def carryforward(self) -> dict[str, Any]:
        cin = self.raw["prior_years"]["carryovers_into_2025"]
        versions = [v.version for v in self.p.return_versions]
        outs = {v["version"]: v["carryovers_out"] for v in self.raw["return_versions"]}
        filed_v = self.filed["snapshot"]["version"] if self.filed else self.version
        amd = [a for a in self.amendments.values()]
        rows = []
        for key, label in self.CO_LABELS.items():
            hist = [{"version": v, "value": outs[v]["federal"].get(key)} for v in versions]
            out_val = next(h["value"] for h in hist if h["version"] == filed_v)
            prior = cin.get(self.CO_IN[key]) if key in self.CO_IN else None
            changes = [f"{a['version']}: {a['value']:,} → {b['value']:,}" for a, b in zip(hist, hist[1:])
                       if isinstance(a["value"], (int, float)) and isinstance(b["value"], (int, float)) and a["value"] != b["value"]]
            rows.append({"key": key, "label": label, "into_2025": prior, "out_2026": out_val, "history": hist,
                         "changes": changes, "jurisdiction": "federal",
                         "used_2025": (round(prior - out_val, 2) if isinstance(prior, (int, float)) and isinstance(out_val, (int, float)) else None)})
        ca_out = outs[filed_v]["california"]
        ca_rows = []
        for key, val in ca_out.items():
            if key == "depreciation_basis_differences":
                for asset, amt in val.items():
                    ca_rows.append({"key": f"ca.basis.{asset}", "label": f"CA depreciation basis difference — {asset}",
                                    "into_2025": None, "out_2026": amt, "jurisdiction": "california"})
            else:
                ca_rows.append({"key": f"ca.{key}", "label": f"California {key.replace('_', ' ')}",
                                "into_2025": cin.get("california", {}).get(key), "out_2026": val, "jurisdiction": "california"})
        plan = self.raw["planning_reference_2026"]
        fig = (self.filed["snapshot"]["figures"] if self.filed else self.figures())
        fed_tax, ca_tax = fig["federal"]["total_tax"], fig["california"]["total_tax"]
        fed_sh = round(fed_tax * 1.10)
        ca_sh = round(ca_tax * 1.10)
        estimates = {
            "federal": {"rule": plan["federal_safe_harbor"], "basis_2025_tax": fed_tax, "safe_harbor_total": fed_sh,
                        "installments": [{"due": d, "amount": round(fed_sh / 4)} for d in plan["federal_estimate_due_dates"]]},
            "california": {"rule": plan["california_safe_harbor"], "basis_2025_tax": ca_tax, "safe_harbor_total": ca_sh,
                           "installments": [{"due": d, "amount": round(ca_sh * pct)} for d, pct in
                                            zip(plan["california_estimate_due_dates"], plan["california_installment_percentages"])],
                           "caveat": "110% of 2025 California tax is the safe-harbor ceiling; 2026 California tax will be "
                                     "far lower (nonresident: only California-source income). 90% of 2026 tax is likely smaller."},
        }
        return {"filed_version": filed_v, "filed": bool(self.filed), "federal": rows, "california": ca_rows,
                "sources": {"into_2025": cin.get("sources"), "out": f"return_versions[{filed_v}].carryovers_out"},
                "amendments": [{"id": a["id"], "status": a["status"]} for a in amd],
                "planning": {"known_changes": plan["known_2026_changes_for_this_household"], "estimates": estimates,
                             "basis": fig.get("basis")},
                "rolled": self.rolled}

    def roll_forward(self, actor: Actor, note: str) -> dict[str, Any]:
        cf = self.carryforward()

        def guard() -> None:
            self._require(actor, PREPARE_ROLES, "roll the file forward")
            if not self.filed:
                raise Conflict("NOT_FILED", "Roll forward from the filed return.")
            if self.rolled:
                raise Conflict("ALREADY_ROLLED", "The 2026 file is already opened.")

        self.store.append(actor=actor.id, actor_role=actor.role, type="carryforward.rolled", node="return",
                          version=self.version,
                          payload={"tax_year": 2026, "from_snapshot": self.filed["snapshot_hash"] if self.filed else None,
                                   "carryovers": {r_["key"]: r_["out_2026"] for r_ in cf["federal"] + cf["california"]},
                                   "history": {r_["key"]: r_.get("history") for r_ in cf["federal"]},
                                   "planning": cf["planning"], "note": note.strip()}, guard=guard)
        return self.carryforward()


__all__ = ["LifecycleService", "Gate", "GateItem", "FROZEN_TYPES"]
