// The review layer for one node (a return line, an extracted value, a document,
// or the whole return): verifications, the sign-off ladder, review notes and,
// for values, corrections. Every action is a server-checked event; buttons the
// firm's rules would refuse are disabled with the rule's own reason, and if a
// rule still refuses (someone else acted first) the refusal is shown inline.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CircleDot, Lock, MessageSquare, PenLine, RotateCcw, ShieldCheck, Undo2 } from "lucide-react";
import { api, ApiError, type Level, type Note, type NodeReview, type SignOff } from "../../api/client";
import { Badge, Button, Callout, ErrorState, Select, Skeleton } from "../../ui";
import { fmtDateTime, fmtValue } from "../../format";
import { useSession } from "../../session";

const LEVELS: Level[] = ["preparer", "reviewer", "partner"];
const METHOD_LABEL: Record<string, string> = {
  agreed_to_source_document: "Agreed to source document",
  recalculated: "Recalculated",
  confirmed_with_client: "Confirmed with client",
  agreed_to_prior_year: "Agreed to prior year",
  agreed_to_third_party_record: "Agreed to third-party record",
};
export const methodLabel = (m: string) => METHOD_LABEL[m] ?? m.replace(/_/g, " ");

/** Invalidate everything a review write can change. */
export function useReviewWrite<TArgs, TData = unknown>(fn: (a: TArgs) => Promise<TData>) {
  const qc = useQueryClient();
  return useMutation<TData, Error, TArgs>({
    mutationFn: fn,
    onSettled: () => {
      for (const k of ["review", "review-summary", "queue", "readiness", "events", "document", "values", "line", "landing", "health", "checks", "variance", "adjustments", "states", "compare", "digest", "bulks", "lines", "filing", "gate", "extension", "filed", "amendments", "notices", "carryforward", "client-filing", "status", "budget", "search"]) {
        void qc.invalidateQueries({ queryKey: [k] });
      }
    },
  });
}

function ErrorLine({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof ApiError ? error.message : String(error);
  const conflict = error instanceof ApiError && error.status === 409;
  return <Callout tone={conflict ? "warning" : "error"}>{conflict ? "Changed by someone else: " : "Refused by the server: "}{msg}</Callout>;
}

export function ReviewPanel({ node, version, compact }: { node: string; version?: string; compact?: boolean }) {
  const q = useQuery({ queryKey: ["review", node, version], queryFn: () => api.review(node, version) });
  if (q.isPending) return <div className="stack-2"><Skeleton height={60} /><Skeleton height={120} /></div>;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const r = q.data;
  return (
    <div className="review stack-5">
      <ReviewStatus r={r} />
      {node.startsWith("ev-") && <CorrectionSection r={r} />}
      {!node.startsWith("ev-") && !/^D\d\d$/.test(node) && node !== "return" && <AdjustSection node={node} />}
      <VerifySection r={r} version={version} />
      <SignOffSection r={r} version={version} />
      <NotesSection r={r} version={version} compact={compact} />
    </div>
  );
}

function ReviewStatus({ r }: { r: NodeReview }) {
  const current = r.verifications.filter((v) => v.status === "current").length;
  const stale = r.verifications.filter((v) => v.status === "stale").length;
  const open = r.notes.filter((n) => n.status === "open");
  const blocking = open.filter((n) => n.blocking).length;
  const reopened = r.signoffs.filter((s) => s.status === "reopened").length;
  return (
    <div className="review__status">
      {current > 0 ? <Badge tone="verified" icon={<CheckCircle2 aria-hidden />}>Verified{current > 1 ? ` ×${current}` : ""}</Badge>
        : <Badge tone="neutral">Not verified</Badge>}
      {stale > 0 && <Badge tone="warning">{stale} stale</Badge>}
      {LEVELS.map((l) => {
        const s = r.signoffs.find((x) => x.level === l && x.status !== "withdrawn");
        return s ? <Badge key={l} tone={s.status === "active" ? "verified" : "error"}>{l} {s.status === "active" ? "✓" : "reopened"}</Badge> : null;
      })}
      {blocking > 0 && <Badge tone="error" icon={<Lock aria-hidden />}>{blocking} blocking</Badge>}
      {open.length - blocking > 0 && <Badge tone="open">{open.length - blocking} open note{open.length - blocking > 1 ? "s" : ""}</Badge>}
      {reopened > 0 && <Badge tone="error" icon={<AlertTriangle aria-hidden />}>Sign-off reopened</Badge>}
      <span className="text-tertiary text-xs mono" title="Fingerprint of the evidence beneath this node">{r.evidence_count} evidence · {r.fingerprint.slice(0, 8)}</span>
    </div>
  );
}

function VerifySection({ r, version }: { r: NodeReview; version?: string }) {
  const methods = useQuery({ queryKey: ["methods"], queryFn: api.methods, staleTime: Infinity });
  const [method, setMethod] = useState("agreed_to_source_document");
  const [note, setNote] = useState("");
  const verify = useReviewWrite(() => api.verify(r.node, method, note, version));
  const withdraw = useReviewWrite((id: string) => api.withdrawVerification(id));
  const { actor } = useSession();
  const perm = r.permissions.verify;
  return (
    <section className="stack-2" aria-labelledby={`vh-${r.node}`}>
      <h3 id={`vh-${r.node}`} className="overline">How it was verified</h3>
      {r.verifications.length === 0 && <p className="text-tertiary text-sm">No verification recorded yet.</p>}
      {r.verifications.map((v) => (
        <div key={v.id} className={`review__item review__item--${v.status}`}>
          <div className="row">
            {v.status === "current" ? <CheckCircle2 className="review__icon review__icon--ok" aria-hidden /> : <CircleDot className="review__icon" aria-hidden />}
            <strong>{methodLabel(v.method)}</strong>
            <span className="text-secondary text-sm">by {v.actor_name} · {fmtDateTime(v.at)}</span>
            <span className="spacer" />
            {v.status !== "current" && <Badge tone={v.status === "stale" ? "warning" : "neutral"}>{v.status}</Badge>}
            {v.status !== "withdrawn" && v.actor === actor?.id && (
              <Button size="sm" variant="ghost" icon={<Undo2 aria-hidden />} onClick={() => withdraw.mutate(v.id)}>Withdraw</Button>
            )}
          </div>
          {v.note && <p className="review__text">{v.note}</p>}
          {v.status === "stale" && <ChangedList changed={v.changed} lead="Evidence changed since this verification:" />}
        </div>
      ))}
      <div className="review__form">
        <Select label="Method" hideLabel value={method} onChange={setMethod}
          options={(methods.data ?? []).map((m) => ({ value: m, label: methodLabel(m) }))} />
        <input className="ui-input review__input" placeholder="What did you check? (optional)" value={note}
          onChange={(e) => setNote(e.target.value)} aria-label="Verification note" disabled={!perm.allowed} />
        <Button variant="primary" size="md" icon={<ShieldCheck aria-hidden />} disabled={!perm.allowed || verify.isPending}
          title={perm.reason ?? undefined} onClick={() => verify.mutate(undefined, { onSuccess: () => setNote("") })}>
          Record verification
        </Button>
      </div>
      {!perm.allowed && <p className="text-tertiary text-xs">{perm.reason}</p>}
      <ErrorLine error={verify.error ?? withdraw.error} />
    </section>
  );
}

export function SignOffSection({ r, version }: { r: NodeReview; version?: string }) {
  const sign = useReviewWrite((level: Level) => api.signoff(r.node, level, r.fingerprint, version));
  const withdraw = useReviewWrite((id: string) => api.withdrawSignoff(id));
  const { actor } = useSession();
  return (
    <section className="stack-2" aria-labelledby={`sh-${r.node}`}>
      <h3 id={`sh-${r.node}`} className="overline">Sign-off</h3>
      <ol className="ladder">
        {LEVELS.map((level) => {
          const history = r.signoffs.filter((s) => s.level === level);
          const current = [...history].reverse().find((s) => s.status !== "withdrawn");
          const perm = r.permissions[`signoff_${level}`];
          return (
            <li key={level} className={`ladder__step ladder__step--${current?.status ?? "empty"}`}>
              <span className="ladder__level">{level}</span>
              <div className="ladder__body">
                {current ? <SignOffLine s={current} /> : <span className="text-tertiary text-sm">Not signed</span>}
                {current?.status === "reopened" && <ChangedList changed={current.changed} lead={current.reopened_reason ?? "Signed content changed:"} />}
              </div>
              {(!current || current.status === "reopened") && (
                <Button size="sm" variant={perm?.allowed ? "secondary" : "ghost"} icon={<PenLine aria-hidden />}
                  disabled={!perm?.allowed || sign.isPending} title={perm?.reason ?? `Sign as ${level}`}
                  onClick={() => sign.mutate(level)}>
                  {current?.status === "reopened" ? "Sign again" : "Sign"}
                </Button>
              )}
              {current?.status === "active" && current.actor === actor?.id && (
                <Button size="sm" variant="ghost" icon={<Undo2 aria-hidden />} onClick={() => withdraw.mutate(current.id)}>Withdraw</Button>
              )}
              {!perm?.allowed && (!current || current.status === "reopened") && <p className="ladder__why">{perm?.reason}</p>}
            </li>
          );
        })}
      </ol>
      <ErrorLine error={sign.error ?? withdraw.error} />
    </section>
  );
}

function SignOffLine({ s }: { s: SignOff }) {
  return (
    <span className="row-wrap">
      {s.status === "active" ? <CheckCircle2 className="review__icon review__icon--ok" aria-hidden /> : <AlertTriangle className="review__icon review__icon--bad" aria-hidden />}
      <strong>{s.actor_name}</strong>
      <span className="text-secondary text-sm">{fmtDateTime(s.at)}</span>
      {s.status === "reopened" && <Badge tone="error">Reopened {s.reopened_at ? fmtDateTime(s.reopened_at) : ""}</Badge>}
    </span>
  );
}

function ChangedList({ changed, lead }: { changed: { ev: string; was?: unknown; now?: unknown }[]; lead: string }) {
  if (!changed.length) return null;
  return (
    <div className="changed">
      <span className="text-secondary text-sm">{lead}</span>
      <ul>
        {changed.slice(0, 6).map((c) => (
          <li key={c.ev} className="mono text-sm">{c.ev}: <s>{fmtValue(c.was)}</s> → <strong>{fmtValue(c.now)}</strong></li>
        ))}
      </ul>
    </div>
  );
}

function NotesSection({ r, version, compact }: { r: NodeReview; version?: string; compact?: boolean }) {
  const [text, setText] = useState("");
  const [blocking, setBlocking] = useState(true);
  const open = useReviewWrite(() => api.openNote(r.node, text, blocking, version));
  const permNote = r.permissions[blocking ? "note_blocking" : "note"];
  const sorted = [...r.notes].sort((a, b) => (a.status === b.status ? b.last_seq - a.last_seq : a.status === "open" ? -1 : 1));
  return (
    <section className="stack-2" aria-labelledby={`nh-${r.node}`}>
      <h3 id={`nh-${r.node}`} className="overline">Review notes</h3>
      {sorted.length === 0 && <p className="text-tertiary text-sm">No notes.</p>}
      {sorted.map((n) => <NoteCard key={n.id} n={n} compact={compact} />)}
      <div className="note-compose">
        <textarea className="ui-input note-compose__text" rows={2} placeholder="Leave a review note…" value={text}
          onChange={(e) => setText(e.target.value)} aria-label="New review note" disabled={!permNote.allowed} />
        <div className="row">
          <label className="check">
            <input type="checkbox" checked={blocking} onChange={(e) => setBlocking(e.target.checked)} />
            <Lock aria-hidden /> Blocks filing until cleared
          </label>
          <span className="spacer" />
          <Button variant="primary" icon={<MessageSquare aria-hidden />} disabled={!text.trim() || !permNote.allowed || open.isPending}
            title={permNote.reason ?? undefined} onClick={() => open.mutate(undefined, { onSuccess: () => setText("") })}>
            Add note
          </Button>
        </div>
      </div>
      <ErrorLine error={open.error} />
    </section>
  );
}

function NoteCard({ n, compact }: { n: Note; compact?: boolean }) {
  const [reply, setReply] = useState("");
  const act = useReviewWrite((a: { kind: "reply" | "resolve" | "reopen"; text: string }) => api.noteAction(n.id, a.kind, a.text, n.last_seq));
  const thread = compact ? n.thread.slice(-3) : n.thread;
  return (
    <article className={`note note--${n.status}${n.blocking ? " note--blocking" : ""}`}>
      <header className="row">
        {n.blocking && n.status === "open" ? <Badge tone="error" icon={<Lock aria-hidden />}>Blocks filing</Badge>
          : <Badge tone={n.status === "open" ? "open" : "verified"}>{n.status}</Badge>}
        <span className="text-secondary text-sm">{n.author_name} · {fmtDateTime(n.at)}</span>
      </header>
      <ol className="note__thread">
        {thread.map((t) => (
          <li key={t.seq}>
            <span className="note__who">{t.actor_name}</span>
            <span className={`note__kind note__kind--${t.kind}`}>{t.kind}</span>
            <span className="text-tertiary text-xs">{fmtDateTime(t.at)}</span>
            {t.text && <p className="review__text">{t.text}</p>}
          </li>
        ))}
      </ol>
      <div className="note__actions">
        <input className="ui-input review__input" placeholder={n.status === "open" ? "Reply or resolution…" : "Reason to reopen…"}
          value={reply} onChange={(e) => setReply(e.target.value)} aria-label={`Reply to note ${n.id}`} />
        {n.status === "open" ? <>
          <Button size="sm" disabled={!reply.trim() || act.isPending} onClick={() => act.mutate({ kind: "reply", text: reply }, { onSuccess: () => setReply("") })}>Reply</Button>
          <Button size="sm" variant="primary" icon={<CheckCircle2 aria-hidden />} disabled={act.isPending}
            onClick={() => act.mutate({ kind: "resolve", text: reply }, { onSuccess: () => setReply("") })}>Resolve</Button>
        </> : (
          <Button size="sm" icon={<RotateCcw aria-hidden />} disabled={act.isPending}
            onClick={() => act.mutate({ kind: "reopen", text: reply }, { onSuccess: () => setReply("") })}>Reopen</Button>
        )}
      </div>
      <ErrorLine error={act.error} />
    </article>
  );
}

function CorrectionSection({ r }: { r: NodeReview }) {
  const [to, setTo] = useState("");
  const [reason, setReason] = useState("");
  const correct = useReviewWrite(() => api.correct(r.node, coerce(to), reason));
  const revert = useReviewWrite(() => api.revertCorrection(r.node, reason || "Reverted to the value as read"));
  const perm = r.permissions.correct;
  const c = r.correction;
  return (
    <section className="stack-2" aria-labelledby={`ch-${r.node}`}>
      <h3 id={`ch-${r.node}`} className="overline">Correction</h3>
      {c ? (
        <Callout tone="open">
          <div className="stack-1">
            <span>Corrected <s className="mono">{fmtValue(c.from_value)}</s> → <strong className="mono">{fmtValue(c.to_value)}</strong> by {c.actor_name} · {fmtDateTime(c.at)}</span>
            <span>{c.reason}</span>
          </div>
        </Callout>
      ) : <p className="text-tertiary text-sm">Uses the value as read. Correct it only to what the document actually shows.</p>}
      <div className="review__form">
        <input className="ui-input review__input review__input--short" placeholder="Correct value" value={to}
          onChange={(e) => setTo(e.target.value)} aria-label="Corrected value" disabled={!perm.allowed} />
        <input className="ui-input review__input" placeholder="Reason — what the document shows" value={reason}
          onChange={(e) => setReason(e.target.value)} aria-label="Correction reason" disabled={!perm.allowed} />
        <Button variant="primary" disabled={!perm.allowed || !to.trim() || !reason.trim() || correct.isPending}
          title={perm.reason ?? undefined} onClick={() => correct.mutate(undefined, { onSuccess: () => { setTo(""); setReason(""); } })}>
          Correct
        </Button>
        {c && <Button variant="ghost" icon={<Undo2 aria-hidden />} disabled={!perm.allowed || revert.isPending} onClick={() => revert.mutate(undefined)}>Revert</Button>}
      </div>
      {!perm.allowed && <p className="text-tertiary text-xs">{perm.reason}</p>}
      <ErrorLine error={correct.error ?? revert.error} />
    </section>
  );
}

/** Change this return line's value: an adjustment (engine value preserved, tax effect, partner rule). */
function AdjustSection({ node }: { node: string }) {
  const adjs = useQuery({ queryKey: ["adjustments"], queryFn: api.adjustments });
  const [to, setTo] = useState("");
  const [reason, setReason] = useState("");
  const propose = useReviewWrite(() => api.proposeAdjustment({ title: `Adjust ${node}`, reason, changes: [{ key: node, to_value: Number(to.replace(/,/g, "")) }] }));
  const mine = (adjs.data ?? []).filter((a) => a.changes.some((c) => c.key === node) && (a.status === "active" || a.status === "pending_partner"));
  return (
    <section className="stack-2" aria-labelledby={`ah-${node}`}>
      <h3 id={`ah-${node}`} className="overline">Adjustments</h3>
      {mine.length === 0 && <p className="text-tertiary text-sm">The engine's value stands. An adjustment keeps it and records the change beside it.</p>}
      {mine.map((a) => (
        <Callout key={a.id} tone={a.status === "active" ? "open" : "warning"}>
          <strong className="mono">{a.id}</strong> {a.status === "active" ? "active" : "awaiting partner sign-off"}: {a.title} — {a.reason}
        </Callout>
      ))}
      <div className="review__form">
        <input className="ui-input review__input review__input--short" placeholder="New value" value={to} inputMode="decimal"
          onChange={(e) => setTo(e.target.value)} aria-label="Adjusted value" />
        <input className="ui-input review__input" placeholder="Why — evidence or judgment" value={reason}
          onChange={(e) => setReason(e.target.value)} aria-label="Adjustment reason" />
        <Button variant="secondary" disabled={!to.trim() || Number.isNaN(Number(to.replace(/,/g, ""))) || !reason.trim() || propose.isPending}
          onClick={() => propose.mutate(undefined, { onSuccess: () => { setTo(""); setReason(""); } })}>Propose</Button>
      </div>
      {propose.data && <Callout tone={propose.data.status === "active" ? "neutral" : "warning"}>
        {propose.data.id}: federal {fmtValue(Number(propose.data.tax_effect.federal_balance_due))}, CA {fmtValue(Number(propose.data.tax_effect.california_balance_due))} —
        {propose.data.status === "active" ? " applied." : ` over ${propose.data.threshold.toLocaleString()}, awaits partner sign-off.`}
      </Callout>}
      <ErrorLine error={propose.error} />
    </section>
  );
}

/** "1,500" -> 1500 for numeric reads; anything else stays text (EINs, dates). */
function coerce(s: string): unknown {
  const t = s.trim();
  return /^-?[\d,]+(\.\d+)?$/.test(t) && !/^\d{2}-\d{7}$/.test(t) ? Number(t.replace(/,/g, "")) : t;
}
