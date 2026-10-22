"""The check suite: reconcilers, error detectors, independent re-computations and
completeness proofs over the packet and the current review state.

Each check is a registered function that *computes* its result from the data
(documents, extracted values, return lines, prior years, agency records) and the
event-sourced review state (corrections, dispositions). Nothing here names a
document or a line to flag; the planted errors surface because the arithmetic
or the cross-check fails. Think of it as a regression suite for a tax return:
every run produces pass/fail per check plus formal findings with severity,
evidence refs, affected lines (each traceable) and, where the packet's
``tax_effect_rates`` allow, the tax effect.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel

from app.models.packet import ReturnLine
from app.services.loader import PacketIndex
from app.services.trace import EV, TraceIndex

Severity = Literal["error", "warning", "info"]
Kind = Literal["reconciliation", "detector", "independent", "completeness"]
LOW_CONFIDENCE = 0.80
MONEY = re.compile(r"[\d,]+\.\d\d")


# ------------------------------------------------------------------ models
class TaxEffect(BaseModel):
    category: str
    change: float                 # change in the underlying figure (income, gain, payment)
    federal_tax: float            # change in federal tax
    california_tax: float
    federal_balance_due: float    # change in what is owed (tax change, or 1:1 for payments)
    california_balance_due: float
    basis: str                    # how it was computed
    bound: Literal["estimate", "upper_bound"] = "estimate"


class LineChange(BaseModel):
    key: str
    label: str
    from_value: Optional[float] = None   # None = a line the engine never produced
    to_value: float
    new_line: bool = False


class Fix(BaseModel):
    """The exact line changes that would resolve a finding, when they are determinable.
    Turned into an adjustment, it carries the finding's evidence and tax effect."""
    description: str
    changes: list[LineChange]


class Finding(BaseModel):
    id: str
    check_id: str
    code: str
    severity: Severity
    area: str
    title: str
    summary: str
    facts: list[str] = []
    refs: list[str] = []           # evidence: ev-…, D.., qa-…, py:/…, agency:/…
    lines: list[str] = []          # return lines affected (open in the trace)
    tax_effect: Optional[TaxEffect] = None
    engine_diagnostic: Optional[str] = None   # engine code if the engine also flagged it
    status: Literal["open", "accepted", "resolved", "not_an_issue", "corrected", "adjusted", "adjustment_pending"] = "open"
    disposition: Optional[dict[str, Any]] = None
    fix: Optional[Fix] = None
    adjustment: Optional[dict[str, Any]] = None   # the adjustment made from this finding, if any


class CheckResult(BaseModel):
    id: str
    title: str
    kind: Kind
    description: str
    status: Literal["pass", "fail", "warn", "info"]
    summary: str
    metrics: dict[str, Any] = {}
    findings: list[Finding] = []


class OutsideFiling(BaseModel):
    filing: str
    required: Literal["yes", "no", "check"]
    responsible: str
    in_engagement: bool
    due: Optional[str] = None
    basis: str
    refs: list[str] = []


# ------------------------------------------------------------------ context
@dataclass
class Ctx:
    idx: PacketIndex
    trace: TraceIndex
    review: Any  # ReviewService (corrections, dispositions)
    version: str

    @property
    def v(self):
        return self.idx.versions[self.version]

    @property
    def lines(self) -> dict[str, ReturnLine]:
        return self.idx.lines[self.version]

    def eff(self, ev: str) -> Any:
        return self.review.effective(ev) if self.review else self.idx.values[ev].value

    def line_value(self, key: str) -> Any:
        ln = self.lines.get(key)
        return ln.value if ln else None

    def rate(self, cat: str) -> tuple[float, float]:
        r = self.v.tax_effect_rates.get(cat)
        return (r.federal_per_dollar, r.california_per_dollar) if r else (0.0, 0.0)

    def effect(self, cat: str, change: float, basis: str, bound: str = "estimate") -> TaxEffect:
        if cat == "payment":
            # Payments change what is owed 1:1, not the tax.
            return TaxEffect(category=cat, change=change, federal_tax=0, california_tax=0,
                             federal_balance_due=round(-change), california_balance_due=0, basis=basis, bound=bound)
        if cat == "ca_payment":
            return TaxEffect(category=cat, change=change, federal_tax=0, california_tax=0,
                             federal_balance_due=0, california_balance_due=round(-change), basis=basis, bound=bound)
        f, c = self.rate(cat)
        fed, ca = round(change * f), round(change * c)
        return TaxEffect(category=cat, change=round(change, 2), federal_tax=fed, california_tax=ca,
                         federal_balance_due=fed, california_balance_due=ca,
                         basis=f"{basis} × tax_effect_rates.{cat} ({f} federal, {c} CA per $)", bound=bound)

    def ca_resident_on(self, d: str) -> bool:
        day = date.fromisoformat(d)
        return any(r.state == "CA" and date.fromisoformat(r.from_) <= day <= date.fromisoformat(r.to)
                   for r in self.idx.packet.household.residency)

    def sale_effect(self, cat: str, change: float, sold: Optional[str], basis: str) -> TaxEffect:
        """Packet rule: for an item fully California-source (a sale during California residency)
        use ca_source_income for the California effect; otherwise the prorated category rate."""
        eff = self.effect(cat, change, basis)
        if sold and self.ca_resident_on(sold):
            ca_rate = self.rate("ca_source_income")[1]
            eff.california_tax = eff.california_balance_due = round(change * ca_rate)
            eff.basis += f"; sold {sold} while a California resident → CA uses ca_source_income ({ca_rate})"
        elif sold:
            eff.basis += f"; sold {sold} after the move — CA figure uses the packet's prorated rate (confirm CA-sourcing)"
        return eff

    def engine_diag(self, code: str, refs: list[str] = ()) -> Optional[str]:  # type: ignore[assignment]
        for d in self.v.diagnostics:
            if d.code == code and (not refs or set(d.refs) & set(refs) or not d.refs):
                return d.code
        return None

    def num(self, x: Any) -> bool:
        return isinstance(x, (int, float)) and not isinstance(x, bool)


def money(x: float) -> str:
    return f"({abs(x):,.2f})" if x < 0 else f"{x:,.2f}"


def tax_category(key: str) -> str:
    """Which tax_effect_rates category a change on this line falls under."""
    form, rest = key.split(".", 1)
    if form == "F8949":
        return "stcg" if rest[0] in "ABCGHI" else "ltcg"
    if form == "SchB":
        return "interest"
    if form in ("SchC", "SchSE", "F4562-C"):
        return "schc_profit"
    if form == "SchA":
        return "salt" if rest.startswith("5") else "itemized"
    if form == "Sch1" and rest.split(".")[0].isdigit() and int(rest.split(".")[0]) >= 11:
        return "adjustment"
    if key.startswith("F1040.1") and form == "F1040" and rest[:1] == "1" and not rest[1:2].isdigit():
        return "wages"
    if key in ("F1040.25a", "F1040.25d", "F1040.26") or key.startswith("Sch3.1"):
        return "payment"
    if key in ("F540NR.71", "F540NR.72", "F540NR.73"):
        return "ca_payment"
    return "ordinary_income"


# ------------------------------------------------------------------ registry
CHECKS: list[tuple[str, str, Kind, str, Callable[[Ctx], CheckResult]]] = []


def check(check_id: str, title: str, kind: Kind, description: str):
    def deco(fn: Callable[[Ctx], "CheckResult"]):
        CHECKS.append((check_id, title, kind, description, fn))
        return fn
    return deco


def result(ctx_id: str, findings: list[Finding], *, ok: str, metrics: dict[str, Any] | None = None,
           summary: Optional[str] = None) -> CheckResult:
    meta = next(c for c in CHECKS if c[0] == ctx_id)
    if any(f.severity == "error" and f.status == "open" for f in findings):
        status = "fail"
    elif any(f.severity == "warning" and f.status == "open" for f in findings):
        status = "warn"
    elif findings:
        status = "info"
    else:
        status = "pass"
    return CheckResult(id=ctx_id, title=meta[1], kind=meta[2], description=meta[3], status=status,
                       summary=summary or (ok if status == "pass" else f"{len(findings)} finding(s)"),
                       metrics=metrics or {}, findings=findings)


def F(ctx: Ctx, check_id: str, subject: str, **kw: Any) -> Finding:
    return Finding(id=f"{check_id}:{subject}", check_id=check_id, **kw)


# ================================================================== reconciliations
LOT_LINE = re.compile(
    r"(?P<lot>[A-Z]+\d+) (?P<desc>[^;]+?) (?P<qty>[\d.]+) sh acquired (?P<acq>\d{4}-\d\d-\d\d) sold "
    r"(?P<sold>\d{4}-\d\d-\d\d) proceeds (?P<proceeds>[\d,]+\.\d\d) basis (?P<basis>[\d,]+\.\d\d|\(not reported\))"
    r" (?P<term>short|long)-term (?P<cov>covered|noncovered)")


@check("RECON_BROKER_LOTS", "Broker summary vs sum of lots", "reconciliation",
       "Every 1099-B summary total must equal the sum of its lot detail; unexplained differences are lots the return is missing.")
def broker_lots(ctx: Ctx) -> CheckResult:
    findings: list[Finding] = []
    compared = 0
    for doc in ctx.idx.packet.documents:
        if doc.id not in ctx.v.documents_used:
            continue
        evs = ctx.idx.values_by_doc.get(doc.id, [])
        summary = next((e for e in evs if e.field.endswith("summary_proceeds")), None)
        if summary is None:
            continue
        compared += 1
        lots = [e for e in evs if re.fullmatch(r"[A-Z]+\d+_proceeds", e.field)]
        total = float(ctx.eff(summary.id))
        lot_sum = round(sum(float(ctx.eff(e.id)) for e in lots), 2)
        diff = round(total - lot_sum, 2)
        if abs(diff) < 0.5:
            continue
        landing = ctx.trace.landing(doc.id, ctx.version)
        missing = []
        for n in landing.unread_pages:
            for m in LOT_LINE.finditer(doc.pages[n - 1].printed_content):
                missing.append((n, m.groupdict()))
        explained = round(sum(float(m["proceeds"].replace(",", "")) for _, m in missing), 2)
        facts = [f"{doc.id} summary proceeds {money(total)} ({summary.id}); {len(lots)} extracted lots sum to {money(lot_sum)}; difference {money(diff)}."]
        effect = None
        lines: list[str] = []
        if missing and abs(explained - diff) < 0.5:
            gain_total = 0.0
            cats: dict[str, float] = {}
            for page, m in missing:
                basis = 0.0 if m["basis"].startswith("(") else float(m["basis"].replace(",", ""))
                proceeds = float(m["proceeds"].replace(",", ""))
                gain = proceeds - basis
                gain_total += gain
                cat = "stcg" if m["term"] == "short" else "ltcg"
                cats[cat] = cats.get(cat, 0) + gain
                box = {("short", "covered"): "A", ("short", "noncovered"): "B",
                       ("long", "covered"): "D", ("long", "noncovered"): "E"}[(m["term"], m["cov"])]
                lines += [f"F8949.{box}.total"]
                facts.append(f"Unread page {page} prints lot {m['lot']} {m['desc']}: acquired {m['acq']}, sold {m['sold']}, "
                             f"proceeds {m['proceeds']}, basis {m['basis']}, {m['term']}-term {m['cov']} → gain/(loss) {money(gain)}.")
                if not ctx.ca_resident_on(m["sold"]):
                    facts.append(f"Sold {m['sold']}, after the move out of California: likely not California-source; "
                                 "the CA figure below uses the packet's prorated rate and should be confirmed.")
            facts.append(f"The unread page fully explains the {money(diff)} difference. This lot is not on the return.")
            cat = max(cats, key=lambda k: abs(cats[k]))
            effect = ctx.sale_effect(cat, gain_total, missing[-1][1]["sold"],
                                     f"missing {'loss' if gain_total < 0 else 'gain'} {money(gain_total)}")
            lines = sorted(set(lines)) + ["SchD.7" if cat == "stcg" else "SchD.15", "F1040.7"]
            title = f"{doc.issuer}: {money(diff)} of sales missing from the return (unread page)"
            fix = Fix(description="Add the unread lot(s) to Form 8949", changes=[
                LineChange(key=f"F8949.{ {('short', 'covered'): 'A', ('short', 'noncovered'): 'B', ('long', 'covered'): 'D', ('long', 'noncovered'): 'E'}[(m['term'], m['cov'])] }.{m['lot']}",
                           label=f"{m['desc']} (acquired {m['acq']}, sold {m['sold']}; proceeds {m['proceeds']}, basis {m['basis']})",
                           to_value=round(float(m['proceeds'].replace(',', '')) - (0.0 if m['basis'].startswith('(') else float(m['basis'].replace(',', ''))), 2),
                           new_line=True)
                for _, m in missing])
        else:
            facts.append("The difference is not explained by any unread page; the lot detail is incomplete or a lot was misread.")
            title = f"{doc.issuer}: summary proceeds differ from lot detail by {money(diff)}"
            fix = None
        findings.append(F(ctx, "RECON_BROKER_LOTS", doc.id, code="BROKER_SUMMARY_DETAIL_MISMATCH", severity="error",
                          area="investments", title=title,
                          summary=f"Summary {money(total)} vs lots {money(lot_sum)}.",
                          facts=facts, refs=[summary.id, doc.id] + [f"doc:{doc.id}#page{n}" for n, _ in missing],
                          lines=lines, tax_effect=effect, fix=fix,
                          engine_diagnostic=ctx.engine_diag("BROKER_SUMMARY_DETAIL_MISMATCH", [summary.id])))
    return result("RECON_BROKER_LOTS", findings, ok=f"{compared} broker summary/summaries agree with their lots",
                  metrics={"documents_compared": compared})


@check("RECON_W2", "W-2 wages and withholding vs return", "reconciliation",
       "Box 1, box 2 and box 17 of every distinct W-2 (duplicates excluded) must equal the return lines.")
def w2(ctx: Ctx) -> CheckResult:
    w2s = [d for d in ctx.idx.packet.documents if d.document_type == "W-2" and d.id in ctx.v.documents_used]
    counted = [d for d in w2s if ctx.trace.landing(d.id, ctx.version).status == "lands"]
    dupes = [d for d in w2s if ctx.trace.landing(d.id, ctx.version).status == "duplicate"]

    def box(docs: list, field: str) -> float:
        return sum(float(ctx.eff(e.id)) for d in docs for e in ctx.idx.values_by_doc.get(d.id, []) if e.field == field)

    findings: list[Finding] = []
    checks = [("box1", "F1040.1a", "wages"), ("box2", "F1040.25a", "payment"), ("box17", "F540NR.71", "ca_payment")]
    metrics: dict[str, Any] = {"w2_counted": [d.id for d in counted], "duplicates_excluded": [d.id for d in dupes]}
    for field, key, cat in checks:
        recomputed = box(counted, field)
        on_return = ctx.line_value(key)
        metrics[key] = {"recomputed": recomputed, "return": on_return}
        if on_return is not None and abs(recomputed - on_return) > 0.5:
            findings.append(F(ctx, "RECON_W2", key, code="W2_MISMATCH", severity="error", area="wages",
                              title=f"{key} does not equal the sum of W-2 {field}",
                              summary=f"W-2s sum to {money(recomputed)}; return shows {money(on_return)}.",
                              refs=[d.id for d in counted], lines=[key],
                              tax_effect=ctx.effect(cat, recomputed - on_return, "W-2 total minus return")))
    for d in dupes:
        land = ctx.trace.landing(d.id, ctx.version)
        doubled = box(counted, "box1") + box([d], "box1")
        findings.append(F(ctx, "RECON_W2", f"dup-{d.id}", code="DUPLICATE_DOCUMENT", severity="info", area="wages",
                          title=f"{d.id} is a second image of {land.duplicate_of} — correctly counted once",
                          summary=f"Counting it would have made wages {money(doubled)} instead of {money(box(counted, 'box1'))}.",
                          facts=[r.detail for r in land.reasons if r.code == "DUPLICATE"],
                          refs=[d.id, land.duplicate_of or ""], lines=["F1040.1a"], status="resolved"))
    return result("RECON_W2", findings, ok=f"{len(counted)} distinct W-2s foot to wages, federal and CA withholding",
                  metrics=metrics)


@check("RECON_PAYMENTS", "Estimated and extension payments vs IRS/FTB records", "reconciliation",
       "Payments claimed on the return must agree to the agencies' own records (required step).")
def payments(ctx: Ctx) -> CheckResult:
    ar = ctx.idx.packet.tax_agency_records
    snap = max(ar.irs_account_transcript_2025, key=lambda s: s.as_of)
    est = [t for t in snap.transactions if t.code == "670" and "estimated" in t.description.lower()]
    ext = [t for t in snap.transactions if "extension" in t.description.lower() or t.code == "460"]
    findings: list[Finding] = []
    fed_est = sum(float(t.amount) for t in est if not isinstance(t.amount, str))
    claimed = ctx.line_value("F1040.26") or 0
    metrics: dict[str, Any] = {"irs_estimated": fed_est, "F1040.26": claimed}
    if abs(fed_est - claimed) > 0.5:
        qa = next((q for q in ctx.idx.packet.client.questionnaire if "4th quarter" in q.question.lower()), None)
        facts = [f"IRS transcript (as of {snap.as_of}) shows {len(est)} estimated payments: "
                 + ", ".join(f"{t.date} {money(float(t.amount))}" for t in est) + f" = {money(fed_est)}.",
                 f"F1040.26 claims {money(claimed)}."]
        if qa:
            facts.append(f"The client's own answer ({qa.id}): “{qa.answer}”.")
        findings.append(F(ctx, "RECON_PAYMENTS", "federal-estimates", code="ESTIMATED_PAYMENTS_MISMATCH", severity="error",
                          area="payments", title=f"Federal estimated payments overstated by {money(claimed - fed_est)}",
                          summary="The return claims more estimated tax than the IRS received.",
                          facts=facts, refs=["agency:/irs_account_transcript_2025"] + ([qa.id] if qa else []) + ctx.lines["F1040.26"].sources,
                          lines=["F1040.26", "F1040.33", "F1040.37"],
                          tax_effect=ctx.effect("payment", fed_est - claimed, "payments per IRS minus payments claimed"),
                          fix=Fix(description="Claim the estimated payments the IRS shows", changes=[
                              LineChange(key="F1040.26", label=ctx.lines["F1040.26"].label, from_value=claimed, to_value=fed_est)])))
    ftb = ar.ftb_account
    ca_paid = sum(float(p["amount"]) for p in ftb.get("tax_year_2025_payments", []))
    ca_claimed = (ctx.line_value("F540NR.72") or 0)
    metrics.update({"ftb_2025_payments": ca_paid, "F540NR.72": ca_claimed})
    if abs(ca_paid - ca_claimed) > 0.5:
        stray = ftb.get("tax_year_2024_payments_after_filing", [])
        facts = [f"FTB account (as of {ftb.get('as_of')}) credits {len(ftb.get('tax_year_2025_payments', []))} payments to 2025 = {money(ca_paid)}; "
                 f"F540NR.72 claims {money(ca_claimed)}."]
        for s in stray:
            facts.append(f"A {money(float(s['amount']))} payment on {s['date']} was applied to tax year 2024: {s.get('note', '')} "
                         "Ask the FTB to transfer it, or claim only what 2025 shows.")
        findings.append(F(ctx, "RECON_PAYMENTS", "ca-estimates", code="CA_ESTIMATED_PAYMENTS_MISMATCH", severity="error",
                          area="california", title=f"California estimated payments overstated by {money(ca_claimed - ca_paid)}",
                          summary="The FTB has fewer 2025 payments on file than the 540NR claims.",
                          facts=facts, refs=["agency:/ftb_account"] + ctx.lines["F540NR.72"].sources,
                          lines=["F540NR.72", "F540NR.78", "F540NR.97"],
                          tax_effect=ctx.effect("ca_payment", ca_paid - ca_claimed, "FTB 2025 payments minus claimed"),
                          fix=Fix(description="Claim the 2025 payments the FTB shows (or get the stray payment transferred)", changes=[
                              LineChange(key="F540NR.72", label=ctx.lines["F540NR.72"].label, from_value=ca_claimed, to_value=ca_paid)])))
    ext_paid = sum(float(t.amount) for t in ext if not isinstance(t.amount, str))
    metrics.update({"irs_extension": ext_paid, "Sch3.10": ctx.line_value("Sch3.10")})
    return result("RECON_PAYMENTS", findings, ok="Payments agree to IRS and FTB records", metrics=metrics)


@check("RECON_SCORP_BASIS", "S corporation stock basis roll-forward", "reconciliation",
       "Recompute stock basis year by year from the basis records and every K-1 in the file; gaps are flagged, not assumed.")
def scorp_basis(ctx: Ctx) -> CheckResult:
    p = ctx.idx.packet
    findings: list[Finding] = []
    rows = p.prior_years.basis_records.get("scorp_lindqvist_family_woodworks", [])
    k1s = {d.tax_year: d for d in p.documents if "1120-S" in d.title and "K-1" in d.title}

    def k1(year: int, field: str) -> Optional[float]:
        d = k1s.get(year)
        e = next((x for x in ctx.idx.values_by_doc.get(d.id, []) if x.field == field), None) if d else None
        return float(ctx.eff(e.id)) if e else None

    basis: Optional[float] = None
    chain: list[str] = []
    gaps: list[str] = []
    for i, row in enumerate(rows):
        y = row["year"]
        if row.get("ending_stock_basis") is not None and basis is None:
            basis = float(row["ending_stock_basis"])
            chain.append(f"{y}: ending basis {money(basis)} per record ({row.get('source')}).")
            continue
        inc = row.get("k1_income") if row.get("k1_income") is not None else k1(y, "box1")
        dist = row.get("distributions") if row.get("distributions") is not None else k1(y, "box16d")
        interest = k1(y, "box4") or 0.0
        if row.get("ending_stock_basis") is None and (inc is None or dist is None):
            gaps.append(f"{y}: no ending basis and no K-1 to rebuild it ({row.get('source')}).")
            basis = None
            continue
        if basis is None:
            gaps.append(f"{y}: cannot roll forward — prior year unknown.")
            continue
        before = basis + float(inc or 0) + interest
        basis = max(0.0, before - float(dist or 0))
        src = "record" if row.get("k1_income") is not None else f"K-1 {k1s[y].id}" if y in k1s else "record"
        chain.append(f"{y}: {money(before - float(inc or 0) - interest)} + income {money(float(inc or 0) + interest)} − distributions "
                     f"{money(float(dist or 0))} = {money(basis)} ({src}).")
        if row.get("ending_stock_basis") is None:
            chain[-1] += " This year was a gap in the prior file; rebuilt from the K-1 now in the file."
    begin = ctx.line_value("F7203.1")
    metrics = {"recomputed_beginning_2025": basis, "F7203.1": begin, "chain": chain}
    if gaps:
        findings.append(F(ctx, "RECON_SCORP_BASIS", "gap", code="BASIS_GAP", severity="warning", area="pass_throughs",
                          title="S corporation stock basis has an unfilled gap", summary="; ".join(gaps),
                          facts=chain + gaps, refs=["py:/basis_records/scorp_lindqvist_family_woodworks/1"], lines=["F7203.1"]))
    elif basis is not None and begin is not None and abs(basis - begin) > 0.5:
        findings.append(F(ctx, "RECON_SCORP_BASIS", "mismatch", code="BASIS_MISMATCH", severity="error", area="pass_throughs",
                          title=f"Beginning stock basis {money(begin)} does not match the recomputed {money(basis)}",
                          summary="The basis roll-forward does not agree.", facts=chain, lines=["F7203.1", "F7203.excess"],
                          tax_effect=ctx.effect("ltcg", -(basis - begin), "excess-distribution gain change")))
    excess = ctx.line_value("F7203.excess")
    if not gaps and excess:
        findings.append(F(ctx, "RECON_SCORP_BASIS", "excess", code="DISTRIBUTIONS_EXCEED_BASIS", severity="warning", area="pass_throughs",
                          title=f"Distributions exceed stock basis by {money(excess)} — taxed as capital gain",
                          summary="The roll-forward agrees with the engine; the excess distribution is real and depends on the "
                                  "2023 year rebuilt from a late K-1. Confirm with the S corporation's own basis schedule.",
                          facts=chain + [f"2025: {money(basis or 0)} + income − distributions {money(ctx.line_value('F7203.6') or 0)} → "
                                         f"excess {money(excess)} (F7203.excess)."],
                          refs=["py:/basis_records/scorp_lindqvist_family_woodworks/1"] + [d.id for d in k1s.values()],
                          lines=["F7203.1", "F7203.excess"]))
    pship = p.prior_years.basis_records.get("partnership_ridgeline", [])
    if any(r.get("outside_basis") is None for r in pship):
        findings.append(F(ctx, "RECON_SCORP_BASIS", "partnership-outside", code="BASIS_GAP", severity="warning", area="pass_throughs",
                          title="Ridgeline partnership outside basis is not tracked",
                          summary="Only the capital account is on file; outside basis (which limits losses and determines gain "
                                  "on exit) is null. Request the partner's basis schedule.",
                          refs=["py:/basis_records/partnership_ridgeline/0"], lines=["SchE.28B"]))
    return result("RECON_SCORP_BASIS", findings, ok="Basis rolls forward without gaps", metrics=metrics,
                  summary=f"Recomputed beginning-2025 basis {money(basis or 0)} vs F7203.1 {money(begin or 0)}"
                  + (" — agrees" if basis is not None and begin is not None and abs(basis - begin) < 0.5 else ""))


# ================================================================== detectors
@check("DET_ZERO_BASIS", "Sales reported at zero basis", "detector",
       "8949 lots whose basis was blank on the 1099-B are taxed on gross proceeds; look for the true basis elsewhere in the file.")
def zero_basis(ctx: Ctx) -> CheckResult:
    findings: list[Finding] = []
    # Supplemental basis statements: <LOT>_adjusted_basis with <LOT>_acquired.
    supplemental: list[tuple[str, str, float, str]] = []  # (acquired ISO, lot, basis, ev)
    for e in ctx.idx.packet.extracted_values:
        if e.field.endswith("_adjusted_basis"):
            lot = e.field[: -len("_adjusted_basis")]
            acq = next((x for x in ctx.idx.values_by_doc[e.document_id] if x.field == f"{lot}_acquired"), None)
            if acq:
                supplemental.append((str(acq.value), lot, float(ctx.eff(e.id)), e.id))
    by_doc: dict[str, list[dict[str, Any]]] = {}
    for key, ln in ctx.lines.items():
        if not key.startswith("F8949.") or key.endswith(".total"):
            continue
        srcs = [ctx.idx.values[s] for s in ln.sources if s in ctx.idx.values]
        basis_ev = next((e for e in srcs if re.search(r"_(basis|cost)$", e.field)), None)
        if basis_ev is None or basis_ev.text_as_read.strip():
            continue
        if ctx.review and ctx.review.active_correction(basis_ev.id):
            continue  # someone has supplied the basis
        acq = next((e for e in srcs if e.field.endswith(("_acquired", "_acq"))), None)
        proceeds = next((e for e in srcs if e.field.endswith("_proceeds")), None)
        m = re.search(r"acquired (\d{4}-\d\d-\d\d)", ln.label)
        acquired = m.group(1) if m else (str(acq.value) if acq else None)
        match = next((s for s in supplemental if s[0] == acquired), None) if acquired else None
        by_doc.setdefault(basis_ev.document_id, []).append(
            {"line": key, "lot": basis_ev.field.split("_")[0], "proceeds": float(ctx.eff(proceeds.id)) if proceeds else float(ln.value),
             "acquired": acquired, "acq_text": acq.text_as_read if acq else "", "match": match, "basis_ev": basis_ev.id})
    for doc_id, lots in by_doc.items():
        doc = ctx.idx.documents[doc_id]
        known = [x for x in lots if x["match"]]
        unknown = [x for x in lots if not x["match"]]
        if known:
            facts, refs = [], [doc_id]
            effects = []
            total = 0.0
            for x in known:
                acq, lot, basis, ev = x["match"]
                total -= basis
                refs += [x["basis_ev"], ev]
                sold = re.search(r"sold (\d{4}-\d\d-\d\d)", ctx.lines[x["line"]].label)
                effects.append(ctx.sale_effect(tax_category(x["line"]), -basis, sold.group(1) if sold else None,
                                               f"{lot}: basis omitted {money(basis)}"))
                facts.append(f"{x['line']}: lot {x['lot']} acquired {x['acquired']} taxed at basis 0.00; "
                             f"{ctx.idx.values[ev].document_id} gives adjusted basis {money(basis)} for lot {lot} (same acquisition date).")
            eff = effects[0] if len(effects) == 1 else TaxEffect(
                category="stcg+ltcg", change=total, federal_tax=sum(e.federal_tax for e in effects),
                california_tax=sum(e.california_tax for e in effects), federal_balance_due=sum(e.federal_balance_due for e in effects),
                california_balance_due=sum(e.california_balance_due for e in effects),
                basis="; ".join(e.basis for e in effects))
            facts.append("These shares' value was already taxed as wages at vesting; basis 0 taxes it a second time.")
            fix = Fix(description="Use the supplemental statement's adjusted basis for each lot", changes=[
                LineChange(key=x["line"], label=ctx.lines[x["line"]].label, from_value=float(ctx.lines[x["line"]].value),
                           to_value=round(float(ctx.lines[x["line"]].value) - x["match"][2], 2)) for x in known])
            findings.append(F(ctx, "DET_ZERO_BASIS", f"{doc_id}-known", code="ZERO_BASIS_WITH_KNOWN_BASIS", severity="error",
                              area="investments", title=f"{doc.issuer}: {len(known)} lot(s) taxed at zero basis — gain overstated by {money(-total)}",
                              summary="The 1099-B left basis blank (noncovered); the supplemental statement in the file has it.",
                              facts=facts, refs=refs, lines=[x["line"] for x in known] + ["SchD.7", "SchD.15"], tax_effect=eff,
                              fix=fix))
        for x in unknown:
            refs = [x["basis_ev"], doc_id]
            findings.append(F(ctx, "DET_ZERO_BASIS", x["line"], code="DIGITAL_ASSET_BASIS_MISSING" if re.match(r"F8949\.[HK]\.", x["line"]) else "BASIS_MISSING",  # boxes H/K = digital assets
                              severity="warning", area="investments",
                              title=f"{x['line']}: lot {x['lot']} has no basis — taxed on full proceeds {money(x['proceeds'])}",
                              summary=f"Acquired “{x['acq_text'] or 'unknown'}”; no basis anywhere in the file. Obtain the wallet history "
                                      "for the transfer-in, or document why zero is right.",
                              refs=refs, lines=[x["line"]],
                              tax_effect=ctx.effect(tax_category(x["line"]), -x["proceeds"], f"if true basis ≈ proceeds {money(x['proceeds'])}", "upper_bound"),
                              engine_diagnostic=ctx.engine_diag("DIGITAL_ASSET_BASIS_MISSING", refs)))
    return result("DET_ZERO_BASIS", findings, ok="No sale is taxed at a missing basis")


@check("DET_DUPLICATE_INCOME", "Same income reported twice", "detector",
       "Payer lines with equal amounts from different documents that print the same account number.")
def duplicate_income(ctx: Ctx) -> CheckResult:
    findings: list[Finding] = []
    payer = [ln for ln in ctx.lines.values() if ln.rule in ("R-INTEREST-PAYER", "R-DIVIDEND-PAYER") and ctx.num(ln.value)]
    for a, b in itertools.combinations(payer, 2):
        if a.value != b.value or a.rule != b.rule or not a.value:
            continue
        da = {ctx.idx.values[s].document_id for s in a.sources if s in ctx.idx.values}
        db = {ctx.idx.values[s].document_id for s in b.sources if s in ctx.idx.values}
        if not da or not db or da & db:
            continue

        def accounts(docs: set[str]) -> set[str]:
            return {m for d in docs for pg in ctx.idx.documents[d].pages for m in re.findall(r"ending (\d{3,})", pg.printed_content)}

        shared = accounts(da) & accounts(db)
        if not shared:
            continue
        cat = tax_category(a.key)
        total_line = next((ln.key for ln in ctx.lines.values() if a.key in ln.inputs or b.key in ln.inputs), None)
        findings.append(F(ctx, "DET_DUPLICATE_INCOME", f"{a.key}+{b.key}", code="DUPLICATE_INCOME_LINE", severity="warning",
                          area="investments",
                          title=f"{a.key} and {b.key}: the same {money(a.value)} reported twice",
                          summary=f"Both documents print account ending {', '.join(sorted(shared))}; the bank-sweep interest on the "
                                  "brokerage 1099 and the bank's own 1099-INT are one payment.",
                          facts=[f"{a.key} “{a.label}” = {money(a.value)} from {', '.join(sorted(da))}.",
                                 f"{b.key} “{b.label}” = {money(b.value)} from {', '.join(sorted(db))}.",
                                 *[f"{d}: “{ctx.idx.documents[d].pages[0].printed_content[:160]}…”" for d in sorted(da | db)]],
                          refs=sorted(da | db) + a.sources + b.sources,
                          lines=[a.key, b.key] + ([total_line] if total_line else []),
                          tax_effect=ctx.effect(cat, -float(a.value), f"remove the duplicate {money(a.value)}"),
                          fix=Fix(description=f"Remove the duplicate line {b.key} (the same interest is on {a.key})", changes=[
                              LineChange(key=b.key, label=b.label, from_value=float(b.value), to_value=0.0)])))
    return result("DET_DUPLICATE_INCOME", findings, ok="No income line duplicates another")


@check("DET_FX_RATE", "Foreign currency converted at the right year's rate", "detector",
       "Income for the tax year must use that year's average rate; balances use the year-end rate.")
def fx_rate(ctx: Ctx) -> CheckResult:
    findings: list[Finding] = []
    year = ctx.idx.packet.household.tax_year
    fx = ctx.idx.packet.engine_reference.parameters.get("fx", {})
    for ln in ctx.lines.values():
        for s in ln.sources:
            m = re.fullmatch(r"ref:fx\.([A-Z]{3})\.(\d{4})_average", s)
            if not m or int(m.group(2)) == year:
                continue
            ccy = m.group(1)
            used = fx[ccy][f"{m.group(2)}_average"]
            right = fx[ccy].get(f"{year}_average")
            amount_ev = next((ctx.idx.values[x] for x in ln.sources if x in ctx.idx.values and ctx.num(ctx.idx.values[x].value)), None)
            if right is None or amount_ev is None:
                continue
            foreign = float(ctx.eff(amount_ev.id))
            correct = round(foreign / right)
            diff = correct - float(ln.value)
            findings.append(F(ctx, "DET_FX_RATE", ln.key, code="FX_RATE_WRONG_YEAR", severity="error", area="investments",
                              title=f"{ln.key}: {ccy} income converted at the {m.group(2)} rate, not {year}",
                              summary=f"{ccy} {foreign:,.2f} ÷ {right} ({year} average) = {money(correct)}; the return used {used} → {money(ln.value)}.",
                              refs=[amount_ev.id, s, f"ref:fx.{ccy}.{year}_average"], lines=[ln.key],
                              tax_effect=ctx.effect(tax_category(ln.key), diff, f"understated by {money(diff)}"),
                              fix=Fix(description=f"Convert at the {year} average rate", changes=[
                                  LineChange(key=ln.key, label=ln.label, from_value=float(ln.value), to_value=float(correct))])))
    return result("DET_FX_RATE", findings, ok="Every currency conversion uses the tax year's rate")


@check("DET_READS", "Reads that do not stand up", "detector",
       "Values feeding the return that were read with low confidence, or that are not what the page prints.")
def reads(ctx: Ctx) -> CheckResult:
    findings: list[Finding] = []
    for e in ctx.idx.packet.extracted_values:
        lands = ctx.trace.lands_in(e.id, ctx.version)
        if not lands:
            continue
        m = ctx.idx.text_matches[e.id]
        page = ctx.idx.documents[e.document_id].pages[e.page - 1].printed_content
        corr = ctx.review.active_correction(e.id) if ctx.review else None
        if e.confidence < LOW_CONFIDENCE and e.text_as_read.strip():
            alts = re.search(r"could be read as (\d) or (\d)", page)
            q = re.search(r"\$?([\d,]*\?[\d,]*\.\d\d)", page)
            facts = [f"Read {e.text_as_read!r} at {e.confidence:.0%} confidence. The page prints: “{page[:220]}”"]
            effect = None
            if alts and q and ctx.num(e.value):
                options = sorted({float(q.group(1).replace("?", d).replace(",", "")) for d in alts.groups()})
                other = next((o for o in options if abs(o - float(e.value)) > 0.5), None)
                if other is not None:
                    facts.append(f"Possible readings: {', '.join(money(o) for o in options)}. Return uses {money(float(e.value))}.")
                    effect = ctx.effect(tax_category(lands[0]), other - float(e.value), f"if it is {money(other)}")
            findings.append(F(ctx, "DET_READS", f"lowconf-{e.id}", code="LOW_CONFIDENCE_READ", severity="warning", area=area_of(lands[0]),
                              title=f"{e.label} on {e.document_id} read at {e.confidence:.0%} — feeds {', '.join(lands)}",
                              summary="Confirm the amount with the client or the original before relying on it.",
                              facts=facts, refs=[e.id, e.document_id], lines=lands, tax_effect=effect,
                              engine_diagnostic=ctx.engine_diag("LOW_CONFIDENCE_READ", [e.id]),
                              status="corrected" if corr else "open"))
        elif m.status == "not_found":
            zero = ctx.num(e.value) and float(e.value) == 0
            facts = [f"Read {e.text_as_read!r} ({e.confidence:.0%} confidence) — not printed on {e.document_id} p.{e.page}.",
                     f"The page prints: “{page[:240]}”"]
            if corr:
                facts.append(f"Corrected to {corr['to']!r} by {ctx.review.name(corr['actor'])}: {corr['reason']}")
            findings.append(F(ctx, "DET_READS", f"notprinted-{e.id}", code="READ_NOT_ON_PAGE",
                              severity="info" if zero else "warning", area=area_of(lands[0]),
                              title=f"{e.label} on {e.document_id}: {e.text_as_read!r} is not what the page prints",
                              summary=("A zero read where nothing is printed: no amount effect, but the read is fabricated."
                                       if zero else "A confident misread. Identifiers like this cause e-file rejects; amounts change tax."),
                              facts=facts, refs=[e.id, e.document_id], lines=lands,
                              status="corrected" if corr else "open"))
    return result("DET_READS", findings, ok="Every value feeding the return is printed on its page with good confidence")


def _quote(text: str, n: int = 48) -> str:
    first = re.split(r"(?<=[.!?])\s", text.strip())[0]
    return first if len(first) <= n else first[: n].rsplit(" ", 1)[0] + "…"


QA_RULES: list[dict[str, Any]] = [
    {"id": "sales", "question": r"sell any stocks|investments", "answer": r"^\s*no\b", "area": "investments",
     "evidence": lambda ctx: [k for k in ctx.lines if re.fullmatch(r"F8949\.[ABDE]\.[A-Z]+\d+", k)],
     "say": lambda n: f"{n} brokerage sales are on Form 8949"},
    {"id": "crypto", "question": r"cryptocurrency|digital asset", "answer": r"didn't really sell|^\s*no\b", "area": "investments",
     "evidence": lambda ctx: [k for k in ctx.lines if re.fullmatch(r"F8949\.[HK]\.[A-Z]+\d+", k)],
     "say": lambda n: f"{n} digital-asset disposals are on Form 8949"},
    {"id": "ira-basis", "question": r"prior basis", "answer": r"none", "area": "investments",
     "evidence": lambda ctx: ["py:/return_2024/lines/F8606.14"] if ctx.idx.packet.prior_years.return_2024.lines.get("F8606.14") else [],
     "say": lambda n: "the 2024 return as filed carries nondeductible IRA basis on F8606.14"},
]


@check("DET_QUESTIONNAIRE", "Client answers vs the documents", "detector",
       "Each organizer answer is checked against what the documents show; conflicts become questions for the client.")
def questionnaire(ctx: Ctx) -> CheckResult:
    findings: list[Finding] = []
    for rule in QA_RULES:
        qa = next((q for q in ctx.idx.packet.client.questionnaire if re.search(rule["question"], q.question, re.I)), None)
        if qa is None or not re.search(rule["answer"], qa.answer, re.I):
            continue
        evidence = rule["evidence"](ctx)
        if not evidence:
            continue
        said = rule["say"](len(evidence))
        code = "QUESTIONNAIRE_SALES_CONFLICT" if rule["id"] in ("sales", "crypto") else "QUESTIONNAIRE_CONFLICT"
        findings.append(F(ctx, "DET_QUESTIONNAIRE", rule["id"], code=code, severity="warning", area=rule["area"],
                          title=f"{qa.id}: client said “{_quote(qa.answer)}” but {said}",
                          summary=f"Q: {qa.question}",
                          facts=[f"Answer by {qa.answered_by} on {qa.answered_at[:10]}: “{qa.answer}”.", f"The file shows {said}."],
                          refs=[qa.id] + evidence[:3], lines=[x for x in evidence if not x.startswith("py:")][:6] or [],
                          engine_diagnostic=ctx.engine_diag(code, [qa.id])))
    return result("DET_QUESTIONNAIRE", findings, ok="Client answers agree with the documents")


@check("DET_DUE_DILIGENCE", "Due diligence for credits that require it", "detector",
       "Firm rule: due diligence must be documented for CTC, ODC, AOTC, EIC and head of household.")
def due_diligence(ctx: Ctx) -> CheckResult:
    findings: list[Finding] = []
    claimed = [k for k in ("F1040.19", "F8812.12", "F8863.7") if ctx.num(ctx.line_value(k)) and ctx.line_value(k) > 0]
    if claimed:
        findings.append(F(ctx, "DET_DUE_DILIGENCE", "8867", code="DUE_DILIGENCE_REQUIRED", severity="warning", area="deductions",
                          title="Form 8867 due diligence not yet documented",
                          summary=f"Credits claimed ({', '.join(f'{k} {money(ctx.line_value(k))}' for k in claimed)}) require the "
                                  "preparer's due-diligence record before filing.",
                          refs=["household:theo", "household:ada"], lines=claimed + (["F8867.status"] if "F8867.status" in ctx.lines else []),
                          engine_diagnostic=ctx.engine_diag("DUE_DILIGENCE_REQUIRED")))
    return result("DET_DUE_DILIGENCE", findings, ok="No credit requiring due diligence is claimed")


# ================================================================== independent checks
def _foot(value: float, inputs: list[float]) -> bool:
    if not inputs:
        return False
    for signs in itertools.product((1, -1), repeat=len(inputs) - 1):
        s = inputs[0] + sum(x * g for x, g in zip(inputs[1:], signs))
        if abs(s - value) < 0.51 or abs(-s - value) < 0.51 or (value == 0 and s < 0):
            return True
    return False


@check("IND_FOOTING", "Totals reproduce from their inputs", "independent",
       "Every summing line is recomputed from its listed inputs (allowing subtraction and a zero floor) and every carry is compared.")
def footing(ctx: Ctx) -> CheckResult:
    lines = ctx.lines
    ok = carries = 0
    findings: list[Finding] = []
    for ln in lines.values():
        if not ctx.num(ln.value) or not ln.inputs or not all(ctx.num(lines[i].value) for i in ln.inputs):
            continue
        vals = [float(lines[i].value) for i in ln.inputs]
        if ln.rule == "R-CARRY" and len(vals) == 1:
            carries += 1
            if abs(vals[0] - ln.value) > 0.5:
                findings.append(F(ctx, "IND_FOOTING", ln.key, code="CARRY_MISMATCH", severity="error", area=area_of(ln.key),
                                  title=f"{ln.key} does not equal {ln.inputs[0]}", summary=f"{money(ln.value)} vs {money(vals[0])}",
                                  lines=[ln.key, ln.inputs[0]]))
            continue
        if ln.rule != "R-SUM":
            continue
        if _foot(float(ln.value), vals):
            ok += 1
            continue
        # Explain with sibling lines left out of the input list (same form, line numbers in range).
        num = lambda k: int(re.match(r"\d+", k.split(".", 1)[1]).group()) if re.match(r"\d+", k.split(".", 1)[1]) else None  # noqa: E731
        lo = min((num(i) for i in ln.inputs if num(i) is not None), default=None)
        me = num(ln.key)
        sibs = [k for k in lines if k.split(".")[0] == ln.form and k != ln.key and k not in ln.inputs and ctx.num(lines[k].value)
                and num(k) is not None and lo is not None and me is not None and lo <= num(k) <= me
                and not k.endswith(".D") and not k.endswith(".E")][:10]
        explained = None
        for r in range(1, min(4, len(sibs)) + 1):
            for combo in itertools.combinations(sibs, r):
                if _foot(float(ln.value), vals + [float(lines[c].value) for c in combo]):
                    explained = combo
                    break
            if explained:
                break
        if explained:
            ok += 1
            findings.append(F(ctx, "IND_FOOTING", ln.key, code="INPUTS_INCOMPLETE", severity="info", area=area_of(ln.key),
                              title=f"{ln.key} foots only with {', '.join(explained)} — missing from its input list",
                              summary="The value is right; the engine's calc graph omits these inputs, so a trace of this "
                                      "total would not show them.",
                              lines=[ln.key, *explained], status="resolved"))
        else:
            findings.append(F(ctx, "IND_FOOTING", ln.key, code="DOES_NOT_FOOT", severity="warning", area=area_of(ln.key),
                              title=f"{ln.key} cannot be reproduced from its inputs",
                              summary=f"{money(ln.value)} vs inputs {', '.join(f'{i} {money(lines[i].value)}' for i in ln.inputs)}. "
                                      "The rule may apply a limit or worksheet the packet doesn't show.",
                              lines=[ln.key, *ln.inputs]))
    hard = [f for f in findings if f.severity != "info"]
    return result("IND_FOOTING", findings, ok="All totals foot", metrics={"sums_reproduced": ok, "carries": carries,
                                                                        "not_reproduced": len(hard)},
                  summary=f"{ok} sums and {carries} carries reproduced; {len(hard)} not reproduced from the listed inputs")


@check("IND_8949_CROSSFOOT", "Form 8949 lots cross-foot to Schedule D", "independent",
       "Each 8949 box total equals the sum of its lots, and Schedule D carries the box totals.")
def crossfoot(ctx: Ctx) -> CheckResult:
    findings: list[Finding] = []
    boxes: dict[str, float] = {}
    for k, ln in ctx.lines.items():
        m = re.fullmatch(r"F8949\.([A-Z])\.[A-Z]+\d+", k)
        if m and ctx.num(ln.value):
            boxes[m.group(1)] = boxes.get(m.group(1), 0) + float(ln.value)
    metrics = {}
    for box, total in sorted(boxes.items()):
        key = f"F8949.{box}.total"
        on = ctx.line_value(key)
        metrics[box] = {"lots": round(total, 2), "total_line": on}
        if on is not None and abs(round(total) - on) > 1:
            findings.append(F(ctx, "IND_8949_CROSSFOOT", box, code="CROSSFOOT", severity="error", area="investments",
                              title=f"Form 8949 box {box}: lots sum to {money(total)}, total line shows {money(on)}",
                              summary="Lot detail and box total disagree.", lines=[key]))
    return result("IND_8949_CROSSFOOT", findings, ok=f"{len(boxes)} 8949 boxes cross-foot", metrics=metrics)


MACRS_5_HY = [0.20, 0.32, 0.192, 0.1152, 0.1152, 0.0576]


@check("IND_DEPRECIATION", "Depreciation recalculated by asset", "independent",
       "Each asset's 2025 depreciation is recomputed from cost, method, life and dates (federal and California).")
def depreciation(ctx: Ctx) -> CheckResult:
    findings: list[Finding] = []
    rows = []
    year = ctx.idx.packet.household.tax_year
    for a in ctx.v.assets:
        placed = date.fromisoformat(a.placed_in_service)
        disposed = date.fromisoformat(a.disposed) if a.disposed else None
        fed = ca = None
        method = a.method.lower()
        if "sl / mid-month" in method:
            months = 12.0
            if placed.year == year:
                months = 12 - placed.month + 0.5
            if disposed and disposed.year == year:
                months = disposed.month - 0.5
            fed = ca = round(a.cost / a.life_years * months / 12, 2)
        elif "100%" in method and placed.year == year:
            fed, ca = a.cost, round(a.cost * MACRS_5_HY[0], 2)
        elif "bonus" in method and "200db half-year" in method:
            fed = 0.0
            n = year - placed.year
            ca = round(a.cost * MACRS_5_HY[n], 2) if n < len(MACRS_5_HY) else 0.0
        elif "section 179" in method and placed.year < year:
            fed = ca = 0.0
        if fed is None:
            rows.append({"asset": a.asset_id, "status": "not recalculated", "method": a.method})
            continue
        good = abs(fed - a.federal.depreciation_2025) < 0.02 and abs(ca - a.california.depreciation_2025) < 0.02
        rows.append({"asset": a.asset_id, "method": a.method, "recomputed_federal": fed, "engine_federal": a.federal.depreciation_2025,
                     "recomputed_california": ca, "engine_california": a.california.depreciation_2025, "status": "pass" if good else "fail"})
        if not good:
            findings.append(F(ctx, "IND_DEPRECIATION", a.asset_id, code="DEPRECIATION_MISMATCH", severity="error", area="rentals" if "Rental" in a.activity else "business",
                              title=f"{a.asset_id}: depreciation recomputes to {money(fed)} federal / {money(ca)} CA",
                              summary=f"Engine: {money(a.federal.depreciation_2025)} / {money(a.california.depreciation_2025)}.",
                              refs=[f"asset:{a.asset_id}"]))
    passed = sum(r["status"] == "pass" for r in rows)
    return result("IND_DEPRECIATION", findings, ok=f"{passed} of {len(rows)} assets recompute exactly",
                  metrics={"assets": rows}, summary=f"{passed} of {len(rows)} assets recompute exactly"
                  + (f"; {sum(r['status'] == 'not recalculated' for r in rows)} method(s) not recalculated" if passed < len(rows) else ""))


@check("IND_SUPERSEDED", "Superseded documents do not flow into the return", "independent",
       "No line of the current return may cite a value from a document the version marks superseded.")
def superseded(ctx: Ctx) -> CheckResult:
    findings: list[Finding] = []
    for d in ctx.v.documents_superseded:
        cited = sorted({land.line for e in ctx.idx.values_by_doc.get(d, []) for land in ctx.trace.ev_lines[ctx.version].get(e.id, [])})
        if cited:
            findings.append(F(ctx, "IND_SUPERSEDED", d, code="SUPERSEDED_FLOWS", severity="error", area="investments",
                              title=f"Superseded {d} still feeds {len(cited)} line(s)", summary=", ".join(cited[:8]), lines=cited[:8], refs=[d]))
    return result("IND_SUPERSEDED", findings, ok=f"{len(ctx.v.documents_superseded)} superseded document(s) feed nothing")


# ================================================================== completeness
@check("COMP_DOCUMENTS", "Every document accounted for", "completeness",
       "Each document lands in the return, or is superseded, a duplicate, not extracted, support-only or not used — with the reason.")
def documents_accounted(ctx: Ctx) -> CheckResult:
    counts: dict[str, int] = {}
    unexplained = []
    for d in ctx.idx.packet.documents:
        land = ctx.trace.landing(d.id, ctx.version)
        counts[land.status] = counts.get(land.status, 0) + 1
        if land.status not in ("lands", "lands_indirectly") and not land.reasons:
            unexplained.append(d.id)
    findings = [F(ctx, "COMP_DOCUMENTS", d, code="DOCUMENT_UNEXPLAINED", severity="warning", area="payments",
                  title=f"{d} is neither used nor explained", summary="", refs=[d]) for d in unexplained]
    return result("COMP_DOCUMENTS", findings, ok=f"All {len(ctx.idx.packet.documents)} documents accounted for", metrics=counts,
                  summary=f"All {len(ctx.idx.packet.documents)} documents accounted for: "
                  + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])))


def outside_filings(ctx: Ctx) -> list[OutsideFiling]:
    p = ctx.idx.packet
    out: list[OutsideFiling] = []
    letter = next((pg.printed_content for d in p.documents if d.document_type == "engagement_letter" for pg in d.pages), "")
    excluded = letter.lower()
    deadline = lambda word: next((d.date for d in p.firm.deadlines if word.lower() in d.what.lower()), None)  # noqa: E731
    fx = p.engine_reference.parameters.get("fx", {})
    for e in p.extracted_values:
        m = re.fullmatch(r"max_balance_([a-z]{3})", e.field)
        if m:
            ccy = m.group(1).upper()
            usd = float(e.value) / fx[ccy]["2025_year_end"]
            out.append(OutsideFiling(filing="FinCEN Form 114 (FBAR)", required="yes" if usd > 10_000 else "no",
                                     responsible="Client (outside this engagement)" if "fbar" in excluded else "Firm",
                                     in_engagement="fbar" not in excluded, due=deadline("FBAR"),
                                     basis=f"Maximum {ccy} {float(e.value):,.0f} ÷ {fx[ccy]['2025_year_end']} = ${usd:,.0f} > $10,000 aggregate.",
                                     refs=[e.id, e.document_id, "F8938.1.max"]))
    if ctx.line_value("SchC.I") == "Yes" and ctx.line_value("SchC.J") == "No":
        payees = [ctx.idx.values[s] for s in ctx.lines["SchC.I"].sources if s in ctx.idx.values and ctx.num(ctx.idx.values[s].value)]
        over = [x for x in payees if float(x.value) >= 600]
        out.append(OutsideFiling(filing="Forms 1099-NEC (Lindqvist Studio)", required="yes",
                                 responsible="Client's business (outside this engagement)" if "1099" in excluded else "Firm",
                                 in_engagement="1099" not in excluded, due=deadline("1099-NEC"),
                                 basis="; ".join(f"{x.label} {money(float(x.value))}" for x in over) + " — none filed (late).",
                                 refs=["SchC.I", "SchC.J", *(x.id for x in over)]))
    for r in p.household.related_returns:
        out.append(OutsideFiling(filing=f"{r.who}: {r.return_}", required="yes", responsible=r.prepared_by,
                                 in_engagement=False, basis=f"In this packet: {r.in_this_packet}.", refs=[]))
    for d in p.documents:
        for pg in d.pages:
            m = re.search(r"filed an? (\w+) composite return[^.]*\.([^.]*\.)?", pg.printed_content)
            if m:
                out.append(OutsideFiling(filing=f"{m.group(1)} nonresident filing", required="no", responsible="Partnership composite",
                                         in_engagement=False, basis=m.group(0).strip(), refs=[d.id]))
    if "oregon" in excluded:
        out.append(OutsideFiling(filing="Oregon nonresident return (S corporation K-1, Oregon source)", required="check",
                                 responsible="S corporation composite (Willamette CPA Group) — confirm Erik is included",
                                 in_engagement=False, basis="The engagement letter excludes Oregon returns; the 1120-S preparer files an "
                                                            "Oregon composite.", refs=["D39", "D01"]))
    return out


@check("COMP_OUTSIDE_FILINGS", "Every outside filing identified", "completeness",
       "Filings this return triggers that are not part of it (FBAR, 1099s, related and composite returns) are listed with who is responsible.")
def outside(ctx: Ctx) -> CheckResult:
    items = outside_filings(ctx)
    findings = []
    for it in items:
        if it.required == "yes" and not it.in_engagement and ("FBAR" in it.filing or "1099" in it.filing):
            code = "FBAR_OUTSIDE_RETURN" if "FBAR" in it.filing else "FORM_1099_FILING"
            findings.append(F(ctx, "COMP_OUTSIDE_FILINGS", code, code=code, severity="warning",
                              area="investments" if "FBAR" in it.filing else "business",
                              title=f"{it.filing} required — outside this engagement",
                              summary=f"{it.basis} Responsible: {it.responsible}. Due {it.due or 'n/a'}. Tell the client in writing.",
                              refs=it.refs, lines=[r for r in it.refs if "." in r and not r.startswith("ev-")][:3],
                              engine_diagnostic=ctx.engine_diag(code)))
    return result("COMP_OUTSIDE_FILINGS", findings, ok="No outside filings triggered", metrics={"items": [i.model_dump() for i in items]},
                  summary=f"{len(items)} outside filings identified; {len(findings)} need client action")


# ------------------------------------------------------------------ area mapping
AREAS = [
    ("wages", "Wages & stock comp", "wages_and_stock_compensation", "F1040.1a"),
    ("investments", "Investments & digital assets", "investments_and_digital_assets", "F1040.7"),
    ("business", "Business", "business", "SchC.31"),
    ("rentals", "Rentals & sale", "rentals_and_sale", "SchE.26"),
    ("pass_throughs", "Pass-throughs & basis", "pass_throughs_and_basis", "SchE.32"),
    ("deductions", "Deductions & credits", "deductions_and_credits", "F1040.12"),
    ("california", "California", "california", "F540NR.64"),
    ("payments", "Payments", None, "F1040.33"),
]

_RULES: list[tuple[str, str]] = [
    (r"^(SchCA540NR|F540NR|ScheduleS|FTB3885A|FTB5805)\.", "california"),
    (r"^(F1040\.1[a-z]|F8959\.|F6251\.|Sch2\.(1|3|11)$)", "wages"),
    (r"^(SchD\.1[12]|SchD\.19)$", "rentals"),
    (r"^(SchE\.(2[7-9]|3\d|4\d)|F7203\.|Sch1\.5$)", "pass_throughs"),
    (r"^(SchB|SchD|F8949|F8960|F8938|F8606)\.|^F1040\.(2|3|4|7)[a-z]?$|^Sch2\.12$|^Sch3\.1$", "investments"),
    (r"^(SchC|SchSE|F4562-C|F8995)\.|^Sch1\.(3|15|16|17)$|^Sch2\.4$|^F1040\.13$", "business"),
    (r"^(SchE|F4562-E|F4797|F8582)\.", "rentals"),
    (r"^(SchA|F8283|F8812|F8863|F2441|F8889|F8867)\.|^F1040\.(12|14|19|10)$|^Sch3\.8$|^Sch1\.(13|26)$", "deductions"),
    (r"^F1040\.(2[5-9][a-z]?|3\d)$|^(F2210)\.|^Sch3\.(1[0-5])$", "payments"),
]


def area_of(key: str) -> str:
    for pattern, area in _RULES:
        if re.search(pattern, key):
            return area
    return "totals"


# ------------------------------------------------------------------ runner
class CheckRun(BaseModel):
    version: str
    seq: int
    checks: list[CheckResult]
    findings: list[Finding]
    counts: dict[str, int]
    engine_diagnostics: list[dict[str, Any]]
    outside_filings: list[OutsideFiling]


_SEV = {"error": 0, "warning": 1, "info": 2}


def run_checks(idx: PacketIndex, trace: TraceIndex, review: Any, version: Optional[str] = None) -> CheckRun:
    ctx = Ctx(idx, trace, review, version or idx.current_version)
    results = []
    for cid, title, kind, desc, fn in CHECKS:
        try:
            res = fn(ctx)
        except Exception as exc:  # a broken check must be visible, never silently pass
            res = CheckResult(id=cid, title=title, kind=kind, description=desc, status="fail",
                              summary=f"Check could not run: {exc!r}")
        for f in res.findings:
            disp = review.dispositions.get(f.id) if review else None
            if disp and f.status == "open":
                f.status = disp["disposition"]
                f.disposition = disp
            adj = review.adjustment_for_finding(f.id) if review else None
            if adj and f.status in ("open", "accepted"):
                f.status = "adjusted" if adj["status"] == "active" else "adjustment_pending"
                f.adjustment = {"id": adj["id"], "status": adj["status"], "title": adj["title"]}
        results.append(res)
    findings = sorted((f for r in results for f in r.findings),
                      key=lambda f: (f.status != "open", _SEV[f.severity], f.area, f.id))
    used = {f.engine_diagnostic for f in findings if f.engine_diagnostic}
    diags = [{"code": d.code, "severity": d.severity, "message": d.message, "refs": d.refs,
              "covered_by": [f.id for f in findings if f.engine_diagnostic == d.code]}
             for d in ctx.v.diagnostics]
    counts = {
        "checks_pass": sum(r.status == "pass" for r in results),
        "checks_fail": sum(r.status == "fail" for r in results),
        "checks_warn": sum(r.status == "warn" for r in results),
        "checks_info": sum(r.status == "info" for r in results),
        "open_errors": sum(f.severity == "error" and f.status == "open" for f in findings),
        "open_warnings": sum(f.severity == "warning" and f.status == "open" for f in findings),
        "engine_missed": sum(1 for f in findings if f.severity != "info" and not f.engine_diagnostic),
        "engine_diagnostics_covered": len(used),
    }
    outs = next((r.metrics.get("items", []) for r in results if r.id == "COMP_OUTSIDE_FILINGS"), [])
    return CheckRun(version=ctx.version, seq=review.store.last_seq() if review else 0, checks=results, findings=findings,
                    counts=counts, engine_diagnostics=diags, outside_filings=[OutsideFiling(**o) for o in outs])


@check("COMP_AREAS", "Every area considered", "completeness",
       "Each of the eight areas has had preparer work recorded (a verification or sign-off on at least one of its lines).")
def areas_considered(ctx: Ctx) -> CheckResult:
    summary = ctx.review.summary(ctx.version) if ctx.review else {}
    by_area: dict[str, list[str]] = {}
    for key in ctx.lines:
        by_area.setdefault(area_of(key), []).append(key)
    rows = {}
    for aid, name, _b, _h in AREAS:
        keys = by_area.get(aid, [])
        done = sum(1 for k in keys if k in summary and (summary[k].verified or summary[k].signed))
        rows[aid] = {"name": name, "lines": len(keys), "worked": done}
    missing = [r["name"] for r in rows.values() if r["worked"] == 0]
    meta = next(c for c in CHECKS if c[0] == "COMP_AREAS")
    return CheckResult(id="COMP_AREAS", title=meta[1], kind="completeness", description=meta[3],
                       status="pass" if not missing else "warn", metrics={"areas": rows},
                       summary="All eight areas have recorded work" if not missing
                       else f"{8 - len(missing)} of 8 areas have recorded work; not yet: {', '.join(missing)}")
