// One check finding: what the check computed, the evidence, the lines it touches
// (each opens its trace), the tax effect, and what was decided about it.
import { useState } from "react";
import { AlertOctagon, AlertTriangle, Bot, BotOff, CheckCircle2, Info, RotateCcw, Scale } from "lucide-react";
import { Link } from "react-router-dom";
import { api, ApiError, type Finding, type TaxEffect } from "../../api/client";
import { useReviewWrite } from "../review/ReviewPanel";
import { Badge, Button, Callout } from "../../ui";
import { fmtDateTime, fmtValue } from "../../format";
import { RefChip } from "../evidence";
import { LineChip } from "../trace/bits";

const SEV = {
  error: { tone: "error" as const, icon: <AlertOctagon aria-hidden />, label: "Error" },
  warning: { tone: "warning" as const, icon: <AlertTriangle aria-hidden />, label: "Warning" },
  info: { tone: "neutral" as const, icon: <Info aria-hidden />, label: "Info" },
};

export const AREA_NAME: Record<string, string> = {
  wages: "Wages & stock comp", investments: "Investments & digital assets", business: "Business",
  rentals: "Rentals & sale", pass_throughs: "Pass-throughs & basis", deductions: "Deductions & credits",
  california: "California", payments: "Payments", totals: "Return totals",
};

const signed = (n: number) => (n === 0 ? "0" : `${n > 0 ? "+" : "−"}${Math.abs(n).toLocaleString("en-US")}`);

export function TaxEffectView({ t }: { t: TaxEffect }) {
  const payments = t.category === "payment" || t.category === "ca_payment";
  return (
    <div className="taxfx">
      <div className="taxfx__head">
        <span className="overline">{t.bound === "upper_bound" ? "Tax at stake (upper bound)" : "Tax effect"}</span>
        <span className="text-tertiary text-xs">{payments ? "balance due" : "tax"}, via the packet's tax_effect_rates</span>
      </div>
      <div className="taxfx__grid">
        <div><span className="taxfx__label">Federal</span><span className={`taxfx__num${t.federal_balance_due > 0 ? " up" : t.federal_balance_due < 0 ? " down" : ""}`}>{signed(t.federal_balance_due)}</span></div>
        <div><span className="taxfx__label">California</span><span className={`taxfx__num${t.california_balance_due > 0 ? " up" : t.california_balance_due < 0 ? " down" : ""}`}>{signed(t.california_balance_due)}</span></div>
        <div><span className="taxfx__label">{payments ? "Payment change" : "Income change"}</span><span className="taxfx__num">{signed(t.change)}</span></div>
      </div>
      <p className="taxfx__basis">{t.basis}</p>
    </div>
  );
}

/** A finding's computed fix → a proposed adjustment that carries its evidence and tax effect. */
function ProposeFix({ f }: { f: Finding }) {
  const [reason, setReason] = useState("");
  const propose = useReviewWrite(() => api.adjustFromFinding(f.id, reason));
  if (!f.fix) return null;
  return (
    <div className="fix">
      <div className="fix__head"><Scale aria-hidden /><strong>Computed fix</strong><span className="text-secondary">{f.fix.description}</span></div>
      <table className="mini">
        <thead><tr><th>Line</th><th className="num">Engine</th><th className="num">Fixed</th></tr></thead>
        <tbody>{f.fix.changes.map((c) => (
          <tr key={c.key}><td><LineChip lineKey={c.key} />{c.new_line && <> <Badge tone="open">new line</Badge></>}</td>
            <td className="num">{c.from_value == null ? "—" : fmtValue(c.from_value)}</td><td className="num"><strong>{fmtValue(c.to_value)}</strong></td></tr>
        ))}</tbody>
      </table>
      {f.adjustment ? (
        <Callout tone="open">
          <Link to="/adjustments">{String(f.adjustment.id)}</Link> {String(f.adjustment.status) === "active" ? "is active" : "awaits partner sign-off"} — {String(f.adjustment.title)}
        </Callout>
      ) : (
        <div className="finding__actions">
          <input className="ui-input review__input" placeholder="Reason for the adjustment (carried into the workpaper)…" value={reason}
            onChange={(e) => setReason(e.target.value)} aria-label={`Adjustment reason for ${f.code}`} />
          <Button size="sm" variant="primary" icon={<Scale aria-hidden />} disabled={!reason.trim() || propose.isPending}
            onClick={() => propose.mutate(undefined, { onSuccess: () => setReason("") })}>Propose adjustment</Button>
        </div>
      )}
      {propose.error && <Callout tone="error">Refused by the server: {propose.error instanceof Error ? propose.error.message : String(propose.error)}</Callout>}
      {propose.data && <Callout tone={propose.data.status === "active" ? "neutral" : "warning"}>
        {propose.data.id} {propose.data.status === "active" ? "applied" : `proposed — tax effect over ${propose.data.threshold.toLocaleString()}, so it awaits partner sign-off`}.
      </Callout>}
    </div>
  );
}

export function FindingCard({ f, defaultOpen = false, select }: {
  f: Finding; defaultOpen?: boolean; select?: { checked: boolean; onToggle: () => void };
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [note, setNote] = useState("");
  const act = useReviewWrite((d: "resolved" | "accepted" | "not_an_issue" | "reopened") => api.disposition(f.id, d, note));
  const s = SEV[f.severity];
  const closed = f.status !== "open";
  return (
    <article className={`finding finding--${f.severity}${closed ? " finding--closed" : ""}`} aria-labelledby={`f-${f.id}`}>
      <header className="finding__head">
        {select && <input type="checkbox" className="finding__check" checked={select.checked} onChange={select.onToggle}
          aria-label={`Select finding ${f.code}`} />}
        <Badge tone={s.tone} icon={s.icon}>{s.label}</Badge>
        <h3 id={`f-${f.id}`} className="finding__title">
          <button type="button" className="finding__toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>{f.title}</button>
        </h3>
        {closed && <Badge tone={f.status === "not_an_issue" ? "neutral" : f.status === "adjustment_pending" ? "warning" : "verified"} icon={<CheckCircle2 aria-hidden />}>{f.status.replace(/_/g, " ")}</Badge>}
        {f.severity !== "info" && (f.engine_diagnostic
          ? <Badge tone="outline" icon={<Bot aria-hidden />} title={`The engine's own diagnostic ${f.engine_diagnostic} also flags this`}>engine agrees</Badge>
          : <Badge tone="accent" icon={<BotOff aria-hidden />} title="The engine raised no diagnostic for this">engine missed</Badge>)}
      </header>
      <div className="finding__meta">
        <span className="mono">{f.code}</span><span>{AREA_NAME[f.area] ?? f.area}</span><span className="mono text-tertiary">{f.check_id}</span>
        {f.tax_effect && !open && (
          <span className="finding__fx">federal {signed(f.tax_effect.federal_balance_due)} · CA {signed(f.tax_effect.california_balance_due)}{f.tax_effect.bound === "upper_bound" ? " (up to)" : ""}</span>
        )}
      </div>
      <p className="finding__summary">{f.summary}</p>
      {open && (
        <div className="finding__body stack-3">
          {f.facts.length > 0 && <ul className="finding__facts">{f.facts.map((x, i) => <li key={i}>{x}</li>)}</ul>}
          {f.tax_effect && <TaxEffectView t={f.tax_effect} />}
          {f.fix && <ProposeFix f={f} />}
          {f.lines.length > 0 && <div className="row-wrap"><span className="overline">Lines</span>{f.lines.map((k) => <LineChip key={k} lineKey={k} />)}</div>}
          {f.refs.length > 0 && <div className="row-wrap"><span className="overline">Evidence</span>{f.refs.filter(Boolean).map((r) => <RefChip key={r} refId={r} />)}</div>}
          {f.disposition && (
            <Callout tone="neutral">
              <strong>{String(f.disposition.disposition).replace(/_/g, " ")}</strong> by {String(f.disposition.actor_name)} · {fmtDateTime(String(f.disposition.at))}: {String(f.disposition.note)}
            </Callout>
          )}
          {f.check_id !== "RECON_W2" && f.code !== "INPUTS_INCOMPLETE" && (
            <div className="finding__actions">
              {f.status === "open" ? <>
                <input className="ui-input review__input" placeholder="Decision and why (becomes workpaper evidence)…" value={note}
                  onChange={(e) => setNote(e.target.value)} aria-label={`Disposition note for ${f.code}`} />
                <Button size="sm" variant="primary" disabled={!note.trim() || act.isPending} onClick={() => act.mutate("resolved")}>Resolved</Button>
                <Button size="sm" disabled={!note.trim() || act.isPending} onClick={() => act.mutate("accepted")} title="Agreed; the fix follows as an adjustment">Accept</Button>
                <Button size="sm" variant="ghost" disabled={!note.trim() || act.isPending} onClick={() => act.mutate("not_an_issue")}>Not an issue</Button>
              </> : (
                <Button size="sm" variant="ghost" icon={<RotateCcw aria-hidden />} disabled={act.isPending} onClick={() => act.mutate("reopened")}>Reopen</Button>
              )}
            </div>
          )}
          {act.error && <Callout tone={act.error instanceof ApiError && act.error.status === 409 ? "warning" : "error"}>Refused by the server: {act.error instanceof Error ? act.error.message : String(act.error)}</Callout>}
        </div>
      )}
    </article>
  );
}
