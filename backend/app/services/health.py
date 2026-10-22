"""Return health: variance flags (firm rule), the eight area summaries and the
cached check run. Everything is derived from the packet + the event log; the
cache key is (version, last event seq), so any review action re-runs checks."""

from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel

from app.services.checks import AREAS, CheckRun, area_of, run_checks
from app.services.loader import PacketIndex
from app.services.trace import TraceIndex


class VarianceFlag(BaseModel):
    line: str
    label: str
    area: str
    current: float
    prior: float
    delta: float
    pct: Optional[float]           # None when prior is 0
    explanation: Optional[dict[str, Any]] = None


class VarianceReport(BaseModel):
    version: str
    rule: dict[str, Any]
    compared: int
    flags: list[VarianceFlag]


class Owner(BaseModel):
    actor: str
    name: str
    source: str


class AreaSummary(BaseModel):
    id: str
    name: str
    headline_line: str
    headline_label: str
    current: Optional[float]
    prior: Optional[float]
    delta: Optional[float]
    delta_pct: Optional[float]
    headline_flagged: bool
    lines: int
    evidence_lines: int
    verified_lines: int
    signed_lines: int
    reopened_signoffs: int
    open_notes: int
    blocking_notes: int
    findings_error: int
    findings_warning: int
    findings_total: int
    variance_flags: int
    variance_unexplained: int
    owner: Owner
    budget_hours: Optional[float]
    status: Literal["attention", "in_progress", "clear"]
    considered: bool
    line_keys: list[str]


class Headline(BaseModel):
    key: str
    label: str
    current: Optional[float]
    prior: Optional[float]


class Health(BaseModel):
    version: str
    areas: list[AreaSummary]
    totals: list[Headline]
    counts: dict[str, int]


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


_STOP = {"the", "of", "and", "using", "law", "total", "from", "line", "lines", "amount"}


def _words(label: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", label.lower()) if w not in _STOP}


def prior_key(key: str, prior: dict[str, Any], label: str = "", prior_labels: Optional[dict[str, str]] = None) -> Optional[str]:
    """The 2024 line to compare with. 2024 was a resident CA540; this year is a 540NR.
    The forms share some line numbers but not all (540NR line 32 is California AGI,
    540 line 32 is exemption credits), so a cross-form pair is accepted only when
    the labels agree: one label's significant words contain the other's."""
    if key in prior:
        return key
    if key.startswith("F540NR."):
        alt = "CA540." + key.split(".", 1)[1]
        if alt not in prior or prior_labels is None:
            return None
        a, b = _words(label), _words(prior_labels.get(alt, ""))
        return alt if a and b and (a <= b or b <= a) else None
    return None


def _prior_value(key: str, label: str, prior: dict[str, Any], labels: dict[str, str]) -> Optional[float]:
    pk = prior_key(key, prior, label, labels)
    return float(prior[pk]) if pk and _num(prior.get(pk)) else None


class HealthService:
    def __init__(self, idx: PacketIndex, trace: TraceIndex, review: Any):
        self.idx, self.trace, self.review = idx, trace, review
        self._cache: dict[tuple[str, int], CheckRun] = {}

    def checks(self, version: Optional[str] = None) -> CheckRun:
        v = version or self.idx.current_version
        key = (v, self.review.store.last_seq())
        if key not in self._cache:
            self._cache = {key: run_checks(self.idx, self.trace, self.review, v)}
        return self._cache[key]

    # ------------------------------------------------------------- variance
    def variance(self, version: Optional[str] = None) -> VarianceReport:
        v = version or self.idx.current_version
        rule = self.idx.packet.firm.starter_standards.variance_review
        pct, amount = float(rule.flag_if_change_over_percent), float(rule.and_over_amount)
        prior = self.idx.packet.prior_years.return_2024.lines
        labels = self.idx.packet.prior_years.return_2024.line_labels
        flags: list[VarianceFlag] = []
        compared = 0
        for key, ln in self.idx.lines[v].items():
            pk = prior_key(key, prior, ln.label, labels)
            p = prior.get(pk) if pk else None
            if not (_num(ln.value) and _num(p)):
                continue
            compared += 1
            delta = float(ln.value) - float(p)
            ratio = None if p == 0 else delta / abs(float(p)) * 100
            # Firm rule, applied exactly: more than pct% AND more than amount (a change from zero is unbounded %).
            if abs(delta) > amount and (ratio is None or abs(ratio) > pct):
                label = ln.label + (f" (vs 2024 resident {pk})" if pk and pk != key else "")
                flags.append(VarianceFlag(line=key, label=label, area=area_of(key), current=float(ln.value), prior=float(p),
                                          delta=delta, pct=None if ratio is None else round(ratio, 1),
                                          explanation=self.review.variance_notes.get(key)))
        flags.sort(key=lambda f: -abs(f.delta))
        return VarianceReport(version=v, rule={"compare_to": rule.compare_to, "flag_if_change_over_percent": pct,
                                               "and_over_amount": amount}, compared=compared, flags=flags)

    # ------------------------------------------------------------- areas
    def owner(self, area_id: str) -> Owner:
        a = self.review.assignments.get(f"area:{area_id}")
        if a:
            return Owner(actor=a["actor"], name=self.review.name(a["actor"]), source="area assignment")
        pre = self.review.assignments.get("preparer")
        return Owner(actor=pre["actor"] if pre else "", name=self.review.name(pre["actor"]) if pre else "Unassigned",
                     source="engagement preparer (firm.assignment_at_start)")

    def health(self, version: Optional[str] = None) -> Health:
        v = version or self.idx.current_version
        lines = self.idx.lines[v]
        prior = self.idx.packet.prior_years.return_2024.lines
        labels = self.idx.packet.prior_years.return_2024.line_labels
        run = self.checks(v)
        var = self.variance(v)
        summary = self.review.summary(v)
        budget = self.idx.packet.firm.budget_hours
        by_area: dict[str, list[str]] = {a[0]: [] for a in AREAS}
        for key in lines:
            by_area.setdefault(area_of(key), []).append(key)
        areas = []
        for aid, name, budget_key, headline in AREAS:
            keys = by_area.get(aid, [])
            hl = lines.get(headline)
            cur = float(hl.value) if hl and _num(hl.value) else None
            pk = prior_key(headline, prior, hl.label if hl else "", labels)
            pri = float(prior[pk]) if pk and _num(prior.get(pk)) else None
            delta = cur - pri if cur is not None and pri is not None else None
            pct = round(delta / abs(pri) * 100, 1) if delta is not None and pri else None
            s = [summary[k] for k in keys if k in summary]
            fs = [f for f in run.findings if f.area == aid and f.status == "open"]
            vf = [f for f in var.flags if f.area == aid]
            errs = sum(f.severity == "error" for f in fs)
            warns = sum(f.severity == "warning" for f in fs)
            blocking = sum(x.blocking for x in s)
            reopened = sum(x.reopened for x in s)
            unexplained = sum(1 for f in vf if not f.explanation)
            verified = sum(1 for x in s if x.verified)
            signed = sum(1 for x in s if x.signed)
            considered = bool(verified or signed)
            status = ("attention" if errs or blocking or reopened else
                      "clear" if considered and not warns and not unexplained else "in_progress")
            areas.append(AreaSummary(
                id=aid, name=name, headline_line=headline, headline_label=hl.label if hl else headline,
                current=cur, prior=pri, delta=delta, delta_pct=pct,
                headline_flagged=any(f.line == headline for f in vf),
                lines=len(keys), evidence_lines=sum(1 for k in keys if lines[k].sources),
                verified_lines=verified, signed_lines=signed, reopened_signoffs=reopened,
                open_notes=sum(x.open_notes for x in s), blocking_notes=blocking,
                findings_error=errs, findings_warning=warns, findings_total=len(fs),
                variance_flags=len(vf), variance_unexplained=unexplained, owner=self.owner(aid),
                budget_hours=budget.get(budget_key) if budget_key else None,
                status=status, considered=considered, line_keys=keys,
            ))
        totals = [Headline(key=k, label=lines[k].label, current=float(lines[k].value) if _num(lines[k].value) else None,
                           prior=_prior_value(k, lines[k].label, prior, labels))
                  for k in ("F1040.9", "F1040.11", "F1040.15", "F1040.24", "F1040.33", "F1040.37", "F540NR.64", "F540NR.97")
                  if k in lines]
        counts = {**run.counts, "variance_flags": len(var.flags),
                  "variance_unexplained": sum(1 for f in var.flags if not f.explanation),
                  "areas_attention": sum(a.status == "attention" for a in areas),
                  "areas_considered": sum(a.considered for a in areas)}
        return Health(version=v, areas=areas, totals=totals, counts=counts)
