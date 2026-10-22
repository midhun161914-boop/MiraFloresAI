import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertOctagon, BadgeCheck, CalendarClock, CheckCircle2, Circle, FileSignature, Lock, Send, ShieldAlert, Snowflake, Wrench, XCircle,
} from "lucide-react";
import { api } from "../api/client";
import type { Figures, Filing, Submission } from "../api/lifecycle";
import { RefChip } from "../components/evidence";
import { ReturnSignoff } from "../components/review/ReturnSignoff";
import { useReviewWrite } from "../components/review/ReviewPanel";
import { useSession } from "../session";
import { Badge, Button, Callout, Card, ErrorState, PageHeader, PageSkeleton } from "../ui";
import { fmtAccounting, fmtDateTime } from "../format";

const STAGES = [
  { id: "preparing", label: "Pre-file gate" },
  { id: "presented", label: "Client approval" },
  { id: "authorized", label: "8879 signed" },
  { id: "transmitted", label: "E-file" },
  { id: "filed", label: "Filed & frozen" },
] as const;

function Refused({ error }: { error: unknown }) {
  if (!error) return null;
  return <Callout tone="error">Refused by the server: {error instanceof Error ? error.message : String(error)}</Callout>;
}

export function FiguresTable({ f, caption }: { f: Figures; caption?: string }) {
  const due = (n: number) => (n < 0 ? <span className="down">refund {fmtAccounting(-n)}</span> : <span className={n > 0 ? "up" : ""}>{fmtAccounting(n)}</span>);
  return (
    <div className="stack-2">
      <table className="mini mini--wide">
        <thead><tr><th></th><th className="num">AGI</th><th className="num">Total tax</th><th className="num">Payments</th><th className="num">Balance due</th></tr></thead>
        <tbody>
          <tr><td>Federal (Form 1040)</td><td className="num">{fmtAccounting(f.federal.agi)}</td><td className="num">{fmtAccounting(f.federal.total_tax)}</td>
            <td className="num">{fmtAccounting(f.federal.payments)}</td><td className="num"><strong>{due(f.federal.balance_due)}</strong></td></tr>
          <tr><td>California (540NR)</td><td className="num">{fmtAccounting(f.california.agi)}</td><td className="num">{fmtAccounting(f.california.total_tax)}</td>
            <td className="num">{fmtAccounting(f.california.payments)}</td><td className="num"><strong>{due(f.california.balance_due)}</strong></td></tr>
        </tbody>
      </table>
      <p className="text-tertiary text-xs">{caption ?? f.basis}</p>
    </div>
  );
}

function Stepper({ stage }: { stage: Filing["stage"] }) {
  const at = STAGES.findIndex((s) => s.id === stage);
  return (
    <ol className="stepper" aria-label="Filing progress">
      {STAGES.map((s, i) => (
        <li key={s.id} className={`stepper__step${i < at ? " is-done" : i === at ? " is-current" : ""}`} aria-current={i === at ? "step" : undefined}>
          <span className="stepper__dot">{i < at ? <CheckCircle2 aria-hidden /> : i + 1}</span>{s.label}
        </li>
      ))}
    </ol>
  );
}

function ExtensionCard() {
  const q = useQuery({ queryKey: ["extension"], queryFn: api.extension });
  const [note, setNote] = useState("Form 4868 with 36,000 and FTB 3519 with 0 (from what_if.extension, v2).");
  const file = useReviewWrite(() => api.fileExtension(note));
  if (!q.data) return null;
  const x = q.data;
  return (
    <Card title="Extension" actions={x.filed ? <Badge tone="verified" icon={<CheckCircle2 aria-hidden />}>Filed</Badge> : <Badge tone="open">Not recorded</Badge>}
      description={`Estimated from ${x.based_on_version} on ${x.computed_at.slice(0, 10)} · extended due ${x.extended_due ?? "—"}`}>
      <div className="stack-3">
        <table className="mini">
          <thead><tr><th></th><th className="num">Est. tax</th><th className="num">Payments</th><th className="num">Balance</th><th className="num">Paid with extension</th></tr></thead>
          <tbody>
            <tr><td>Federal · Form 4868</td><td className="num">{fmtAccounting(x.federal.estimated_total_tax)}</td><td className="num">{fmtAccounting(x.federal.payments)}</td>
              <td className="num">{fmtAccounting(x.federal.estimated_balance)}</td><td className="num"><strong>{fmtAccounting(x.federal.paid_with_form_4868)}</strong></td></tr>
            <tr><td>California · FTB 3519</td><td className="num">{fmtAccounting(x.california.estimated_total_tax)}</td><td className="num">{fmtAccounting(x.california.payments)}</td>
              <td className="num">{fmtAccounting(x.california.estimated_balance)}</td><td className="num"><strong>{fmtAccounting(x.california.paid_with_ftb_3519)}</strong></td></tr>
          </tbody>
        </table>
        <p className="text-tertiary text-xs">Rule: {x.federal.rule} — recomputed {fmtAccounting(x.federal.recomputed_payment)} federal, {fmtAccounting(x.california.recomputed_payment)} CA, matching the packet. {x.note}</p>
        {x.filed ? <Callout tone="neutral">Recorded by {x.filed.actor_name} · {fmtDateTime(x.filed.at)}: {x.filed.note}</Callout> : (
          <div className="finding__actions">
            <input className="ui-input review__input" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Extension note" />
            <Button size="sm" variant="primary" icon={<CalendarClock aria-hidden />} disabled={file.isPending} onClick={() => file.mutate(undefined)}>Record extension</Button>
          </div>
        )}
        <Refused error={file.error} />
      </div>
    </Card>
  );
}

function GateCard({ f }: { f: Filing }) {
  const g = useQuery({ queryKey: ["gate"], queryFn: api.gate });
  const [note, setNote] = useState("");
  const present = useReviewWrite(() => api.present(note));
  if (!g.data) return null;
  const gate = g.data;
  return (
    <Card title="Pre-file gate" actions={gate.clear ? <Badge tone="verified" icon={<CheckCircle2 aria-hidden />}>Clear</Badge>
      : <Badge tone="error" icon={<Lock aria-hidden />}>{gate.blockers.length} outstanding</Badge>}
      description="Checked again by the server at every step that needs it — this list is the same check.">
      <div className="stack-3">
        {gate.blockers.length > 0 && (
          <ul className="gate">
            {gate.blockers.map((b, i) => (
              <li key={i} className="gate__item">
                <AlertOctagon aria-hidden className="gate__icon" />
                <div className="gate__text"><strong>{b.title}</strong>{b.detail && <span className="text-secondary text-sm">{b.detail}</span>}</div>
                <Badge tone="outline">{b.kind.replace(/_/g, " ")}</Badge>
                {b.link && <Link className="text-sm" to={b.link}>{b.node === "return" ? "Sign off" : "Open"}</Link>}
              </li>
            ))}
          </ul>
        )}
        {gate.blockers.some((b) => b.node === "return" && (b.kind === "missing_signoff" || b.kind === "reopened_signoff")) && (
          <div className="gate-signoff">
            <h3 className="overline">Sign off on the return</h3>
            <ReturnSignoff compact />
          </div>
        )}
        <details>
          <summary className="text-sm" style={{ cursor: "pointer", color: "var(--accent-text)" }}>Firm required steps ({gate.steps.filter((s) => s.status === "done").length}/{gate.steps.length})</summary>
          <ul className="steps">{gate.steps.map((s) => (
            <li key={s.step}>{s.status === "done" ? <CheckCircle2 aria-hidden className="ck ck--pass" /> : <Circle aria-hidden className="ck" />}
              <span>{s.step}</span>{s.detail && <span className="text-tertiary text-xs">{s.detail}</span>}</li>
          ))}</ul>
        </details>
        {f.stage === "preparing" || !f.presented_current ? (
          <div className="finding__actions">
            <input className="ui-input review__input" placeholder="Note to the client (optional)" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Presentation note" />
            <Button size="sm" variant="primary" icon={<Send aria-hidden />} disabled={present.isPending} onClick={() => present.mutate(undefined)}>
              {f.presented && !f.presented_current ? "Present again (return changed)" : "Present to client for approval"}
            </Button>
          </div>
        ) : null}
        <Refused error={present.error} />
      </div>
    </Card>
  );
}

function DiligenceCard({ f }: { f: Filing }) {
  const needed = f.diligence.filter((d) => d.status !== "not_applicable");
  return (
    <Card title="Due diligence (Form 8867)" description="Firm rule: due diligence is documented for CTC, ODC, AOTC, EIC and head of household." >
      <div id="diligence" className="stack-3">
        {needed.map((d) => <DiligenceItemRow key={d.id} id={d.id} f={f} />)}
        <p className="text-tertiary text-xs">Not applicable: {f.diligence.filter((d) => d.status === "not_applicable").map((d) => d.label).join(", ")}.</p>
      </div>
    </Card>
  );
}

function DiligenceItemRow({ id, f }: { id: string; f: Filing }) {
  const d = f.diligence.find((x) => x.id === id)!;
  const [answers, setAnswers] = useState<Record<string, boolean>>({});
  const [note, setNote] = useState("");
  const save = useReviewWrite(() => api.diligence(id, answers, note));
  return (
    <div className="dd">
      <div className="row"><strong>{d.label}</strong>{d.line && <RefChip refId={d.line} />}<span className="spacer" />
        {d.status === "complete" ? <Badge tone="verified" icon={<CheckCircle2 aria-hidden />}>Complete</Badge> : <Badge tone="warning">Required</Badge>}</div>
      {d.record ? <p className="text-secondary text-sm">{d.record.actor_name} · {fmtDateTime(d.record.at)}: {d.record.note}</p> : <>
        <ul className="dd__qs">{f.diligence_questions.map((q) => (
          <li key={q}><label><input type="checkbox" checked={!!answers[q]} onChange={(e) => setAnswers({ ...answers, [q]: e.target.checked })} /> {q}</label></li>
        ))}</ul>
        <div className="finding__actions">
          <input className="ui-input review__input" placeholder="What you asked and what the client said…" value={note} onChange={(e) => setNote(e.target.value)} aria-label={`Due diligence note for ${d.label}`} />
          <Button size="sm" variant="primary" disabled={save.isPending} onClick={() => save.mutate(undefined)}>Complete</Button>
        </div>
        <Refused error={save.error} />
      </>}
    </div>
  );
}

function ApprovalCard({ f }: { f: Filing }) {
  const ero = useReviewWrite(() => api.eroSign(""));
  if (!f.presented) return null;
  return (
    <Card title="Client approval & Form 8879"
      actions={f.presented_current ? <Badge tone="verified">Presented {fmtDateTime(f.presented.at)}</Badge> : <Badge tone="warning">Stale — return changed</Badge>}>
      <div className="stack-3">
        <FiguresTable f={f.presented.figures} caption={`The amounts the taxpayers approve (fingerprint ${f.presented.fingerprint}). ${f.presented.figures.basis}.`} />
        <ul className="signers">
          {f.signers.map((s) => (
            <li key={s.id}>{s.approval ? <BadgeCheck aria-hidden className="ck ck--pass" /> : <Circle aria-hidden className="ck" />}
              <strong>{s.name}</strong><span className="text-secondary text-sm">{s.approval ? `signed 8879 as ${s.approval.role} · ${fmtDateTime(s.approval.at)}` : "awaiting signature on the client portal"}</span></li>
          ))}
          <li>{f.ero ? <BadgeCheck aria-hidden className="ck ck--pass" /> : <Circle aria-hidden className="ck" />}
            <strong>{f.ero_signer}</strong><span className="text-secondary text-sm">{f.ero ? `ERO signature · EFIN ${f.ero.efin} · ${fmtDateTime(f.ero.at)}` : "ERO / paid preparer signs after both taxpayers"}</span>
            {!f.ero && f.signers.every((s) => s.approval) && <Button size="sm" variant="primary" icon={<FileSignature aria-hidden />} disabled={ero.isPending} onClick={() => ero.mutate(undefined)}>Sign as ERO</Button>}
          </li>
        </ul>
        <Refused error={ero.error} />
      </div>
    </Card>
  );
}

function SubmissionRow({ s }: { s: Submission }) {
  const tone = s.status === "accepted" ? "verified" : s.status === "rejected" ? "error" : "warning";
  return (
    <li className={`sub sub--${s.status}`}>
      <div className="row">
        {s.status === "accepted" ? <CheckCircle2 aria-hidden className="ck ck--pass" /> : <XCircle aria-hidden className="ck ck--fail" />}
        <strong>{s.jurisdiction === "federal" ? "Federal 1040" : "California 540NR"}</strong>
        <span className="mono text-tertiary text-sm">{s.id}</span><Badge tone={tone}>{s.status.replace(/_/g, " ")}</Badge>
        <span className="spacer" /><span className="text-tertiary text-xs">attempt {s.attempt} · agency {s.response?.agency_date.replace("T", " ").slice(0, 16)}</span>
      </div>
      {s.response?.errors.map((e) => (
        <div key={e.code} className="sub__err"><span className="mono">{e.code}</span> {e.message}</div>
      ))}
      {s.response && <span className="text-tertiary text-xs">Response from {s.response.source}</span>}
    </li>
  );
}

function EfileCard({ f }: { f: Filing }) {
  const { actor } = useSession();
  const transmit = useReviewWrite(() => api.transmit());
  const [reason, setReason] = useState("R0000-504-02: dependent 2 TIN per Theo's Social Security card (D71).");
  const fix = useReviewWrite((p: { person: string; ev: string }) => api.correctIdentity(p.person, p.ev, reason));
  if (f.stage === "preparing" || f.stage === "presented") return null;
  const rejected = f.submissions.some((s) => s.status === "rejected") && !f.filed;
  const bad = f.tin_checks.filter((c) => !c.match);
  return (
    <Card title="E-file" actions={f.filed ? <Badge tone="verified">Accepted</Badge> : rejected ? <Badge tone="error" icon={<ShieldAlert aria-hidden />}>Rejected</Badge> : null}>
      <div className="stack-3">
        {f.submissions.length > 0 && <ol className="subs">{[...f.submissions].reverse().map((s) => <SubmissionRow key={s.id} s={s} />)}</ol>}
        <table className="mini">
          <thead><tr><th>Dependent</th><th>TIN on the return</th><th>SSA record</th><th>Evidence</th><th></th></tr></thead>
          <tbody>{f.tin_checks.map((c) => (
            <tr key={c.person}><td>{c.name}</td><td className="mono">{c.on_return}</td><td className="mono">{c.ssa ?? "—"}</td>
              <td>{c.evidence && <span className="jt-inline"><RefChip refId={c.evidence.document_id} /><RefChip refId={c.evidence.ev} /></span>}</td>
              <td>{c.match ? <Badge tone="verified">match</Badge> : <Badge tone="error">mismatch</Badge>}</td></tr>
          ))}</tbody>
        </table>
        {rejected && bad.length > 0 && (
          <div className="fix">
            <div className="fix__head"><Wrench aria-hidden /><strong>Fix the reject</strong><span className="text-secondary">Correct the TIN on the return from the SSA document, then resubmit. The 8879 amounts don't change, so the signatures stand.</span></div>
            <div className="finding__actions">
              <input className="ui-input review__input" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Correction reason" />
              {bad.map((c) => c.evidence && (
                <Button key={c.person} size="sm" variant="primary" disabled={fix.isPending} onClick={() => fix.mutate({ person: c.person, ev: c.evidence!.ev })}>
                  Correct {c.name.split(" ")[0]}'s TIN from {c.evidence.document_id}
                </Button>
              ))}
            </div>
            <Refused error={fix.error} />
            {!actor?.sensitive_data_clearance && <Callout tone="warning">You are not cleared for full SSNs — the server will refuse this correction.</Callout>}
          </div>
        )}
        {Object.entries(f.identity).flatMap(([k, hist]) => hist.map((h) => (
          <Callout key={`${k}${h.seq}`} tone="neutral">{h.actor_name} corrected {k} {h.from} → {h.to} from {h.document_id} · {fmtDateTime(h.at)}: {h.reason}</Callout>
        )))}
        {!f.filed && (
          <div className="row">
            <Button variant="primary" icon={<Send aria-hidden />} disabled={transmit.isPending} onClick={() => transmit.mutate(undefined)}>
              {f.submissions.length ? "Resubmit federal + California" : "Transmit federal + California"}
            </Button>
            <span className="text-tertiary text-sm">Agency responses are the packet's recorded ones (tax_agency_records.efile).</span>
          </div>
        )}
        <Refused error={transmit.error} />
      </div>
    </Card>
  );
}

function FiledCard({ f }: { f: Filing }) {
  const q = useQuery({ queryKey: ["filed"], queryFn: api.filedReturn, enabled: !!f.filed });
  if (!f.filed || !q.data) return null;
  const r = q.data;
  return (
    <Card title="Filed return (frozen)" actions={<Badge tone={r.intact ? "verified" : "error"} icon={<Snowflake aria-hidden />}>{r.intact ? "Snapshot intact" : "Snapshot altered!"}</Badge>}>
      <div className="stack-3">
        <Callout tone="neutral">
          Accepted {r.accepted_at.slice(0, 10)} · federal <span className="mono">{r.submissions.federal}</span> · California <span className="mono">{r.submissions.california}</span>.
          Frozen at event #{r.as_of_seq} (snapshot <span className="mono">{r.snapshot_hash}</span>), {r.lines.length} lines, adjustments {r.adjustments.join(", ") || "none"}.
          The server now refuses adjustments, corrections, verifications and sign-offs on this return — further work goes into an <Link to="/amend">amendment</Link>.
        </Callout>
        <FiguresTable f={r.figures} />
        {f.interest && f.interest.balance_due > 0 && (
          <p className="text-secondary text-sm">Balance paid {f.interest.paid}, {f.interest.days_late} days after 2026-04-15: interest ≈ {fmtAccounting(f.interest.interest)}, failure-to-pay ≈ {fmtAccounting(f.interest.penalty)}. {f.interest.basis}</p>
        )}
      </div>
    </Card>
  );
}

/** Extension → gate → diligence → approval/8879 → e-file → filed. */
export function FilingPage() {
  const q = useQuery({ queryKey: ["filing"], queryFn: api.filing });
  if (q.isPending) return <PageSkeleton label="Loading filing" />;
  if (q.isError) return <div className="page"><ErrorState error={q.error} /></div>;
  const f = q.data;
  return (
    <div className="page">
      <PageHeader title="Filing" meta={<span>Every step is an event; the server enforces the order and the gate.</span>} />
      <Stepper stage={f.stage} />
      <div className="stack-4">
        <FiledCard f={f} />
        {!f.filed && <><ExtensionCard /><GateCard f={f} /><DiligenceCard f={f} /></>}
        <ApprovalCard f={f} />
        <EfileCard f={f} />
        {f.filed && <ExtensionCard />}
        {!f.presented && <Card title="Current figures"><FiguresTable f={f.figures} /></Card>}
      </div>
    </div>
  );
}
