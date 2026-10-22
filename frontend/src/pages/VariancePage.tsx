import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { CheckCircle2, TrendingUp } from "lucide-react";
import { api, type VarianceFlag } from "../api/client";
import { AREA_NAME } from "../components/health/FindingCard";
import { useReviewWrite } from "../components/review/ReviewPanel";
import { LineChip } from "../components/trace/bits";
import { Badge, Button, Card, EmptyState, ErrorState, FilterGroup, PageHeader, PageSkeleton, Select } from "../ui";
import { fmtAccounting, fmtDateTime } from "../format";

function Explain({ f }: { f: VarianceFlag }) {
  const [text, setText] = useState("");
  const [editing, setEditing] = useState(false);
  const save = useReviewWrite(() => api.explainVariance(f.line, text));
  if (f.explanation && !editing) {
    const e = f.explanation as unknown as { text: string; actor_name: string; at: string };
    return (
      <div className="explain">
        <CheckCircle2 aria-hidden className="explain__ok" />
        <span>{e.text}</span>
        <span className="text-tertiary text-xs">{e.actor_name} · {fmtDateTime(e.at)}</span>
        <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>Revise</Button>
      </div>
    );
  }
  return (
    <div className="explain">
      <input className="ui-input review__input" value={text} onChange={(e) => setText(e.target.value)} placeholder="Why did this change from 2024?"
        aria-label={`Explain the change in ${f.line}`} onKeyDown={(e) => { if (e.key === "Enter" && text.trim()) save.mutate(undefined, { onSuccess: () => { setText(""); setEditing(false); } }); }} />
      <Button size="sm" disabled={!text.trim() || save.isPending} onClick={() => save.mutate(undefined, { onSuccess: () => { setText(""); setEditing(false); } })}>Explain</Button>
      {save.error && <span className="text-sm" style={{ color: "var(--error-fg)" }}>{save.error instanceof Error ? save.error.message : "Failed"}</span>}
    </div>
  );
}

/** Firm rule: flag a line when it moves more than X% AND more than $Y versus the prior year. */
export function VariancePage() {
  const [params, setParams] = useSearchParams();
  const area = params.get("area") ?? "";
  const show = params.get("show") ?? "unexplained";
  const q = useQuery({ queryKey: ["variance"], queryFn: api.variance });
  const rows = useMemo(() => (q.data?.flags ?? []).filter((f) => (!area || f.area === area) && (show === "all" || !f.explanation)), [q.data, area, show]);
  const set = (k: string, v: string) => { const n = new URLSearchParams(params); if (v) n.set(k, v); else n.delete(k); setParams(n, { replace: true }); };

  if (q.isPending) return <PageSkeleton label="Comparing to 2024" />;
  if (q.isError) return <div className="page"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>;
  const r = q.data;
  const explained = r.flags.filter((f) => f.explanation).length;
  return (
    <div className="page">
      <PageHeader title="Variance vs 2024"
        meta={<span>Firm rule (<span className="mono">variance_review</span>): flag when a line changes by more than <strong>{r.rule.flag_if_change_over_percent as number}%</strong> and more than <strong>${(r.rule.and_over_amount as number).toLocaleString()}</strong>. {r.compared} lines have a 2024 counterpart; {r.flags.length} breach the rule; {explained} explained.</span>} />
      <div className="toolbar">
        <FilterGroup label="Show" selected={[show]} onToggle={(id) => set("show", id === "unexplained" ? "" : id)}
          items={[{ id: "unexplained", label: "Unexplained", count: r.flags.length - explained }, { id: "all", label: "All flags", count: r.flags.length }]} />
        <Select label="Area" value={area} onChange={(v) => set("area", v)}
          options={[{ value: "", label: "All areas" }, ...Object.entries(AREA_NAME).map(([value, label]) => ({ value, label }))]} />
      </div>
      <Card flush>
        {rows.length === 0 ? <EmptyState icon={<CheckCircle2 />} title="Every flagged variance is explained" /> : (
          <table className="mini mini--wide variance">
            <thead><tr><th>Line</th><th>Description</th><th>Area</th><th className="num">2024</th><th className="num">2025</th><th className="num">Change</th><th className="num">%</th><th>Explanation</th></tr></thead>
            <tbody>{rows.map((f) => (
              <tr key={f.line}>
                <td><LineChip lineKey={f.line} /></td>
                <td>{f.label}</td>
                <td className="text-secondary nowrap">{AREA_NAME[f.area] ?? f.area}</td>
                <td className="num">{fmtAccounting(f.prior)}</td>
                <td className="num">{fmtAccounting(f.current)}</td>
                <td className="num"><span className={f.delta > 0 ? "up" : "down"}>{f.delta > 0 ? "+" : ""}{fmtAccounting(f.delta)}</span></td>
                <td className="num">{f.pct == null ? <Badge tone="neutral">from 0</Badge> : <Badge tone={Math.abs(f.pct) > 50 ? "error" : "warning"} icon={<TrendingUp aria-hidden />}>{f.pct > 0 ? "+" : ""}{f.pct}%</Badge>}</td>
                <td className="variance__explain"><Explain f={f} /></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
