import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FilePlus2, Scale, Snowflake, Trash2 } from "lucide-react";
import { api } from "../api/client";
import type { Amendment } from "../api/lifecycle";
import { RefChip } from "../components/evidence";
import { useReviewWrite } from "../components/review/ReviewPanel";
import { LineChip } from "../components/trace/bits";
import { Badge, Button, Callout, Card, EmptyState, ErrorState, PageHeader, PageSkeleton, Select } from "../ui";
import { fmtAccounting, fmtDateTime, fmtValue } from "../format";

function Refused({ error }: { error: unknown }) {
  return error ? <Callout tone="error">Refused by the server: {error instanceof Error ? error.message : String(error)}</Callout> : null;
}

function AmendmentCard({ a }: { a: Amendment }) {
  const checks = useQuery({ queryKey: ["checks"], queryFn: api.checks });
  const [key, setKey] = useState("");
  const [to, setTo] = useState("");
  const [reason, setReason] = useState("");
  const [finding, setFinding] = useState("");
  const [note, setNote] = useState("");
  const add = useReviewWrite(() => api.amendLine(a.id, key.trim(), Number(to.replace(/,/g, "")), reason));
  const fromF = useReviewWrite(() => api.amendFromFinding(a.id, finding, reason));
  const remove = useReviewWrite((k: string) => api.removeAmendLine(a.id, k));
  const approve = useReviewWrite(() => api.approveAmendment(a.id, note));
  const withFix = (checks.data?.findings ?? []).filter((f) => f.fix && !f.adjustment);
  const sign = (n: number) => `${n > 0 ? "+" : ""}${fmtAccounting(n)}`;
  return (
    <Card title={`${a.id} · amended return (1040-X / 540NR)`}
      actions={<Badge tone={a.status === "draft" ? "open" : "verified"}>{a.status}</Badge>}
      description={`Opened by ${a.actor_name} · ${fmtDateTime(a.at)} — ${a.reason}`}>
      <div className="stack-3">
        <p className="text-tertiary text-xs">Layered on the filed snapshot <span className="mono">{a.base_snapshot}</span> {a.intact_base ? "(intact — the filed record is unchanged)" : "(base changed!)"}.</p>
        {a.rows.length === 0 ? <EmptyState icon={<FilePlus2 />} title="No lines amended yet" /> : (
          <table className="mini mini--wide">
            <thead><tr><th>Line</th><th>Description</th><th className="num">A · As filed</th><th className="num">B · Net change</th><th className="num">C · Correct</th><th>Why</th><th className="num">Tax effect (fed / CA)</th><th></th></tr></thead>
            <tbody>{a.rows.map((r) => (
              <tr key={r.key}>
                <td><LineChip lineKey={r.key} /></td><td>{r.label}</td>
                <td className="num">{r.as_filed == null ? "—" : fmtValue(r.as_filed)}</td>
                <td className="num"><span className={r.net_change > 0 ? "up" : "down"}>{sign(r.net_change)}</span></td>
                <td className="num"><strong>{fmtValue(r.corrected)}</strong></td>
                <td className="cmp__why"><div>{r.reason}</div><span className="text-tertiary text-xs">{r.actor_name} · {fmtDateTime(r.at)}{r.finding_id ? ` · from ${r.finding_id}` : ""}</span>
                  {r.refs.length > 0 && <span className="jt-inline">{r.refs.slice(0, 4).map((x) => <RefChip key={x} refId={x} />)}</span>}</td>
                <td className="num nowrap">{sign(r.tax_effect.federal_balance_due)} / {sign(r.tax_effect.california_balance_due)}</td>
                <td>{a.status === "draft" && <Button size="sm" variant="ghost" icon={<Trash2 aria-hidden />} aria-label={`Remove ${r.key}`} onClick={() => remove.mutate(r.key)} />}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
        {a.rows.length > 0 && (
          <div className="estimate-banner" role="note"><strong>ESTIMATE</strong>
            <span>Net change in balance due: federal {sign(a.effect.federal_balance_due)}, California {sign(a.effect.california_balance_due)} — {a.effect.basis}.</span></div>
        )}
        {a.status === "draft" && <>
          <div className="review__form">
            <Select label="From finding" hideLabel value={finding} onChange={setFinding}
              options={[{ value: "", label: "Use a finding's computed fix…" }, ...withFix.map((f) => ({ value: f.id, label: f.title.slice(0, 70) }))]} />
            <span className="text-tertiary text-sm">or line</span>
            <input className="ui-input review__input--short" placeholder="Line, e.g. SchB.1.2" value={key} onChange={(e) => setKey(e.target.value)} aria-label="Line key" />
            <input className="ui-input review__input--short" placeholder="Correct amount" inputMode="decimal" value={to} onChange={(e) => setTo(e.target.value)} aria-label="Correct amount" />
          </div>
          <div className="finding__actions">
            <input className="ui-input review__input" placeholder="Why this line changes (goes on the 1040-X explanation)…" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Amendment reason" />
            <Button size="sm" variant="primary" icon={<Scale aria-hidden />} disabled={!reason.trim() || add.isPending || fromF.isPending || (!finding && (!key || !to))}
              onClick={() => (finding ? fromF.mutate(undefined, { onSuccess: () => { setFinding(""); setReason(""); } })
                : add.mutate(undefined, { onSuccess: () => { setKey(""); setTo(""); setReason(""); } }))}>Amend</Button>
          </div>
          <Refused error={add.error ?? fromF.error ?? remove.error} />
          {a.rows.length > 0 && (
            <div className="finding__actions">
              <input className="ui-input review__input" placeholder="Partner's basis for approving…" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Approval note" />
              <Button size="sm" disabled={!note.trim() || approve.isPending} onClick={() => approve.mutate(undefined)}>Approve (partner)</Button>
            </div>
          )}
          <Refused error={approve.error} />
        </>}
        <ol className="adj__history">{a.history.map((h) => <li key={h.seq}>{fmtDateTime(h.at)} · {h.actor_name} · {h.kind}{h.note ? ` — ${h.note}` : ""}</li>)}</ol>
      </div>
    </Card>
  );
}

/** Amendments sit on top of the frozen filed return; they never edit it. */
export function AmendPage() {
  const filing = useQuery({ queryKey: ["filing"], queryFn: api.filing });
  const q = useQuery({ queryKey: ["amendments"], queryFn: api.amendments });
  const [reason, setReason] = useState("");
  const open = useReviewWrite(() => api.openAmendment(reason));
  if (q.isPending || filing.isPending) return <PageSkeleton label="Loading amendments" />;
  if (q.isError) return <div className="page"><ErrorState error={q.error} /></div>;
  const filed = !!filing.data?.filed;
  const hasDraft = q.data.some((a) => a.status !== "filed");
  return (
    <div className="page">
      <PageHeader title="Amendments" meta={<span>Changes after filing. The filed record stays frozen; each amendment shows as filed → net change → correct, with why.</span>} />
      {!filed ? <Card><EmptyState icon={<Snowflake />} title="Nothing filed yet" description="Before filing, change the return with an adjustment instead." /></Card> : (
        <div className="stack-4">
          {!hasDraft && (
            <Card>
              <div className="finding__actions">
                <input className="ui-input review__input" placeholder="Why is the return being amended?" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Amendment reason" />
                <Button variant="primary" icon={<FilePlus2 aria-hidden />} disabled={!reason.trim() || open.isPending} onClick={() => open.mutate(undefined)}>Open amendment</Button>
              </div>
              <Refused error={open.error} />
            </Card>
          )}
          {q.data.map((a) => <AmendmentCard key={a.id} a={a} />)}
        </div>
      )}
    </div>
  );
}
