import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileStack, Mail, Printer, Send } from "lucide-react";
import { api } from "../api/client";
import type { LineRec, Notice, NoticeItem, NoticeResponse } from "../api/lifecycle";
import { RefChip } from "../components/evidence";
import { methodLabel, useReviewWrite } from "../components/review/ReviewPanel";
import { LineChip } from "../components/trace/bits";
import { Badge, Button, Callout, Card, ErrorState, PageHeader, PageSkeleton } from "../ui";
import { fmtAccounting, fmtDate, fmtDateTime, fmtValue } from "../format";

function LineBlock({ l }: { l: LineRec }) {
  return (
    <div className="nr-line">
      <div className="row"><LineChip lineKey={l.key} /><strong>{l.label}</strong><span className="spacer" />
        <span className="text-secondary">as filed</span><strong className="num">{fmtValue(l.as_filed)}</strong></div>
      {l.adjustments.map((a) => <p key={a.id} className="text-sm text-secondary">Adjusted by {a.id}: {a.reason} (approved by {a.approved_by ?? "—"})</p>)}
      {(l.verifications.length > 0 || l.signoffs.length > 0) && (
        <p className="text-sm">{l.verifications.map((v) => `Verified — ${methodLabel(v.method)} by ${v.actor_name}, ${fmtDate(v.at)}`).join("; ")}
          {l.signoffs.filter((s) => s.status === "active").map((s) => ` · ${s.level} sign-off ${s.actor_name}`).join("")}</p>
      )}
      <table className="mini mini--wide">
        <thead><tr><th>Document</th><th>Page</th><th>Field</th><th>As printed</th><th className="num">Value</th><th>Verification</th></tr></thead>
        <tbody>{l.evidence.filter((e) => e.direct || l.evidence.length <= 12).map((e) => (
          <tr key={e.ev}>
            <td><span className="jt-inline"><RefChip refId={e.document_id} /></span> {e.document}</td>
            <td className="num">{e.page}</td><td>{e.label}</td><td className="mono text-sm">{e.text_as_read}</td>
            <td className="num">{fmtValue(e.effective ?? e.value)}</td>
            <td className="text-sm">{e.verifications.length ? e.verifications.map((v) => `${methodLabel(v.method)} · ${v.actor_name}`).join("; ") : <span className="text-tertiary">none recorded</span>}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function ItemBlock({ it }: { it: NoticeItem }) {
  const r = it.reconciliation;
  return (
    <section className="nr-item">
      <h3 className="nr-item__q"><span className="mono">Item {it.index + 1}.</span> {it.question}</h3>
      {r && (
        <div className="stack-2">
          <table className="mini">
            <tbody>
              {r.bridge.map((x) => <tr key={x.label}><td>{x.label}</td><td className="num">{fmtAccounting(x.amount)}</td></tr>)}
              <tr><td><strong>Schedule C line 1 as filed</strong></td><td className="num"><strong>{fmtAccounting(r.reported)}</strong></td></tr>
            </tbody>
          </table>
          <p className="text-sm text-secondary">The firm's file holds the same third-party forms the IRS cites ({r.file_agrees_with_irs ? "1099-NEC and 1099-K agree to the letter" : "they differ from the letter — see documents"}); books revenue per the P&L is {fmtAccounting(r.books_revenue)}. Engine rule: {r.engine_rule}</p>
          {r.observation && <Callout tone="warning">Before sending: {r.observation}</Callout>}
        </div>
      )}
      {it.lines.map((l) => <LineBlock key={l.key} l={l} />)}
      <p className="text-sm"><strong>Enclosures:</strong> {it.documents.map((d) => `${d.id} ${d.title} (${d.pages} p.)`).join("; ")}</p>
      {it.gaps.map((g) => <Callout key={g} tone="warning">Gap before sending: {g}</Callout>)}
    </section>
  );
}

function ResponseRecord({ r }: { r: NoticeResponse }) {
  const rec = r.record;
  const [note, setNote] = useState("");
  const sent = useReviewWrite(() => api.responseSent(r.notice_id, note));
  return (
    <Card title={`Response record · ${rec.notice.type}`} className="nr"
      actions={<Button size="sm" icon={<Printer aria-hidden />} onClick={() => window.print()}>Print</Button>}>
      <div className="stack-4">
        <div className="nr-head">
          <div><strong>{rec.firm.name}</strong><div className="text-secondary text-sm">{rec.firm.address}</div></div>
          <div className="text-sm">Re: {rec.household} · tax year {rec.tax_year}<br />Notice dated {rec.notice.dated} · response due {rec.notice.response_due}</div>
        </div>
        <p className="text-sm text-secondary">Return as filed: accepted {rec.filed.accepted_at.slice(0, 10)}, submission {rec.filed.submissions.federal}; filed snapshot <span className="mono">{rec.filed.snapshot_hash}</span>. Assembled by {rec.assembled_by} from the workpaper at event #{r.as_of_seq} · record <span className="mono">{r.record_hash}</span>.</p>
        {rec.items.map((it) => <ItemBlock key={it.index} it={it} />)}
        {r.sent ? <Callout tone="neutral">Sent by {r.sent.actor_name} · {fmtDateTime(r.sent.at)}: {r.sent.note}</Callout> : (
          <div className="finding__actions no-print">
            <input className="ui-input review__input" placeholder="How it was sent (fax / portal / mail)…" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Sent note" />
            <Button size="sm" icon={<Send aria-hidden />} disabled={!note.trim() || sent.isPending} onClick={() => sent.mutate(undefined)}>Mark sent (partner)</Button>
          </div>
        )}
        {sent.error && <Callout tone="error">Refused by the server: {sent.error.message}</Callout>}
      </div>
    </Card>
  );
}

function NoticeCard({ n }: { n: Notice }) {
  const assemble = useReviewWrite(() => api.assembleResponse(n.id));
  return (
    <Card title={`${n.agency} ${n.type} · ${n.tax_year}`} actions={n.response ? <Badge tone="verified">Response assembled</Badge> : n.status ? <Badge tone="neutral">Resolved</Badge> : <Badge tone="warning">Open · due {n.response_due}</Badge>}
      description={`Dated ${n.dated}${n.response_due ? ` · respond by ${n.response_due}` : ""}`}>
      <div className="stack-3">
        <div className="row"><RefChip refId={n.document} />{n.summary && <span className="text-secondary">{n.summary}</span>}</div>
        {n.status && <p className="text-sm">{n.status}</p>}
        {n.items_under_examination && <ol className="finding__facts">{n.items_under_examination.map((q) => <li key={q}>{q}</li>)}</ol>}
        {n.items_under_examination && (
          <div className="row no-print">
            <Button variant="primary" icon={<FileStack aria-hidden />} disabled={assemble.isPending} onClick={() => assemble.mutate(undefined)}>
              {n.response ? "Re-assemble from the current workpaper" : "Assemble response from the workpaper"}
            </Button>
            <span className="text-tertiary text-sm">Self-contained: lines as filed, their source documents and pages, and the verifications.</span>
          </div>
        )}
        {assemble.error && <Callout tone="error">Refused by the server: {assemble.error.message}</Callout>}
      </div>
    </Card>
  );
}

export function NoticesPage() {
  const q = useQuery({ queryKey: ["notices"], queryFn: api.notices });
  if (q.isPending) return <PageSkeleton label="Loading notices" />;
  if (q.isError) return <div className="page"><ErrorState error={q.error} /></div>;
  return (
    <div className="page">
      <PageHeader title="Agency notices" meta={<span><Mail aria-hidden style={{ width: 14, height: 14, verticalAlign: -2 }} /> From tax_agency_records.notices.</span>} />
      <div className="stack-4">
        {q.data.map((n) => <div key={n.id} className="stack-4"><NoticeCard n={n} />{n.response && <ResponseRecord r={n.response} />}</div>)}
      </div>
    </div>
  );
}
