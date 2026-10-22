import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";
import { ReturnSignoff } from "../components/review/ReturnSignoff";
import { CheckCircle2, Lock, ShieldAlert } from "lucide-react";
import { api, type Note } from "../api/client";
import { RefChip } from "../components/evidence";
import { methodLabel } from "../components/review/ReviewPanel";
import { useTrace } from "../trace";
import { Badge, Card, EmptyState, ErrorState, PageHeader, PageSkeleton, Table, type Column } from "../ui";
import { fmtDateTime, fmtValue } from "../format";

/** Everything open in the review layer, and whether the return can be filed. */
export function ReviewPage() {
  const q = useQuery({ queryKey: ["queue"], queryFn: api.queue });
  const { open } = useTrace();
  const { hash } = useLocation();
  // Arriving from the pre-file gate (#return-signoff): bring the sign-off control into view and focus it.
  useEffect(() => {
    if (!hash || q.isPending) return;
    const el = document.getElementById(hash.slice(1));
    el?.scrollIntoView({ block: "center" });
    el?.focus({ preventScroll: true });
  }, [hash, q.isPending]);
  if (q.isPending) return <PageSkeleton label="Loading review queue" />;
  if (q.isError) return <div className="page"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>;
  const d = q.data;
  const openNode = (node: string) => (node.startsWith("ev-") || /^D\d\d$/.test(node) || node === "return" ? undefined : open(node));

  const noteCols: Column<Note>[] = [
    { id: "b", header: "", width: "120px", cell: (n) => n.blocking ? <Badge tone="error" icon={<Lock aria-hidden />}>Blocks filing</Badge> : <Badge tone="open">Open</Badge> },
    { id: "node", header: "On", width: "150px", cell: (n) => <span onClick={(e) => e.stopPropagation()}><RefChip refId={n.node} /></span> },
    { id: "t", header: "Note", width: "minmax(260px, 3fr)", cell: (n) => <span className="truncate" style={{ display: "block" }} title={n.text}>{n.text}</span> },
    { id: "who", header: "By", width: "150px", cell: (n) => <span className="text-secondary">{n.author_name}</span> },
    { id: "at", header: "Last activity", width: "140px", cell: (n) => <span className="text-secondary nowrap">{fmtDateTime(n.thread[n.thread.length - 1].at)}</span> },
  ];

  return (
    <div className="page">
      <PageHeader title="Review" meta={<span>Open notes, reopened sign-offs and anything that blocks filing.</span>} />

      <div className="overview-grid">
        <Card title="Filing readiness"
          actions={d.readiness.ready ? <Badge tone="verified" icon={<CheckCircle2 aria-hidden />}>No blockers</Badge>
            : <Badge tone="error" icon={<ShieldAlert aria-hidden />}>{d.readiness.blockers.length} blocker{d.readiness.blockers.length === 1 ? "" : "s"}</Badge>}>
          <div className="stack-2">
            {d.readiness.blockers.map((b, i) => (
              <div key={i} className="blocker blocker--block">
                <Lock aria-hidden /><div><strong>{b.title}</strong>{b.detail && <div className="text-secondary text-sm">{b.detail}</div>}</div>
                <span className="spacer" /><RefChip refId={b.node} />
              </div>
            ))}
            {d.readiness.warnings.map((b, i) => (
              <div key={`w${i}`} className="blocker"><span className="blocker__dot" aria-hidden /><span className="text-secondary">{b.title}</span></div>
            ))}
            {d.readiness.ready && d.readiness.warnings.length === 0 && <p className="text-secondary">Nothing outstanding.</p>}
            <div className="readiness-signoff">
              <h3 className="overline">Sign off on the return (reviewer / partner)</h3>
              <ReturnSignoff />
            </div>
          </div>
        </Card>
        <Card title="Assignments" description="Seeded from firm.assignment_at_start.">
          <dl className="ui-dl">
            {d.assignments.map((a) => [<dt key={`${a.role}t`}>{a.role}</dt>, <dd key={`${a.role}d`}>{a.actor_name}</dd>])}
          </dl>
        </Card>
      </div>

      <div className="stack-4">
        <Card title={`Open review notes · ${d.open_notes.length}`} flush>
          <Table label="Open review notes" columns={noteCols} rows={d.open_notes} rowKey={(n) => n.id} density="default"
            onRowClick={(n) => openNode(n.node)}
            empty={<EmptyState icon={<CheckCircle2 />} title="No open notes" />} />
        </Card>

        {d.reopened_signoffs.length > 0 && (
          <Card title={`Reopened sign-offs · ${d.reopened_signoffs.length}`} description="The signed content changed after sign-off. The signer must look again.">
            <div className="stack-2">
              {d.reopened_signoffs.map((s) => (
                <div key={s.id} className="blocker blocker--block">
                  <ShieldAlert aria-hidden />
                  <div className="stack-1">
                    <span><strong>{s.level}</strong> sign-off by {s.actor_name} on <RefChip refId={s.node} /> reopened {s.reopened_at ? fmtDateTime(s.reopened_at) : ""}</span>
                    <span className="text-secondary text-sm">{s.reopened_reason}</span>
                    {s.changed.map((c) => <span key={c.ev} className="mono text-sm">{c.ev}: <s>{fmtValue(c.was)}</s> → <strong>{fmtValue(c.now)}</strong></span>)}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )}

        <div className="landing-grid">
          <Card title={`Signed off · ${d.active_signoffs.length}`}>
            {d.active_signoffs.length === 0 ? <p className="text-tertiary text-sm">No active sign-offs.</p> : (
              <ul className="stack-2">{d.active_signoffs.map((s) => (
                <li key={s.id} className="row-wrap"><RefChip refId={s.node} /><Badge tone="verified">{s.level}</Badge><span className="text-secondary text-sm">{s.actor_name} · {fmtDateTime(s.at)}</span></li>
              ))}</ul>
            )}
          </Card>
          <Card title={`Corrections & stale verifications · ${d.corrections.length + d.stale_verifications.length}`}>
            <ul className="stack-2">
              {d.corrections.map((c) => (
                <li key={c.id} className="stack-1">
                  <span className="row-wrap"><RefChip refId={c.ev} /><span className="mono text-sm"><s>{fmtValue(c.from_value)}</s> → {fmtValue(c.to_value)}</span></span>
                  <span className="text-secondary text-sm">{c.actor_name}: {c.reason}</span>
                </li>
              ))}
              {d.stale_verifications.map((v) => (
                <li key={v.id} className="row-wrap"><RefChip refId={v.node} /><Badge tone="warning">stale</Badge>
                  <span className="text-secondary text-sm">{methodLabel(v.method)} by {v.actor_name}</span></li>
              ))}
              {d.corrections.length + d.stale_verifications.length === 0 && <li className="text-tertiary text-sm">None.</li>}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
