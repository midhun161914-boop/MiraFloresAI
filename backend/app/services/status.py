"""Return status at a glance: where the return is in its lifecycle, what blocks
the next step, who owns what, and what is outstanding. Read-only — every number here
is derived from services that already enforce the rules."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict


class StatusOwner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str
    name: str
    scope: str


class Outstanding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    label: str
    count: int
    tone: Literal["error", "warning", "neutral"]
    link: str


class Milestone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    at: Optional[str]
    who: Optional[str]
    done: bool


class NextStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    who: str
    link: str


class BudgetSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_budget: float
    total_logged: float
    pct: float
    status: Literal["under", "near", "over", "not_started"]
    over: list[str]


class Deadline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    what: str
    date: Optional[str]


class Status(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: str
    stage_label: str
    headline: str
    next_step: Optional[NextStep]
    blockers: int
    blocker_titles: list[str]
    outstanding: list[Outstanding]
    owners: list[StatusOwner]
    milestones: list[Milestone]
    budget: BudgetSummary
    deadlines: list[Deadline]
    filed_snapshot: Optional[str]


STAGE_LABEL = {
    "preparing": "Preparing", "presented": "Awaiting client approval", "authorized": "Authorized — ready to transmit",
    "transmitted": "Transmitted — fix the reject", "filed": "Filed", "amending": "Filed · amendment in progress",
    "amend_ready": "Filed · amendment approved",
    "notice": "Filed · agency notice open",
}


class StatusService:
    def __init__(self, review: Any, health: Any, lifecycle: Any, time: Any):
        self.review, self.health, self.lc, self.time = review, health, lifecycle, time

    def status(self) -> Status:
        lc, r = self.lc, self.review
        f = lc.filing()
        stage = f["stage"]
        draft = [a for a in lc.amendments.values() if a["status"] != "filed"]
        open_notices = [n for n in lc.notices() if n.get("items_under_examination") and not (n.get("response") or {}).get("sent")]
        approved = [a for a in draft if a["status"] == "approved"]
        if stage == "filed" and draft:
            stage = "amend_ready" if len(approved) == len(draft) else "amending"
        elif stage == "filed" and open_notices:
            stage = "notice"

        gate = lc.gate() if not lc.filed else None
        blockers = gate.blockers if gate else []
        h = self.health.health()
        c = h.counts
        outstanding: list[Outstanding] = []

        def add(kind: str, label: str, n: int, tone: Literal["error", "warning", "neutral"], link: str) -> None:
            if n:
                outstanding.append(Outstanding(kind=kind, label=label, count=n, tone=tone, link=link))

        add("errors", "Open error findings", c.get("open_errors", 0), "error", "/findings?sev=error")
        add("blocking", "Open blocking notes", sum(1 for n in r.notes.values() if n["status"] == "open" and n["blocking"]), "error", "/review")
        add("pending_adj", "Adjustments awaiting partner", sum(1 for a in r.adjustments.values() if a["status"] == "pending_partner"), "error", "/adjustments")
        add("dd", "Due diligence required", sum(1 for d in f["diligence"] if d["status"] == "required"), "error", "/filing#diligence")
        add("warnings", "Open warnings", c.get("open_warnings", 0), "warning", "/findings?sev=warning")
        add("variance", "Unexplained variances", c.get("variance_unexplained", 0), "warning", "/variance")
        add("notes", "Open review notes", sum(1 for n in r.notes.values() if n["status"] == "open" and not n["blocking"]), "neutral", "/review")
        if f["presented"] and not lc.filed:
            add("signers", "Taxpayer signatures missing", sum(1 for s in f["signers"] if not s["approval"]), "warning", "/filing")
        add("amend", "Amendment in progress", len(draft), "warning", "/amend")
        add("notices", "Agency notice to answer", len(open_notices), "error", "/notices")

        owners = [StatusOwner(role=k.replace("area:", "area · ").replace("_", " "), name=r.name(v["actor"]),
                        scope="engagement" if not k.startswith("area:") else "area") for k, v in r.assignments.items()]
        owners.append(StatusOwner(role="ERO / signing preparer", name=f["ero_signer"], scope="filing"))

        def ev(seq_dict: Optional[dict[str, Any]]) -> tuple[Optional[str], Optional[str]]:
            return (seq_dict["at"], seq_dict["actor_name"]) if seq_dict else (None, None)

        accepted = next((s for s in f["submissions"] if s["status"] == "accepted" and s["jurisdiction"] == "federal"), None)
        rejected = next((s for s in f["submissions"] if s["status"] == "rejected"), None)
        signed_all = all(s["approval"] for s in f["signers"]) if f["presented"] else False
        last_sig = max((s["approval"]["at"] for s in f["signers"] if s["approval"]), default=None)
        ms = [
            Milestone(label="Extension filed", at=ev(f["extension"])[0], who=ev(f["extension"])[1], done=bool(f["extension"])),
            Milestone(label="Pre-file gate clear", at=None, who=None, done=bool(lc.filed) or (gate is not None and gate.clear)),
            Milestone(label="Presented to client", at=ev(f["presented"])[0], who=ev(f["presented"])[1], done=bool(f["presented"])),
            Milestone(label="Both taxpayers signed 8879", at=last_sig if signed_all else None, who=None, done=signed_all),
            Milestone(label="ERO signed", at=ev(f["ero"])[0], who=ev(f["ero"])[1], done=bool(f["ero"])),
            Milestone(label="E-file rejected (R0000-504-02)" if rejected else "E-file transmitted",
                      at=rejected["response"]["at"] if rejected and rejected["response"] else None, who=None,
                      done=bool(f["submissions"])),
            Milestone(label="Accepted & frozen", at=accepted["response"]["at"] if accepted and accepted["response"] else None,
                      who=None, done=bool(lc.filed)),
        ]
        for a in lc.amendments.values():
            ms.append(Milestone(label=f"Amendment {a['id']} ({a['status']})", at=a["at"], who=a["actor_name"], done=a["status"] != "draft"))
        for nid, resp in lc.responses.items():
            ms.append(Milestone(label=f"Notice {nid} response {'sent' if resp['sent'] else 'assembled'}", at=resp["at"],
                                who=resp["actor_name"], done=bool(resp["sent"])))
        if lc.rolled:
            ms.append(Milestone(label="2026 file opened", at=lc.rolled["at"], who=lc.rolled["actor_name"], done=True))

        nxt = self._next(stage, f, gate, open_notices, draft)
        b = self.time.budget()
        headline = {
            "preparing": f"{len(blockers)} item(s) stand between the return and client approval." if blockers else "Gate clear — ready to present to the client.",
            "presented": "Waiting for both taxpayers to approve and sign Form 8879.",
            "authorized": "Signed and authorized — ready to transmit.",
            "transmitted": "The federal return was rejected; fix and resubmit.",
            "filed": "Filed and accepted; the filed record is frozen.",
            "amending": "Filed; an amendment is being prepared on top of the frozen return.",
            "amend_ready": "Filed; the amendment is partner-approved and ready to file as Form 1040-X (amendment e-file is not built).",
            "notice": "Filed; an agency notice needs a response.",
        }[stage]
        deadlines = [{"what": d.what, "date": d.date} for d in r.idx.packet.firm.deadlines]
        for n in open_notices:
            deadlines.append({"what": f"Respond to {n['type'].split(' (')[0]} ({n['id']})", "date": n.get("response_due")})
        return Status(stage=stage, stage_label=STAGE_LABEL[stage], headline=headline, next_step=nxt,
                      blockers=len(blockers), blocker_titles=[x.title for x in blockers][:8], outstanding=outstanding,
                      owners=owners, milestones=ms,
                      budget=BudgetSummary(total_budget=b.total_budget, total_logged=b.total_logged, pct=b.pct, status=b.status,
                                           over=[x.label for x in b.buckets if x.status == "over"]),
                      deadlines=[Deadline(**d) for d in sorted(deadlines, key=lambda d: d["date"] or "9999")], filed_snapshot=lc.filed["snapshot_hash"] if lc.filed else None)

    def _next(self, stage: str, f: dict[str, Any], gate: Any, notices: list[dict[str, Any]],
              draft: list[dict[str, Any]]) -> Optional[NextStep]:
        if stage == "preparing":
            if gate and gate.blockers:
                b = gate.blockers[0]
                return NextStep(label=f"Clear: {b.title}", who="preparer / reviewer", link=b.link or "/filing")
            return NextStep(label="Present the return to the client", who="reviewer or partner", link="/filing")
        if stage == "presented":
            missing = [s["name"] for s in f["signers"] if not s["approval"]]
            if not f["presented_current"]:
                return NextStep(label="Present again — the return changed", who="reviewer or partner", link="/filing")
            if missing:
                return NextStep(label=f"Signature from {', '.join(missing)}", who="client", link="/filing")
            return NextStep(label="ERO signature", who=f["ero_signer"], link="/filing")
        if stage == "authorized":
            return NextStep(label="Transmit federal + California", who="reviewer or partner", link="/filing")
        if stage == "transmitted":
            return NextStep(label="Correct the rejected item and resubmit", who="preparer (cleared)", link="/filing")
        if stage == "amend_ready":
            return NextStep(label=f"File amendment {draft[0]['id']} (1040-X) outside this build", who="partner", link="/amend")
        if stage == "amending":
            return NextStep(label=f"Finish amendment {draft[0]['id']}", who="preparer → partner", link="/amend")
        if stage == "notice":
            n = notices[0]
            return NextStep(label=f"Answer {n['type'].split(' (')[0]} by {n.get('response_due')}", who="preparer → partner",
                            link="/notices")
        return NextStep(label="Roll forward to 2026", who="preparer", link="/carryforward") if not self.lc.rolled else None
