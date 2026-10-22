// One adjustment: the line changes (original preserved), who/why, the tax effect,
// the partner gate, and its history. Approve / reject / reverse are server-checked;
// a refusal is shown with the firm rule's own wording.
import { useState } from "react";
import { CheckCircle2, Gavel, RotateCcw, ShieldAlert, XCircle } from "lucide-react";
import { api, ApiError, type Adjustment } from "../../api/client";
import { useReviewWrite } from "../review/ReviewPanel";
import { TaxEffectView } from "../health/FindingCard";
import { LineChip } from "../trace/bits";
import { RefChip } from "../evidence";
import { Badge, Button, Callout } from "../../ui";
import { fmtDateTime, fmtValue } from "../../format";
import type { TaxEffect } from "../../api/client";

const STATUS = {
  pending_partner: { tone: "warning" as const, label: "Awaiting partner sign-off", icon: <ShieldAlert aria-hidden /> },
  active: { tone: "verified" as const, label: "Active", icon: <CheckCircle2 aria-hidden /> },
  rejected: { tone: "error" as const, label: "Rejected", icon: <XCircle aria-hidden /> },
  reversed: { tone: "neutral" as const, label: "Reversed", icon: <RotateCcw aria-hidden /> },
};

export function AdjustmentCard({ a, compact }: { a: Adjustment; compact?: boolean }) {
  const [note, setNote] = useState("");
  const act = useReviewWrite((kind: "approve" | "reject" | "reverse") => api.decideAdjustment(a.id, kind, note));
  const st = STATUS[a.status];
  return (
    <article className={`adj adj--${a.status}`}>
      <header className="adj__head">
        <span className="mono adj__id">{a.id}</span>
        <h3 className="adj__title">{a.title}</h3>
        <Badge tone={st.tone} icon={st.icon}>{st.label}</Badge>
        {a.requires_partner && <Badge tone="outline" icon={<Gavel aria-hidden />} title={`Tax effect over ${a.threshold.toLocaleString()} in a jurisdiction`}>partner rule</Badge>}
      </header>
      <p className="text-secondary text-sm">Proposed by {a.actor_name} · {fmtDateTime(a.at)}{a.approved_by && ` · approved by ${a.approved_by}`}</p>
      <p className="adj__reason">{a.reason}</p>
      <table className="mini adj__changes">
        <thead><tr><th>Line</th><th>Description</th><th className="num">Engine value</th><th className="num">Adjusted</th><th className="num">Change</th></tr></thead>
        <tbody>{a.changes.map((c) => {
          const from = c.from_value as number | null;
          const to = c.to_value as number;
          return (
            <tr key={String(c.key)}>
              <td><LineChip lineKey={String(c.key)} /></td>
              <td className="truncate" style={{ maxWidth: 360 }}>{String(c.label)}{c.new_line ? <> <Badge tone="open">new line</Badge></> : null}</td>
              <td className="num">{from == null ? "—" : <s className="text-tertiary">{fmtValue(from)}</s>}</td>
              <td className="num"><strong>{fmtValue(to)}</strong></td>
              <td className="num">{fmtValue(to - (from ?? 0))}</td>
            </tr>
          );
        })}</tbody>
      </table>
      {!compact && <TaxEffectView t={a.tax_effect as unknown as TaxEffect} />}
      {(a.finding_id || a.refs.length > 0) && !compact && (
        <div className="row-wrap">
          <span className="overline">Evidence</span>
          {a.finding_id && <Badge tone="outline">from finding {a.finding_id}</Badge>}
          {a.refs.slice(0, 8).map((r) => <RefChip key={r} refId={r} />)}
        </div>
      )}
      {!compact && a.history.length > 1 && (
        <ol className="adj__history">{a.history.map((h, i) => (
          <li key={i}><strong>{String(h.kind)}</strong> by {String(h.actor_name)} · {fmtDateTime(String(h.at))}{h.note ? ` — ${String(h.note)}` : ""}</li>
        ))}</ol>
      )}
      {(a.status === "pending_partner" || a.status === "active") && (
        <div className="finding__actions">
          <input className="ui-input review__input" placeholder={a.status === "pending_partner" ? "Partner's basis for the decision…" : "Why reverse it?"}
            value={note} onChange={(e) => setNote(e.target.value)} aria-label={`Note for ${a.id}`} />
          {a.status === "pending_partner" && <>
            <Button size="sm" variant="primary" icon={<Gavel aria-hidden />} disabled={act.isPending} onClick={() => act.mutate("approve")}>Approve (partner)</Button>
            <Button size="sm" variant="danger" disabled={act.isPending} onClick={() => act.mutate("reject")}>Reject</Button>
          </>}
          <Button size="sm" variant="ghost" icon={<RotateCcw aria-hidden />} disabled={act.isPending} onClick={() => act.mutate("reverse")}>
            {a.status === "pending_partner" ? "Withdraw" : "Reverse"}
          </Button>
        </div>
      )}
      {act.error && (
        <Callout tone={act.error instanceof ApiError && act.error.status === 409 ? "warning" : "error"}>
          Refused by the server: {act.error instanceof Error ? act.error.message : String(act.error)}
        </Callout>
      )}
    </article>
  );
}
