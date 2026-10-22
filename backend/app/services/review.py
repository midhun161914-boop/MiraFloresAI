"""The review layer: verifications, review notes, sign-offs, value corrections,
assignments and the sensitive-data view log, all as events.

State is a projection: it is rebuilt by folding the event log at startup and kept
current by applying each new event as it is appended. Commands check the firm's
rules (``firm.starter_standards.rules``) *inside the store's write lock* and only
then append; a refused command writes nothing.

Sign-offs and verifications capture a fingerprint of the evidence beneath the
node (every extracted value reachable through its sources and inputs, at its
current effective value). When a correction changes any of those values, every
active sign-off that covered it is reopened by an automatic event that records
exactly what changed.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel

from app.services.actors import Actor
from app.services.events import Event, EventStore
from app.services.loader import PacketIndex
from app.services.redact import SENSITIVE_VALUE_TYPES
from app.services.trace import EV, TraceIndex

SYSTEM = Actor(id="system", name="Workpaper (automatic)", kind="staff", role="system", sensitive_data_clearance=True)

PREPARE_ROLES = {"preparer", "reviewer", "partner"}
REVIEW_ROLES = {"reviewer", "partner"}
NOTE_ROLES = {"preparer", "reviewer", "partner", "quality_reviewer"}
LEVEL_ROLES = {"preparer": PREPARE_ROLES, "reviewer": REVIEW_ROLES, "partner": {"partner"}}
VIEW_COALESCE = timedelta(seconds=30)


# ------------------------------------------------------------------ errors
class RuleViolation(Exception):
    """A firm rule refuses the action (HTTP 403)."""

    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


class Conflict(Exception):
    """Someone else changed the item since the caller loaded it (HTTP 409)."""

    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


# ------------------------------------------------------------------ models
class Change(BaseModel):
    ev: str
    was: Any = None
    now: Any = None


class Verification(BaseModel):
    id: str
    seq: int
    node: str
    version: Optional[str]
    method: str
    note: str = ""
    actor: str
    actor_name: str
    at: str
    status: Literal["current", "stale", "withdrawn"]
    changed: list[Change] = []


class NoteEntry(BaseModel):
    seq: int
    at: str
    actor: str
    actor_name: str
    kind: Literal["opened", "replied", "resolved", "reopened"]
    text: str = ""


class Note(BaseModel):
    id: str
    node: str
    version: Optional[str]
    text: str
    blocking: bool
    status: Literal["open", "resolved"]
    author: str
    author_name: str
    at: str
    last_seq: int
    thread: list[NoteEntry]


class SignOff(BaseModel):
    id: str
    seq: int
    node: str
    version: Optional[str]
    level: Literal["preparer", "reviewer", "partner"]
    actor: str
    actor_name: str
    at: str
    fingerprint: str
    status: Literal["active", "reopened", "withdrawn"]
    reopened_at: Optional[str] = None
    reopened_reason: Optional[str] = None
    changed: list[Change] = []


class Correction(BaseModel):
    id: str
    seq: int
    ev: str
    from_value: Any
    to_value: Any
    reason: str
    actor: str
    actor_name: str
    at: str
    active: bool


class Permission(BaseModel):
    allowed: bool
    reason: Optional[str] = None


class NodeReview(BaseModel):
    node: str
    version: Optional[str]
    fingerprint: str
    evidence_count: int
    verifications: list[Verification]
    notes: list[Note]
    signoffs: list[SignOff]
    correction: Optional[Correction] = None
    corrections_beneath: list[Correction] = []
    preparers: list[str]
    permissions: dict[str, Permission]


class NodeSummary(BaseModel):
    verified: int = 0
    stale: int = 0
    open_notes: int = 0
    blocking: int = 0
    signed: list[str] = []
    reopened: int = 0


class Blocker(BaseModel):
    kind: Literal["blocking_note", "reopened_signoff", "missing_signoff", "pending_adjustment"]
    node: str
    title: str
    detail: str = ""
    ref_id: Optional[str] = None


class Readiness(BaseModel):
    version: str
    ready: bool
    blockers: list[Blocker]
    warnings: list[Blocker]


class Assignment(BaseModel):
    role: str
    actor: str
    actor_name: str
    at: str


# ------------------------------------------------------------------ service
def _fp(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


class ReviewService:
    def __init__(self, idx: PacketIndex, trace: TraceIndex, store: EventStore, actors: dict[str, Actor]):
        self.idx, self.trace, self.store, self.actors = idx, trace, store, actors
        self.methods = list(idx.packet.firm.starter_standards.verification_types)
        self._memo: dict[tuple[str, str], tuple[frozenset[str], frozenset[str]]] = {}
        self._reset()
        for ev in store.all():
            self._apply(ev)
        store.subscribe(self._apply)
        if not self.assignments:
            self._seed_assignments()

    # ---------------------------------------------------------------- projection
    def _reset(self) -> None:
        self.verifications: dict[str, dict[str, Any]] = {}
        self.notes: dict[str, dict[str, Any]] = {}
        self.signoffs: dict[str, dict[str, Any]] = {}
        self.corrections: dict[str, list[dict[str, Any]]] = defaultdict(list)  # ev -> history
        self.assignments: dict[str, dict[str, Any]] = {}
        self._last_view: dict[tuple[str, str, bool], datetime] = {}
        self.dispositions: dict[str, dict[str, Any]] = {}      # finding id -> latest disposition
        self.variance_notes: dict[str, dict[str, Any]] = {}    # line key -> latest explanation
        self.adjustments: dict[str, dict[str, Any]] = {}       # adj id -> state
        self.saved_states: list[dict[str, Any]] = []
        self.seen: dict[str, int] = {}                         # actor -> last seq they marked seen
        self.bulks: dict[str, dict[str, Any]] = {}
        self.by_node: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    def _apply(self, e: Event) -> None:
        p = e.payload
        t = e.type
        if p.get("bulk_id") and t not in ("bulk.started", "bulk.undone") and p["bulk_id"] in getattr(self, "bulks", {}):
            self.bulks[p["bulk_id"]]["events"].append({"id": e.id, "type": t, "node": e.node, "payload": p})
        if t == "assignment.set":
            self.assignments[p["role"]] = {"actor": p["actor_id"], "at": e.at}
        elif t == "verification.recorded":
            self.verifications[e.id] = {**p, "id": e.id, "seq": e.seq, "node": e.node, "version": e.version,
                                        "actor": e.actor, "at": e.at, "withdrawn": False}
            self.by_node[e.node]["verifications"].append(e.id)
        elif t == "verification.withdrawn" and e.reverts in self.verifications:
            self.verifications[e.reverts]["withdrawn"] = True
        elif t == "note.opened":
            nid = p["note_id"]
            self.notes[nid] = {"id": nid, "node": e.node, "version": e.version, "text": p["text"],
                               "blocking": bool(p.get("blocking")), "status": "open", "author": e.actor,
                               "at": e.at, "last_seq": e.seq,
                               "thread": [{"seq": e.seq, "at": e.at, "actor": e.actor, "kind": "opened", "text": p["text"]}]}
            self.by_node[e.node]["notes"].append(nid)
        elif t in ("note.replied", "note.resolved", "note.reopened") and p.get("note_id") in self.notes:
            n = self.notes[p["note_id"]]
            kind = t.split(".")[1]
            n["thread"].append({"seq": e.seq, "at": e.at, "actor": e.actor, "kind": kind, "text": p.get("text", "")})
            n["last_seq"] = e.seq
            if kind == "resolved":
                n["status"] = "resolved"
            elif kind == "reopened":
                n["status"] = "open"
        elif t == "signoff.recorded":
            self.signoffs[e.id] = {**p, "id": e.id, "seq": e.seq, "node": e.node, "version": e.version,
                                   "actor": e.actor, "at": e.at, "status": "active"}
            self.by_node[e.node]["signoffs"].append(e.id)
        elif t == "signoff.withdrawn" and e.reverts in self.signoffs:
            self.signoffs[e.reverts]["status"] = "withdrawn"
        elif t == "signoff.reopened" and e.reverts in self.signoffs:
            s = self.signoffs[e.reverts]
            if s["status"] == "active":
                s.update(status="reopened", reopened_at=e.at, reopened_reason=p.get("reason"),
                         reopen_changed=p.get("changed", []))
        elif t == "value.corrected":
            self.corrections[e.node].append({**p, "id": e.id, "seq": e.seq, "actor": e.actor, "at": e.at, "active": True})
        elif t == "value.correction_reverted":
            for c in self.corrections.get(e.node, []):
                if c["id"] == e.reverts:
                    c["active"] = False
        elif t == "finding.dispositioned":
            if p.get("disposition") == "reopened":
                self.dispositions.pop(p["finding_id"], None)
            else:
                self.dispositions[p["finding_id"]] = {"disposition": p["disposition"], "note": p.get("note", ""),
                                                      "actor": e.actor, "actor_name": self.name(e.actor), "at": e.at,
                                                      "seq": e.seq}
        elif t == "variance.explained":
            self.variance_notes[e.node or ""] = {"text": p.get("text", ""), "actor": e.actor,
                                                 "actor_name": self.name(e.actor), "at": e.at, "seq": e.seq}
        elif t == "adjustment.proposed":
            self.adjustments[p["adj_id"]] = {
                **p, "id": p["adj_id"], "seq": e.seq, "actor": e.actor, "actor_name": self.name(e.actor), "at": e.at,
                "status": "pending_partner" if p.get("requires_partner") else "active",
                "history": [{"seq": e.seq, "at": e.at, "actor": e.actor, "actor_name": self.name(e.actor),
                             "kind": "proposed", "note": p.get("reason", "")}]}
        elif t in ("adjustment.approved", "adjustment.rejected", "adjustment.reversed") and p.get("adj_id") in self.adjustments:
            a = self.adjustments[p["adj_id"]]
            kind = t.split(".")[1]
            a["status"] = {"approved": "active", "rejected": "rejected", "reversed": "reversed"}[kind]
            a["history"].append({"seq": e.seq, "at": e.at, "actor": e.actor, "actor_name": self.name(e.actor),
                                 "kind": kind, "note": p.get("note", "")})
            if kind == "approved":
                a["approved_by"], a["approved_at"] = self.name(e.actor), e.at
        elif t == "state.saved":
            self.saved_states.append({"id": e.id, "name": p.get("name", ""), "as_of_seq": p.get("as_of_seq", e.seq),
                                      "version": e.version, "actor": e.actor, "actor_name": self.name(e.actor), "at": e.at})
        elif t == "user.seen":
            self.seen[e.actor] = max(self.seen.get(e.actor, 0), int(p.get("seq", e.seq)))
        elif t == "bulk.started":
            self.bulks[p["bulk_id"]] = {"id": p["bulk_id"], "action": p["action"], "params": p.get("params", {}),
                                        "actor": e.actor, "actor_name": self.name(e.actor), "at": e.at, "seq": e.seq,
                                        "events": [], "refused": p.get("refused", []), "undone": False, "undo": None}
        elif t == "bulk.undone" and p.get("bulk_id") in self.bulks:
            self.bulks[p["bulk_id"]].update(undone=True, undo={"actor_name": self.name(e.actor), "at": e.at,
                                                              "reversed": p.get("reversed", 0), "refused": p.get("refused", [])})
        elif t == "view.logged":
            self._last_view[(e.actor, e.node or "", bool(p.get("masked")))] = _parse(e.at)

    # ---------------------------------------------------------------- helpers
    def name(self, actor_id: str) -> str:
        if actor_id == SYSTEM.id:
            return SYSTEM.name
        a = self.actors.get(actor_id)
        return a.name if a else actor_id

    def _seed_assignments(self) -> None:
        for role, actor_id in self.idx.packet.firm.assignment_at_start.model_dump().items():
            self.store.append(actor=SYSTEM.id, actor_role=SYSTEM.role, type="assignment.set",
                              node="engagement", payload={"role": role, "actor_id": actor_id,
                                                          "source": "firm.assignment_at_start"})

    def active_correction(self, ev: str) -> Optional[dict[str, Any]]:
        hist = [c for c in self.corrections.get(ev, []) if c["active"]]
        return hist[-1] if hist else None

    def effective(self, ev: str) -> Any:
        c = self.active_correction(ev)
        return c["to"] if c else self.idx.values[ev].value

    def _version(self, version: Optional[str]) -> str:
        return version or self.idx.current_version

    def node_exists(self, node: str, version: Optional[str]) -> bool:
        v = self._version(version)
        return (node == "return" or node in self.idx.lines[v] or node in self.idx.values
                or node in self.idx.documents)

    def closure(self, node: str, version: Optional[str]) -> tuple[frozenset[str], frozenset[str]]:
        """(line keys, extracted values) beneath a node."""
        return self._closure(node, self._version(version))

    def _closure(self, node: str, v: str) -> tuple[frozenset[str], frozenset[str]]:
        """Static per (node, version): the packet does not change, only effective values do."""
        key = (node, v)
        if key in self._memo:
            return self._memo[key]
        lines = self.idx.lines[v]
        if node in self.idx.values:
            out = (frozenset(), frozenset({node}))
        elif node in self.idx.documents:
            out = (frozenset(), frozenset(e.id for e in self.idx.values_by_doc.get(node, [])))
        elif node == "return":
            evs: set[str] = set()
            for ln in lines.values():
                evs |= self._closure(ln.key, v)[1]
            out = (frozenset(lines), frozenset(evs))
        elif node in lines:
            graph = self.trace.graph(node, v)
            keys = frozenset(graph.nodes) if graph else frozenset({node})
            evs = set()
            for k in keys:
                for s in lines[k].sources:
                    if EV.fullmatch(s):
                        evs.add(s)
                    else:
                        evs.update(self.trace.evs_behind(s, v))
            out = (keys, frozenset(evs))
        else:
            out = (frozenset(), frozenset())
        self._memo[key] = out
        return out

    def snapshot(self, node: str, version: Optional[str]) -> dict[str, Any]:
        return {ev: self.effective(ev) for ev in sorted(self.closure(node, version)[1])}

    def return_adjusted(self, version: Optional[str]) -> dict[str, Any]:
        """The return-level part of a sign-off: every line value an active adjustment sets."""
        return {k: row["value"] for k, row in sorted(self.adjusted_values(self._version(version)).items())}

    def fingerprint(self, node: str, version: Optional[str]) -> str:
        v = self._version(version)
        line = self.idx.lines[v].get(node)
        payload: dict[str, Any] = {"node": node, "value": line.value if line else None, "evidence": self.snapshot(node, v)}
        if node == "return":   # the return as signed = its evidence *and* the adjustments in force
            payload["adjusted"] = self.return_adjusted(v)
        return _fp(payload)

    def _diff(self, snap: dict[str, Any]) -> list[Change]:
        return [Change(ev=ev, was=was, now=self.effective(ev)) for ev, was in snap.items()
                if ev in self.idx.values and self.effective(ev) != was]

    def preparers(self, node: str, version: Optional[str]) -> set[str]:
        """Everyone who did preparer work on this node or anything beneath it."""
        lines, evs = self.closure(node, version)
        scope = set(lines) | set(evs) | {node}
        out = {v["actor"] for v in self.verifications.values() if not v["withdrawn"] and v["node"] in scope}
        out |= {s["actor"] for s in self.signoffs.values()
                if s["level"] == "preparer" and s["status"] != "withdrawn" and s["node"] in scope}
        out |= {c["actor"] for ev in evs for c in self.corrections.get(ev, []) if c["active"]}
        if node == "return":   # whoever proposed an adjustment in force (or pending) prepared the return
            v = self._version(version)
            out |= {a["actor"] for a in self.adjustments.values()
                    if a.get("version") == v and a["status"] in ("active", "pending_partner")}
        return out

    # ---------------------------------------------------------------- adjustments (projection helpers)
    def adjustment_for_finding(self, finding_id: str) -> Optional[dict[str, Any]]:
        hits = [a for a in self.adjustments.values()
                if a.get("finding_id") == finding_id and a["status"] in ("active", "pending_partner")]
        return hits[-1] if hits else None

    def active_adjustments(self, version: Optional[str] = None, as_of_seq: Optional[int] = None) -> list[dict[str, Any]]:
        v = self._version(version)
        out = []
        for a in self.adjustments.values():
            if a.get("version") != v:
                continue
            if as_of_seq is None:
                if a["status"] == "active":
                    out.append(a)
                continue
            # Replay: the adjustment's state as of that seq.
            state = None
            for h in a["history"]:
                if h["seq"] > as_of_seq:
                    break
                state = {"proposed": "pending_partner" if a.get("requires_partner") else "active",
                         "approved": "active", "rejected": "rejected", "reversed": "reversed"}[h["kind"]]
            if state == "active":
                out.append(a)
        return sorted(out, key=lambda a: a["seq"])

    def adjusted_values(self, version: Optional[str] = None, as_of_seq: Optional[int] = None) -> dict[str, dict[str, Any]]:
        """line key -> {value, original, label, adjustments[]} for every line an active adjustment touches."""
        v = self._version(version)
        lines = self.idx.lines[v]
        out: dict[str, dict[str, Any]] = {}
        for a in self.active_adjustments(v, as_of_seq):
            for ch in a["changes"]:
                cur = out.get(ch["key"])
                orig = lines[ch["key"]].value if ch["key"] in lines else None
                out[ch["key"]] = {"value": ch["to_value"], "original": cur["original"] if cur else orig,
                                  "label": ch.get("label") or (lines[ch["key"]].label if ch["key"] in lines else ch["key"]),
                                  "new_line": ch["key"] not in lines,
                                  "adjustments": (cur["adjustments"] if cur else []) + [a["id"]]}
        return out

    # ---------------------------------------------------------------- views
    def _verification(self, v: dict[str, Any]) -> Verification:
        changed = self._diff(v.get("evidence", {}))
        status = "withdrawn" if v["withdrawn"] else "stale" if changed else "current"
        return Verification(id=v["id"], seq=v["seq"], node=v["node"], version=v["version"], method=v["method"],
                            note=v.get("note", ""), actor=v["actor"], actor_name=self.name(v["actor"]),
                            at=v["at"], status=status, changed=changed)

    def _note(self, n: dict[str, Any]) -> Note:
        return Note(id=n["id"], node=n["node"], version=n["version"], text=n["text"], blocking=n["blocking"],
                    status=n["status"], author=n["author"], author_name=self.name(n["author"]), at=n["at"],
                    last_seq=n["last_seq"],
                    thread=[NoteEntry(**x, actor_name=self.name(x["actor"])) for x in n["thread"]])

    def _signoff(self, s: dict[str, Any]) -> SignOff:
        changed = [Change(**c) for c in s.get("reopen_changed", [])] if s["status"] == "reopened" else []
        return SignOff(id=s["id"], seq=s["seq"], node=s["node"], version=s["version"], level=s["level"],
                       actor=s["actor"], actor_name=self.name(s["actor"]), at=s["at"], fingerprint=s["fingerprint"],
                       status=s["status"], reopened_at=s.get("reopened_at"), reopened_reason=s.get("reopened_reason"),
                       changed=changed)

    def _correction(self, c: dict[str, Any], ev: str) -> Correction:
        return Correction(id=c["id"], seq=c["seq"], ev=ev, from_value=c["from"], to_value=c["to"],
                          reason=c["reason"], actor=c["actor"], actor_name=self.name(c["actor"]),
                          at=c["at"], active=c["active"])

    def node_review(self, node: str, version: Optional[str], actor: Actor) -> NodeReview:
        v = self._version(version)
        rec = self.by_node.get(node, {})
        corr = self.active_correction(node) if node in self.idx.values else None
        _, evs = self.closure(node, v)
        beneath = [self._correction(c, ev) for ev in sorted(evs) if ev != node
                   for c in self.corrections.get(ev, []) if c["active"]]
        perms = {name: self._permission(fn) for name, fn in {
            "verify": lambda: self._check_verify(actor, node, v),
            "note": lambda: self._check_note(actor, blocking=False),
            "note_blocking": lambda: self._check_note(actor, blocking=True),
            "signoff_preparer": lambda: self._check_signoff(actor, node, v, "preparer"),
            "signoff_reviewer": lambda: self._check_signoff(actor, node, v, "reviewer"),
            "signoff_partner": lambda: self._check_signoff(actor, node, v, "partner"),
            "correct": lambda: self._check_correct(actor, node),
        }.items()}
        return NodeReview(
            node=node, version=v, fingerprint=self.fingerprint(node, v), evidence_count=len(evs),
            verifications=[self._verification(self.verifications[i]) for i in rec.get("verifications", [])],
            notes=[self._note(self.notes[i]) for i in rec.get("notes", [])],
            signoffs=[self._signoff(self.signoffs[i]) for i in rec.get("signoffs", [])],
            correction=self._correction(corr, node) if corr else None,
            corrections_beneath=beneath[:50],
            preparers=sorted(self.preparers(node, v)),
            permissions=perms,
        )

    @staticmethod
    def _permission(check: Any) -> Permission:
        try:
            check()
            return Permission(allowed=True)
        except (RuleViolation, Conflict) as exc:
            return Permission(allowed=False, reason=exc.message)

    def summary(self, version: Optional[str]) -> dict[str, NodeSummary]:
        v = self._version(version)
        out: dict[str, NodeSummary] = {}
        for node, rec in self.by_node.items():
            s = NodeSummary()
            for i in rec.get("verifications", []):
                vv = self._verification(self.verifications[i])
                if vv.version in (v, None) and vv.status == "current":
                    s.verified += 1
                elif vv.status == "stale":
                    s.stale += 1
            for i in rec.get("notes", []):
                n = self.notes[i]
                if n["status"] == "open":
                    s.open_notes += 1
                    s.blocking += int(n["blocking"])
            for i in rec.get("signoffs", []):
                so = self.signoffs[i]
                if so["status"] == "active":
                    s.signed.append(so["level"])
                elif so["status"] == "reopened" and not self.superseded(so):
                    s.reopened += 1
            out[node] = s
        return out

    def superseded(self, s: dict[str, Any]) -> bool:
        """A reopened sign-off is answered once the same level signs the same node again."""
        return any(o["node"] == s["node"] and o["level"] == s["level"] and o["status"] == "active" and o["seq"] > s["seq"]
                   for o in self.signoffs.values())

    def queue(self) -> dict[str, Any]:
        return {
            "open_notes": [self._note(n) for n in self.notes.values() if n["status"] == "open"],
            "reopened_signoffs": [self._signoff(s) for s in self.signoffs.values()
                                  if s["status"] == "reopened" and not self.superseded(s)],
            "stale_verifications": [x for x in (self._verification(v) for v in self.verifications.values()) if x.status == "stale"],
            "active_signoffs": [self._signoff(s) for s in self.signoffs.values() if s["status"] == "active"],
            "corrections": [self._correction(c, ev) for ev, hist in self.corrections.items() for c in hist if c["active"]],
        }

    def readiness(self, version: Optional[str]) -> Readiness:
        v = self._version(version)
        blockers: list[Blocker] = []
        warnings: list[Blocker] = []
        for n in self.notes.values():
            if n["status"] == "open" and n["blocking"]:
                blockers.append(Blocker(kind="blocking_note", node=n["node"], ref_id=n["id"],
                                        title=f"Open blocking note on {n['node']}", detail=n["text"]))
        for s in self.signoffs.values():
            if s["status"] == "reopened" and not self.superseded(s):
                blockers.append(Blocker(kind="reopened_signoff", node=s["node"], ref_id=s["id"],
                                        title=f"{s['level'].title()} sign-off on {s['node']} reopened",
                                        detail=s.get("reopened_reason") or ""))
        for a in self.adjustments.values():
            if a["status"] == "pending_partner":
                blockers.append(Blocker(kind="pending_adjustment", node=a["changes"][0]["key"], ref_id=a["id"],
                                        title=f"Adjustment {a['id']} awaits partner sign-off",
                                        detail=f"{a['title']} — tax effect over the firm's partner threshold."))
        for level in ("reviewer", "partner"):
            if not any(s["node"] == "return" and s["level"] == level and s["status"] == "active"
                       for s in self.signoffs.values()):
                warnings.append(Blocker(kind="missing_signoff", node="return",
                                        title=f"{level.title()} sign-off on the return not yet recorded"))
        return Readiness(version=v, ready=not blockers, blockers=blockers, warnings=warnings)

    def assignment_list(self) -> list[Assignment]:
        return [Assignment(role=r, actor=a["actor"], actor_name=self.name(a["actor"]), at=a["at"])
                for r, a in self.assignments.items()]

    # ---------------------------------------------------------------- rules
    @staticmethod
    def _staff(actor: Actor) -> None:
        if actor.kind != "staff":
            raise RuleViolation("CLIENT_SURFACE_ONLY", "Client users can only use the client surface.")

    def _check_verify(self, actor: Actor, node: str, v: str) -> None:
        self._staff(actor)
        if actor.role not in PREPARE_ROLES:
            raise RuleViolation("ROLE", f"A {actor.role.replace('_', ' ')} does not verify figures.")
        if not self.node_exists(node, v):
            raise RuleViolation("UNKNOWN_NODE", f"{node} is not a line, value or document in {v}.")

    def _check_note(self, actor: Actor, *, blocking: bool) -> None:
        self._staff(actor)
        if actor.role not in NOTE_ROLES:
            raise RuleViolation("ROLE", f"A {actor.role.replace('_', ' ')} does not write review notes.")

    def _check_resolve(self, actor: Actor, n: dict[str, Any]) -> None:
        self._staff(actor)
        if n["status"] != "open":
            raise Conflict("ALREADY_RESOLVED", "This note is already resolved.")
        if n["blocking"]:
            if actor.role not in REVIEW_ROLES:
                raise RuleViolation("REVIEW_REQUIRED", "A blocking note can only be cleared by a reviewer or partner.")
            if actor.id in self.preparers(n["node"], n["version"]):
                raise RuleViolation("NO_SELF_REVIEW", "You prepared this work, so you can't clear its blocking note "
                                                      "(a person may not review work they prepared).")
        elif actor.id != n["author"] and actor.role not in REVIEW_ROLES:
            raise RuleViolation("REVIEW_REQUIRED", "Only the note's author or a reviewer can resolve it.")

    def _check_signoff(self, actor: Actor, node: str, v: str, level: str) -> None:
        self._staff(actor)
        if level not in LEVEL_ROLES:
            raise RuleViolation("LEVEL", f"Unknown review level {level}.")
        if actor.role not in LEVEL_ROLES[level]:
            raise RuleViolation("ROLE", f"{level.title()} sign-off needs a {' or '.join(sorted(LEVEL_ROLES[level]))}; "
                                        f"you are acting as {actor.role.replace('_', ' ')}.")
        if not self.node_exists(node, v):
            raise RuleViolation("UNKNOWN_NODE", f"{node} is not in {v}.")
        mine = [self.signoffs[i] for i in self.by_node.get(node, {}).get("signoffs", [])]
        if any(s["level"] == level and s["status"] == "active" for s in mine):
            raise Conflict("ALREADY_SIGNED", f"{level.title()} sign-off is already active on {node}.")
        if level != "preparer" and actor.id in self.preparers(node, v):
            raise RuleViolation("NO_SELF_REVIEW", "A person may not review or sign off on work they prepared — "
                                                  "you verified, corrected or prepared something under this number.")
        blocking = [self.notes[i] for i in self.by_node.get(node, {}).get("notes", [])
                    if self.notes[i]["status"] == "open" and self.notes[i]["blocking"]]
        if blocking and level != "preparer":
            raise RuleViolation("BLOCKING_NOTE", f"{len(blocking)} open blocking note(s) on {node} must be cleared first.")
        if level == "reviewer" and node != "return":
            verified = any(self._verification(self.verifications[i]).status == "current"
                           for i in self.by_node.get(node, {}).get("verifications", []))
            prepared = any(s["level"] == "preparer" and s["status"] == "active" for s in mine)
            if not (verified or prepared):
                raise RuleViolation("NOT_PREPARED", "Nothing to review yet: the number has no current verification "
                                                    "or preparer sign-off.")
        if level == "partner" and not any(s["level"] == "reviewer" and s["status"] == "active" for s in mine):
            raise RuleViolation("ORDER", "Partner sign-off follows an active reviewer sign-off.")

    def _check_correct(self, actor: Actor, node: str) -> None:
        self._staff(actor)
        if node not in self.idx.values:
            raise RuleViolation("NOT_A_VALUE", "Only extracted values can be corrected.")
        if actor.role not in PREPARE_ROLES:
            raise RuleViolation("ROLE", f"A {actor.role.replace('_', ' ')} does not correct source values.")
        if self.idx.values[node].value_type in SENSITIVE_VALUE_TYPES and not actor.sensitive_data_clearance:
            raise RuleViolation("CLEARANCE", "This value is sensitive and you are not cleared to see or change it.")

    # ---------------------------------------------------------------- commands
    def verify(self, actor: Actor, node: str, version: Optional[str], method: str, note: str) -> Verification:
        v = self._version(version)
        if method not in self.methods:
            raise RuleViolation("METHOD", f"Use one of the firm's verification types: {', '.join(self.methods)}.")
        ev = self.store.append(
            actor=actor.id, actor_role=actor.role, type="verification.recorded", node=node, version=v,
            payload={"method": method, "note": note.strip(), "evidence": self.snapshot(node, v),
                     "fingerprint": self.fingerprint(node, v)},
            guard=lambda: self._check_verify(actor, node, v))
        return self._verification(self.verifications[ev.id])

    def withdraw_verification(self, actor: Actor, vid: str) -> Verification:
        rec = self.verifications.get(vid)

        def guard() -> None:
            self._staff(actor)
            if rec is None:
                raise RuleViolation("UNKNOWN", "No such verification.")
            if rec["actor"] != actor.id:
                raise RuleViolation("NOT_YOURS", "Only the person who recorded a verification can withdraw it.")
            if rec["withdrawn"]:
                raise Conflict("ALREADY_WITHDRAWN", "Already withdrawn.")

        self.store.append(actor=actor.id, actor_role=actor.role, type="verification.withdrawn",
                          node=rec["node"] if rec else None, reverts=vid, guard=guard)
        return self._verification(self.verifications[vid])

    def open_note(self, actor: Actor, node: str, version: Optional[str], text: str, blocking: bool) -> Note:
        v = self._version(version)
        if not text.strip():
            raise RuleViolation("EMPTY", "Write the note.")

        def guard() -> None:
            self._check_note(actor, blocking=blocking)
            if not self.node_exists(node, v):
                raise RuleViolation("UNKNOWN_NODE", f"{node} is not in {v}.")

        nid = "n-" + uuid.uuid4().hex[:8]
        self.store.append(actor=actor.id, actor_role=actor.role, type="note.opened", node=node, version=v,
                          payload={"note_id": nid, "text": text.strip(), "blocking": blocking}, guard=guard)
        return self._note(self.notes[nid])

    def note_action(self, actor: Actor, note_id: str, kind: Literal["reply", "resolve", "reopen"],
                    text: str, expected_seq: Optional[int]) -> Note:
        n = self.notes.get(note_id)
        if n is None:
            raise RuleViolation("UNKNOWN", "No such note.")

        def guard() -> None:
            if expected_seq is not None and n["last_seq"] != expected_seq:
                raise Conflict("STALE", "Someone else updated this note since you loaded it. Reload to see their change.")
            if kind == "resolve":
                self._check_resolve(actor, n)
            else:
                self._check_note(actor, blocking=False)
                if kind == "reopen" and n["status"] != "resolved":
                    raise Conflict("NOT_RESOLVED", "Only a resolved note can be reopened.")
                if kind == "reply" and not text.strip():
                    raise RuleViolation("EMPTY", "Write the reply.")

        type_ = {"reply": "note.replied", "resolve": "note.resolved", "reopen": "note.reopened"}[kind]
        self.store.append(actor=actor.id, actor_role=actor.role, type=type_, node=n["node"], version=n["version"],
                          payload={"note_id": note_id, "text": text.strip()}, guard=guard)
        return self._note(n)

    def signoff(self, actor: Actor, node: str, version: Optional[str], level: str,
                expected_fingerprint: Optional[str]) -> SignOff:
        v = self._version(version)

        def guard() -> None:
            # A stale screen is reported first: the signer must see the change before anything else.
            if expected_fingerprint and expected_fingerprint != self.fingerprint(node, v):
                raise Conflict("CONTENT_CHANGED", "The evidence under this number changed since you loaded it. "
                                                  "Review the change, then sign.")
            self._check_signoff(actor, node, v, level)

        ev = self.store.append(
            actor=actor.id, actor_role=actor.role, type="signoff.recorded", node=node, version=v,
            payload={"level": level, "fingerprint": self.fingerprint(node, v), "evidence": self.snapshot(node, v),
                     **({"adjusted": self.return_adjusted(v)} if node == "return" else {})},
            guard=guard)
        return self._signoff(self.signoffs[ev.id])

    def withdraw_signoff(self, actor: Actor, sid: str) -> SignOff:
        s = self.signoffs.get(sid)

        def guard() -> None:
            self._staff(actor)
            if s is None:
                raise RuleViolation("UNKNOWN", "No such sign-off.")
            if s["actor"] != actor.id:
                raise RuleViolation("NOT_YOURS", "Only the signer can withdraw a sign-off.")
            if s["status"] == "withdrawn":
                raise Conflict("ALREADY_WITHDRAWN", "Already withdrawn.")

        self.store.append(actor=actor.id, actor_role=actor.role, type="signoff.withdrawn",
                          node=s["node"] if s else None, reverts=sid, guard=guard)
        return self._signoff(self.signoffs[sid])

    def correct_value(self, actor: Actor, ev_id: str, to: Any, reason: str) -> Correction:
        if not reason.strip():
            raise RuleViolation("REASON", "A correction needs a reason (what the document actually shows).")
        before = self.effective(ev_id) if ev_id in self.idx.values else None

        def guard() -> None:
            self._check_correct(actor, ev_id)
            if self.effective(ev_id) == to:
                raise Conflict("NO_CHANGE", "That is already the value.")

        ev = self.store.append(actor=actor.id, actor_role=actor.role, type="value.corrected", node=ev_id,
                               payload={"from": before, "to": to, "reason": reason.strip()}, guard=guard)
        self._reopen_signoffs(ev_id, ev)
        return self._correction(self.corrections[ev_id][-1], ev_id)

    def revert_correction(self, actor: Actor, ev_id: str, reason: str) -> Correction:
        c = self.active_correction(ev_id)

        def guard() -> None:
            self._check_correct(actor, ev_id)
            if c is None:
                raise Conflict("NO_CORRECTION", "There is no active correction on this value.")

        ev = self.store.append(actor=actor.id, actor_role=actor.role, type="value.correction_reverted", node=ev_id,
                               reverts=c["id"] if c else None,
                               payload={"reason": reason.strip(), "restored": self.idx.values[ev_id].value}, guard=guard)
        self._reopen_signoffs(ev_id, ev)
        return self._correction(c, ev_id)  # type: ignore[arg-type]

    def _reopen_signoffs(self, ev_id: str, cause: Event) -> None:
        """Signed content changed: reopen every active sign-off whose evidence included this value."""
        for s in list(self.signoffs.values()):
            if s["status"] != "active" or ev_id not in s.get("evidence", {}):
                continue
            changed = [c.model_dump() for c in self._diff(s["evidence"])]
            if not changed:
                continue
            who = self.name(cause.actor)
            self.store.append(
                actor=SYSTEM.id, actor_role=SYSTEM.role, type="signoff.reopened", node=s["node"],
                version=s["version"], reverts=s["id"],
                payload={"reason": f"Evidence changed after sign-off: {ev_id} corrected by {who}.",
                         "changed": changed, "caused_by": cause.id})

    def reopen_return_signoffs(self, cause: Event) -> None:
        """The return's adjustments changed (one took effect or was reversed): reopen every
        active return-level sign-off whose signed adjustments no longer match."""
        for s in list(self.signoffs.values()):
            if s["status"] != "active" or s["node"] != "return":
                continue
            was, now = s.get("adjusted", {}), self.return_adjusted(s["version"])
            if was == now:
                continue
            changed = [Change(ev=k, was=was.get(k), now=now.get(k)).model_dump()
                       for k in sorted(set(was) | set(now)) if was.get(k) != now.get(k)]
            adj = cause.payload.get("adj_id", "an adjustment")
            self.store.append(
                actor=SYSTEM.id, actor_role=SYSTEM.role, type="signoff.reopened", node="return",
                version=s["version"], reverts=s["id"],
                payload={"reason": f"The return changed after sign-off: {adj} {cause.type.split('.')[1]} by {self.name(cause.actor)}.",
                         "changed": changed, "caused_by": cause.id})

    # ---------------------------------------------------------------- findings + variance
    def disposition_finding(self, actor: Actor, finding_id: str, severity: str,
                            disposition: str, note: str, area_lines: list[str]) -> dict[str, Any]:
        """Record what was decided about a check finding. Errors can only be waved off
        ("not an issue") by review, and never by someone who prepared the affected lines."""
        if disposition not in ("resolved", "accepted", "not_an_issue", "reopened"):
            raise RuleViolation("DISPOSITION", "Use resolved, accepted, not_an_issue or reopened.")
        if disposition != "reopened" and not note.strip():
            raise RuleViolation("NOTE", "Say why — the disposition note becomes the workpaper evidence.")

        def guard() -> None:
            self._staff(actor)
            if actor.role not in PREPARE_ROLES:
                raise RuleViolation("ROLE", f"A {actor.role.replace('_', ' ')} does not disposition findings.")
            if disposition == "not_an_issue" and severity == "error":
                if actor.role not in REVIEW_ROLES:
                    raise RuleViolation("REVIEW_REQUIRED", "Only a reviewer or partner can mark an error finding 'not an issue'.")
                if any(actor.id in self.preparers(k, None) for k in area_lines):
                    raise RuleViolation("NO_SELF_REVIEW", "You prepared the lines this finding affects.")

        self.store.append(actor=actor.id, actor_role=actor.role, type="finding.dispositioned", node=finding_id,
                          payload={"finding_id": finding_id, "disposition": disposition, "note": note.strip(),
                                   "severity": severity}, guard=guard)
        return self.dispositions.get(finding_id, {"disposition": "open"})

    def explain_variance(self, actor: Actor, line: str, version: Optional[str], text: str) -> dict[str, Any]:
        if not text.strip():
            raise RuleViolation("EMPTY", "Explain the change from last year.")

        def guard() -> None:
            self._check_note(actor, blocking=False)

        self.store.append(actor=actor.id, actor_role=actor.role, type="variance.explained", node=line,
                          version=self._version(version), payload={"text": text.strip()}, guard=guard)
        return self.variance_notes[line]

    # ---------------------------------------------------------------- view log
    def log_view(self, actor: Actor, node: str, *, masked: bool, endpoint: str, fields: int) -> None:
        """Record access to sensitive data. Unmasked views (firm rule) and masked
        access by uncleared staff are both logged; repeats within 30 s coalesce."""
        key = (actor.id, node, masked)
        now = datetime.now(timezone.utc)
        last = self._last_view.get(key)
        if last and now - last < VIEW_COALESCE:
            return
        self._last_view[key] = now
        self.store.append(actor=actor.id, actor_role=actor.role, type="view.logged", node=node,
                          payload={"masked": masked, "endpoint": endpoint, "sensitive_fields": fields,
                                   "clearance": actor.sensitive_data_clearance})


def _parse(at: str) -> datetime:
    return datetime.fromisoformat(at.replace("Z", "+00:00"))
