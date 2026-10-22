import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Calculator, Cpu, Plus, Trash2 } from "lucide-react";
import { api, type EstimateItem } from "../api/client";
import { LineChip } from "../components/trace/bits";
import { Badge, Button, Callout, Card, ErrorState, PageHeader, PageSkeleton, Select } from "../ui";
import { fmtAccounting, fmtValue } from "../format";

const CATEGORIES = ["wages", "interest", "schc_profit", "stcg", "ltcg", "ordinary_income", "adjustment", "salt", "itemized", "ca_source_income"];

type Row = { mode: "category" | "line"; category: string; line: string; change: string; label: string };

function money(v: unknown) { return typeof v === "number" ? fmtAccounting(v) : "—"; }

/** Scripted what-ifs are engine results. Ad-hoc ones are estimates — and say so. */
export function WhatIfPage() {
  const q = useQuery({ queryKey: ["whatif"], queryFn: api.whatif, staleTime: Infinity });
  const [rows, setRows] = useState<Row[]>([{ mode: "category", category: "ltcg", line: "", change: "-10000", label: "Harvest 10k of long-term losses" }]);
  const est = useMutation({ mutationFn: (items: EstimateItem[]) => api.estimate(items) });
  const upd = (i: number, patch: Partial<Row>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  if (q.isPending) return <PageSkeleton label="Loading what-ifs" />;
  if (q.isError) return <div className="page"><ErrorState error={q.error} /></div>;
  const run = () => est.mutate(rows.filter((r) => r.change.trim()).map((r) => ({
    category: r.mode === "category" ? r.category : undefined, line: r.mode === "line" ? r.line.trim() : undefined,
    change: Number(r.change.replace(/,/g, "")), label: r.label || undefined,
  })));
  const e = est.data;

  return (
    <div className="page">
      <PageHeader title="What-ifs" meta={<span>Five scripted alternatives the engine actually computed, and an estimator for anything else.</span>} />

      <h2 className="section-title"><Cpu aria-hidden /> Engine-computed alternatives</h2>
      <div className="whatif-grid">
        {q.data.alternatives.map((alt) => {
          const fed = alt.federal as Record<string, unknown>, ca = alt.california as Record<string, unknown>;
          const fb = fed.base as Record<string, number>, fa = fed.alternative as Record<string, number>;
          const cb = ca.base as Record<string, number>, caa = ca.alternative as Record<string, number>;
          const lines = alt.changed_lines as { key: string; label: string; old: number; new: number }[];
          return (
            <Card key={String(alt.id)} title={String(alt.description)} actions={<Badge tone="verified" icon={<Cpu aria-hidden />}>Engine result</Badge>}>
              <div className="stack-3">
                <p className="text-tertiary text-sm">Base {String(alt.base_version)} · choices: {Object.entries(alt.choices as Record<string, unknown>).map(([k, v]) => `${k} = ${String(v)}`).join(", ")}</p>
                <table className="mini">
                  <thead><tr><th></th><th className="num">Base</th><th className="num">Alternative</th><th className="num">Change</th></tr></thead>
                  <tbody>
                    <tr><td>Federal total tax</td><td className="num">{money(fb.total_tax)}</td><td className="num">{money(fa.total_tax)}</td><td className="num"><strong>{money(fed.total_tax_change)}</strong></td></tr>
                    <tr><td>Federal penalty</td><td className="num">{money(fb.penalty)}</td><td className="num">{money(fa.penalty)}</td><td className="num">{money(fed.penalty_change)}</td></tr>
                    <tr><td>California total tax</td><td className="num">{money(cb.total_tax)}</td><td className="num">{money(caa.total_tax)}</td><td className="num"><strong>{money(ca.total_tax_change)}</strong></td></tr>
                  </tbody>
                </table>
                {lines.length > 0 && (
                  <details>
                    <summary className="text-sm" style={{ cursor: "pointer", color: "var(--accent-text)" }}>{lines.length} lines change</summary>
                    <table className="mini" style={{ marginTop: 8 }}><tbody>{lines.slice(0, 40).map((l) => (
                      <tr key={l.key}><td><LineChip lineKey={l.key} /></td><td className="truncate" style={{ maxWidth: 220 }}>{l.label}</td>
                        <td className="num">{fmtValue(l.old)}</td><td className="num">→ {fmtValue(l.new)}</td></tr>
                    ))}</tbody></table>
                  </details>
                )}
              </div>
            </Card>
          );
        })}
      </div>

      <h2 className="section-title" style={{ marginTop: 32 }}><Calculator aria-hidden /> Ad-hoc estimate</h2>
      <Card>
        <div className="stack-3">
          <div className="estimate-banner" role="note">
            <strong>ESTIMATE</strong>
            <span>Not an engine recompute. Each change × this version's <span className="mono">tax_effect_rates</span> — a linear, per-dollar approximation. Large changes can cross thresholds the rates don't capture.</span>
          </div>
          {rows.map((r, i) => (
            <div key={i} className="review__form">
              <Select label="By" hideLabel value={r.mode} onChange={(v) => upd(i, { mode: v as Row["mode"] })}
                options={[{ value: "category", label: "Category" }, { value: "line", label: "Return line" }]} />
              {r.mode === "category"
                ? <Select label="Category" hideLabel value={r.category} onChange={(v) => upd(i, { category: v })} options={CATEGORIES.map((c) => ({ value: c, label: c }))} />
                : <input className="ui-input review__input--short" placeholder="e.g. SchB.1.2" value={r.line} onChange={(e) => upd(i, { line: e.target.value })} aria-label="Line key" />}
              <input className="ui-input review__input--short" placeholder="Change (+/−)" inputMode="decimal" value={r.change} onChange={(e) => upd(i, { change: e.target.value })} aria-label="Change amount" />
              <input className="ui-input review__input" placeholder="What is this?" value={r.label} onChange={(e) => upd(i, { label: e.target.value })} aria-label="Scenario label" />
              <Button variant="ghost" size="sm" icon={<Trash2 aria-hidden />} aria-label="Remove row" onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))} />
            </div>
          ))}
          <div className="row">
            <Button size="sm" icon={<Plus aria-hidden />} onClick={() => setRows((rs) => [...rs, { mode: "category", category: "ltcg", line: "", change: "", label: "" }])}>Add a change</Button>
            <span className="spacer" />
            <Button variant="primary" icon={<Calculator aria-hidden />} disabled={est.isPending} onClick={run}>Estimate</Button>
          </div>
          {est.error && <Callout tone="error">{est.error instanceof Error ? est.error.message : String(est.error)}</Callout>}
          {e && (
            <div className="estimate">
              <div className="estimate__head"><Badge tone="warning">{e.kind}</Badge><span className="text-secondary text-sm">{e.disclaimer}</span></div>
              <table className="mini">
                <thead><tr><th></th><th className="num">{e.version} engine</th><th className="num">Estimated</th><th className="num">Change</th></tr></thead>
                <tbody>
                  <tr><td>Federal total tax</td><td className="num">{money(e.base.federal_total_tax)}</td><td className="num">≈ {money(e.estimated.federal_total_tax)}</td><td className="num"><strong>{money(e.federal_tax)}</strong></td></tr>
                  <tr><td>Federal balance due</td><td className="num">{money(e.base.federal_balance_due)}</td><td className="num">≈ {money(e.estimated.federal_balance_due)}</td><td className="num">{money(e.federal_balance_due)}</td></tr>
                  <tr><td>California total tax</td><td className="num">{money(e.base.california_total_tax)}</td><td className="num">≈ {money(e.estimated.california_total_tax)}</td><td className="num"><strong>{money(e.california_tax)}</strong></td></tr>
                </tbody>
              </table>
              <ul className="finding__facts">{e.items.map((it, i) => <li key={i} className="text-sm">{String(it.basis)}</li>)}</ul>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
