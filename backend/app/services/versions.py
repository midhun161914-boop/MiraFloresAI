"""Version compare and what-ifs.

A *state* is something the return can be compared at:
* an engine version (``v1``, ``v2``, ``v3``) — the engine's lines as computed;
* ``v3@now`` — the engine version plus every active workpaper adjustment;
* ``state:<event id>`` — a state someone saved: the engine version plus the
  adjustments that were active *as of that event seq* (replayed from the log).

The diff explains every changed line: for engine-to-engine changes, which
sources changed (e.g. D30's values replaced by D31's) under the version's
trigger; for adjustments, who changed it, why and with which evidence.

What-ifs: the packet's five scripted alternatives are *engine results*. Ad-hoc
scenarios are *estimates* — a linear approximation using ``tax_effect_rates`` —
and are labelled as such everywhere they appear.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel

from app.services.checks import Ctx, area_of, tax_category
from app.services.review import ReviewService

Kind = Literal["engine", "workpaper", "saved"]


class StateRef(BaseModel):
    id: str
    kind: Kind
    label: str
    version: str
    as_of_seq: Optional[int] = None
    at: Optional[str] = None
    detail: Optional[str] = None


class LineDiff(BaseModel):
    key: str
    label: str
    form: str
    area: str
    change: Literal["added", "removed", "changed"]
    old: Any = None
    new: Any = None
    delta: Optional[float] = None
    why: list[str]
    refs: list[str] = []


class Group(BaseModel):
    form: str
    count: int
    net: Optional[float]
    lines: list[LineDiff]


class Compare(BaseModel):
    a: StateRef
    b: StateRef
    summary: dict[str, Any]
    headline: list[dict[str, Any]]
    groups: list[Group]


class EstimateItem(BaseModel):
    line: Optional[str] = None
    category: Optional[str] = None
    change: float
    label: Optional[str] = None


class Estimate(BaseModel):
    kind: Literal["ESTIMATE"] = "ESTIMATE"
    disclaimer: str
    version: str
    items: list[dict[str, Any]]
    federal_tax: float
    california_tax: float
    federal_balance_due: float
    california_balance_due: float
    base: dict[str, Any]
    estimated: dict[str, Any]


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


HEADLINE = ["F1040.11", "F1040.15", "F1040.24", "F1040.33", "F1040.37", "F540NR.64", "F540NR.97"]


class VersionService:
    def __init__(self, review: ReviewService):
        self.r = review
        self.idx = review.idx

    # ------------------------------------------------------------------ states
    def states(self) -> list[StateRef]:
        out = [StateRef(id=v.version, kind="engine", label=f"{v.version} · engine", version=v.version, at=v.computed_at,
                        detail=v.trigger) for v in self.idx.packet.return_versions]
        cur = self.idx.current_version
        n = len(self.r.active_adjustments(cur))
        out.append(StateRef(id=f"{cur}@now", kind="workpaper", label=f"{cur} + workpaper adjustments (now)", version=cur,
                            as_of_seq=self.r.store.last_seq(), detail=f"{n} active adjustment(s)"))
        for s in self.r.saved_states:
            out.append(StateRef(id=f"state:{s['id']}", kind="saved", label=f"“{s['name']}”", version=s["version"] or cur,
                                as_of_seq=s["as_of_seq"], at=s["at"], detail=f"saved by {s['actor_name']}"))
        return out

    def _resolve(self, sid: str) -> StateRef:
        st = next((s for s in self.states() if s.id == sid), None)
        if st is None:
            raise KeyError(sid)
        return st

    def _values(self, st: StateRef) -> dict[str, dict[str, Any]]:
        lines = self.idx.lines[st.version]
        vals = {k: {"value": ln.value, "label": ln.label, "form": ln.form, "sources": ln.sources, "adj": []}
                for k, ln in lines.items()}
        if st.kind != "engine":
            for k, a in self.r.adjusted_values(st.version, st.as_of_seq).items():
                base = vals.get(k, {"label": a["label"], "form": k.split(".")[0], "sources": []})
                vals[k] = {**base, "value": a["value"], "adj": a["adjustments"]}
        return vals

    # ------------------------------------------------------------------ compare
    def compare(self, a_id: str, b_id: str) -> Compare:
        a, b = self._resolve(a_id), self._resolve(b_id)
        va, vb = self._values(a), self._values(b)
        engine_changes = {}
        if a.kind == "engine" and b.kind == "engine":
            order = [v.version for v in self.idx.packet.return_versions]
            if order.index(b.version) == order.index(a.version) + 1:  # consecutive: the engine's own change log
                engine_changes = {c.key: c for c in self.idx.versions[b.version].changes_from_previous}
        trigger = self.idx.versions[b.version].trigger if a.version != b.version else None
        diffs: list[LineDiff] = []
        for key in sorted(set(va) | set(vb), key=lambda k: (k.split(".")[0], k)):
            x, y = va.get(key), vb.get(key)
            if x and y and x["value"] == y["value"]:
                continue
            change = "added" if x is None else "removed" if y is None else "changed"
            ref = y or x
            why: list[str] = []
            refs: list[str] = []
            adj_ids = [i for i in (y or {}).get("adj", []) if i not in (x or {}).get("adj", [])] + \
                      [i for i in (x or {}).get("adj", []) if i not in (y or {}).get("adj", [])]
            for aid in dict.fromkeys(adj_ids):
                adj = self.r.adjustments[aid]
                state = "reversed in the later state" if aid in (x or {}).get("adj", []) and aid not in (y or {}).get("adj", []) else ""
                why.append(f"Adjustment {aid} by {adj['actor_name']}: {adj['title']} — {adj['reason']}" + (f" ({state})" if state else ""))
                refs += adj.get("refs", [])[:4]
            if a.version != b.version and not adj_ids:
                sa = set((x or {}).get("sources", []))
                sb = set((y or {}).get("sources", []))
                docs = lambda srcs: sorted({self.idx.values[s].document_id for s in srcs if s in self.idx.values})  # noqa: E731
                gone, new = docs(sa - sb), docs(sb - sa)
                if gone or new:
                    why.append(f"Evidence changed: {', '.join(gone) or '—'} → {', '.join(new) or '—'}")
                    refs += new + gone
                elif sa == sb and x and y and x["sources"]:
                    why.append("Same evidence; recomputed from changed inputs")
                elif not (x or {}).get("sources") and not (y or {}).get("sources"):
                    why.append("Computed line: flows from changed lines beneath it")
                if key in engine_changes:
                    why.append(f"Listed in {b.version}.changes_from_previous")
                if trigger:
                    why.append(f"{b.version} trigger: {trigger}")
            delta = float(y["value"]) - float(x["value"]) if x and y and _num(x["value"]) and _num(y["value"]) else \
                (float(y["value"]) if y and not x and _num(y["value"]) else (-float(x["value"]) if x and not y and _num(x["value"]) else None))
            diffs.append(LineDiff(key=key, label=ref["label"], form=ref["form"], area=area_of(key), change=change,
                                  old=x["value"] if x else None, new=y["value"] if y else None, delta=delta,
                                  why=why or ["Changed"], refs=list(dict.fromkeys(refs))[:6]))
        groups: dict[str, list[LineDiff]] = {}
        for d in diffs:
            groups.setdefault(d.form, []).append(d)
        out_groups = [Group(form=f, count=len(ls), lines=ls,
                            net=round(sum(d.delta for d in ls if d.delta is not None), 2) if any(d.delta is not None for d in ls) else None)
                      for f, ls in sorted(groups.items(), key=lambda kv: -len(kv[1]))]
        headline = []
        for k in HEADLINE:
            x, y = va.get(k), vb.get(k)
            if x or y:
                headline.append({"key": k, "label": (y or x)["label"], "old": x["value"] if x else None, "new": y["value"] if y else None})
        summary = {"lines_changed": sum(d.change == "changed" for d in diffs), "lines_added": sum(d.change == "added" for d in diffs),
                   "lines_removed": sum(d.change == "removed" for d in diffs), "forms": len(out_groups),
                   "engine_change_log_entries": len(engine_changes), "adjustment_driven": sum(1 for d in diffs if d.why and d.why[0].startswith("Adjustment"))}
        return Compare(a=a, b=b, summary=summary, headline=headline, groups=out_groups)

    # ------------------------------------------------------------------ what-ifs
    def scripted(self) -> dict[str, Any]:
        w = self.idx.packet.what_if
        alts = []
        for alt in w.alternatives:
            d = alt.model_dump()
            d["kind"] = "ENGINE"
            d["changed_lines"] = [{**c.model_dump(), "label": self.idx.lines[alt.base_version].get(c.key).label
                                   if self.idx.lines[alt.base_version].get(c.key) else c.key} for c in alt.changed_lines]
            alts.append(d)
        return {"alternatives": alts, "extension": w.extension}

    def estimate(self, items: list[EstimateItem], version: Optional[str] = None) -> Estimate:
        v = version or self.idx.current_version
        ctx = Ctx(self.idx, self.r.trace, self.r, v)
        rates = self.idx.versions[v].tax_effect_rates
        rows = []
        fed = ca = fdue = cdue = 0.0
        for it in items:
            cat = it.category or (tax_category(it.line) if it.line else None)
            if cat not in rates and cat not in ("payment", "ca_payment"):
                raise ValueError(f"Unknown category {cat!r}; use one of {', '.join(rates)} (or a line key).")
            e = ctx.effect(cat, it.change, f"{it.label or it.line or cat} {it.change:+,.0f}")
            fed += e.federal_tax
            ca += e.california_tax
            fdue += e.federal_balance_due
            cdue += e.california_balance_due
            rows.append({"line": it.line, "category": cat, "change": it.change, "label": it.label,
                         "federal_tax": e.federal_tax, "california_tax": e.california_tax, "basis": e.basis})
        s = self.idx.versions[v].summary
        base = {"federal_total_tax": s.federal.total_tax, "federal_balance_due": s.federal.balance_due,
                "california_total_tax": s.california.total_tax, "california_balance_due": s.california.balance_due}
        est = {"federal_total_tax": base["federal_total_tax"] + fed, "federal_balance_due": base["federal_balance_due"] + fdue,
               "california_total_tax": base["california_total_tax"] + ca, "california_balance_due": base["california_balance_due"] + cdue}
        return Estimate(
            disclaimer=("ESTIMATE — not an engine recompute. Each change is multiplied by this version's "
                        "tax_effect_rates (a linear, per-dollar approximation measured at the current numbers). "
                        "Large changes can cross thresholds and phase-outs the rates do not capture."),
            version=v, items=rows, federal_tax=round(fed), california_tax=round(ca),
            federal_balance_due=round(fdue), california_balance_due=round(cdue), base=base, estimated=est)
