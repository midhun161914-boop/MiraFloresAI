import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRightCircle, CalendarDays, Lightbulb } from "lucide-react";
import { api } from "../api/client";
import type { CarryRow } from "../api/lifecycle";
import { useReviewWrite } from "../components/review/ReviewPanel";
import { Badge, Button, Callout, Card, ErrorState, PageHeader, PageSkeleton } from "../ui";
import { fmtAccounting, fmtDateTime } from "../format";

const n = (v: number | null | undefined) => (v == null ? "—" : fmtAccounting(v));

function Rows({ rows, history }: { rows: CarryRow[]; history: boolean }) {
  return (
    <table className="mini mini--wide">
      <thead><tr><th>Carryover</th><th className="num">Into 2025</th><th className="num">Used in 2025</th><th className="num">Out to 2026</th>{history && <th>History (v1 → v2 → v3)</th>}</tr></thead>
      <tbody>{rows.map((r) => (
        <tr key={r.key} className={!r.into_2025 && !r.out_2026 ? "text-tertiary" : ""}>
          <td>{r.label}</td><td className="num">{n(r.into_2025)}</td><td className="num">{r.used_2025 != null && r.used_2025 < 0 ? <span className="text-secondary">generated {fmtAccounting(-r.used_2025)}</span> : n(r.used_2025)}</td><td className="num"><strong>{n(r.out_2026)}</strong></td>
          {history && <td className="text-sm">{r.history?.map((h) => (h.value == null ? "—" : h.value.toLocaleString())).join(" → ")}
            {r.changes && r.changes.length > 0 && <div className="text-tertiary text-xs">{r.changes.join("; ")}</div>}</td>}
        </tr>
      ))}</tbody>
    </table>
  );
}

export function CarryForwardPage() {
  const q = useQuery({ queryKey: ["carryforward"], queryFn: api.carryforward });
  const [note, setNote] = useState("");
  const roll = useReviewWrite(() => api.rollForward(note));
  if (q.isPending) return <PageSkeleton label="Loading carryovers" />;
  if (q.isError) return <div className="page"><ErrorState error={q.error} /></div>;
  const c = q.data;
  const p = c.planning;
  return (
    <div className="page">
      <PageHeader title="Carry forward & 2026"
        meta={<span>From {c.sources.out}{c.filed ? " (the filed return)" : " — not filed yet"}; into-2025 from {c.sources.into_2025}.</span>}
        actions={c.rolled ? <Badge tone="verified">2026 file opened {fmtDateTime(c.rolled.at)}</Badge> : undefined} />
      <div className="stack-4">
        <Card title="Federal carryovers" flush><Rows rows={c.federal} history /></Card>
        <Card title="California carryovers" flush><Rows rows={c.california} history={false} /></Card>
        <Card title="2026 estimated payments" description={`Safe harbor on the filed 2025 tax (${p.basis}).`}>
          <div className="whatif-grid">
            {(["federal", "california"] as const).map((j) => {
              const e = p.estimates[j];
              return (
                <div key={j} className="stack-2">
                  <strong>{j === "federal" ? "Federal" : "California"} · 110% of {fmtAccounting(e.basis_2025_tax)} = {fmtAccounting(e.safe_harbor_total)}</strong>
                  <table className="mini"><tbody>{e.installments.map((i) => (
                    <tr key={i.due}><td><CalendarDays aria-hidden style={{ width: 14, height: 14, verticalAlign: -2 }} /> {i.due}</td><td className="num">{fmtAccounting(i.amount)}</td></tr>
                  ))}</tbody></table>
                  <p className="text-tertiary text-xs">{e.rule}</p>
                  {e.caveat && <Callout tone="warning">{e.caveat}</Callout>}
                </div>
              );
            })}
          </div>
        </Card>
        <Card title="Known 2026 changes for this household">
          <ul className="finding__facts">{p.known_changes.map((k) => <li key={k}><Lightbulb aria-hidden style={{ width: 14, height: 14, verticalAlign: -2 }} /> {k}</li>)}</ul>
        </Card>
        {!c.rolled && (
          <Card>
            <div className="finding__actions">
              <input className="ui-input review__input" placeholder="Note for the 2026 preparer…" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Roll-forward note" />
              <Button variant="primary" icon={<ArrowRightCircle aria-hidden />} disabled={roll.isPending} onClick={() => roll.mutate(undefined)}>Open the 2026 file with these carryovers</Button>
            </div>
            {roll.error && <Callout tone="error">Refused by the server: {roll.error.message}</Callout>}
          </Card>
        )}
      </div>
    </div>
  );
}
