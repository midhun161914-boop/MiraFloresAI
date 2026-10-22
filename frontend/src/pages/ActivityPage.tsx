import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Eye, EyeOff, History, Layers, Undo2 } from "lucide-react";
import { api, type EventOut } from "../api/client";
import { RefChip } from "../components/evidence";
import { methodLabel, useReviewWrite } from "../components/review/ReviewPanel";
import { useSession } from "../session";
import { Badge, Button, Callout, Card, EmptyState, ErrorState, FilterGroup, PageHeader, Select, Table, type Column } from "../ui";
import { fmtDateTime, fmtValue } from "../format";

const FILTERS = [
  { id: "", label: "Everything" },
  { id: "verification.", label: "Verifications" },
  { id: "note.", label: "Notes" },
  { id: "signoff.", label: "Sign-offs" },
  { id: "value.", label: "Corrections" },
  { id: "view.", label: "View log" },
  { id: "assignment.", label: "Assignments" },
  { id: "adjustment.", label: "Adjustments" },
  { id: "finding.", label: "Findings" },
];

function describe(e: EventOut): string {
  const p = e.payload as Record<string, unknown>;
  switch (e.type) {
    case "verification.recorded": return `Verified — ${methodLabel(String(p.method))}${p.note ? `: ${p.note}` : ""}`;
    case "verification.withdrawn": return "Withdrew a verification";
    case "note.opened": return `${p.blocking ? "Blocking note" : "Note"}: ${p.text}`;
    case "note.replied": return `Replied: ${p.text}`;
    case "note.resolved": return `Resolved note${p.text ? `: ${p.text}` : ""}`;
    case "note.reopened": return `Reopened note${p.text ? `: ${p.text}` : ""}`;
    case "signoff.recorded": return `Signed off as ${p.level}`;
    case "signoff.withdrawn": return "Withdrew sign-off";
    case "signoff.reopened": return String(p.reason ?? "Sign-off reopened");
    case "value.corrected": return `Corrected ${fmtValue(p.from)} → ${fmtValue(p.to)}: ${p.reason}`;
    case "value.correction_reverted": return `Reverted correction${p.reason ? `: ${p.reason}` : ""}`;
    case "assignment.set": return `Assigned as ${p.role}`;
    case "finding.dispositioned": return `${String(p.disposition).replace(/_/g, " ")}${p.note ? `: ${p.note}` : ""}${p.bulk_id ? ` (${p.bulk_id})` : ""}`;
    case "adjustment.proposed": return `Proposed ${p.adj_id}: ${p.title}${p.requires_partner ? " — needs partner sign-off" : ""}`;
    case "adjustment.approved": return `Approved ${p.adj_id}${p.note ? `: ${p.note}` : ""}`;
    case "adjustment.rejected": return `Rejected ${p.adj_id}${p.note ? `: ${p.note}` : ""}`;
    case "adjustment.reversed": return `Reversed ${p.adj_id}${p.note ? `: ${p.note}` : ""}`;
    case "state.saved": return `Saved state “${p.name}”`;
    case "view.logged": return `${p.masked ? "Viewed masked" : "Viewed unmasked"} sensitive data (${p.endpoint})`;
    default: return e.type;
  }
}

/** Bulk actions are ordinary events sharing a bulk id, so they can be undone as a set. */
function BulkActions() {
  const q = useQuery({ queryKey: ["bulks"], queryFn: api.bulks });
  const undo = useReviewWrite((id: string) => api.undoBulk(id));
  if (!q.data?.length) return null;
  return (
    <Card title="Bulk actions" description="Undo appends reversing events; it never deletes. Each item is checked against the same rule as undoing it singly." flush>
      <table className="mini mini--wide">
        <thead><tr><th>Id</th><th>Action</th><th>By</th><th>When</th><th className="num">Items</th><th>Status</th><th></th></tr></thead>
        <tbody>{q.data.map((b) => (
          <tr key={b.id}>
            <td className="mono">{b.id}</td>
            <td>{b.action === "verify" ? `Verify — ${methodLabel(String(b.params.method ?? ""))}` : `Disposition — ${String(b.params.disposition ?? "").replace(/_/g, " ")}`}</td>
            <td>{b.actor_name}</td><td className="nowrap text-secondary">{fmtDateTime(b.at)}</td>
            <td className="num">{b.count}{b.refused.length > 0 && <span className="text-tertiary"> · {b.refused.length} refused</span>}</td>
            <td>{b.undone ? <Badge tone="neutral">undone{b.undo ? ` by ${String(b.undo.actor_name ?? "")}` : ""}</Badge> : <Badge tone="verified">applied</Badge>}</td>
            <td className="num">{!b.undone && <Button size="sm" variant="ghost" icon={<Undo2 aria-hidden />} disabled={undo.isPending} onClick={() => undo.mutate(b.id)}>Undo</Button>}</td>
          </tr>
        ))}</tbody>
      </table>
      {undo.error && <div style={{ padding: 12 }}><Callout tone="error">Refused by the server: {undo.error instanceof Error ? undo.error.message : String(undo.error)}</Callout></div>}
      {undo.data && <div style={{ padding: 12 }}><Callout tone={undo.data.refused.length ? "warning" : "neutral"}>
        <Layers aria-hidden /> Undid {undo.data.applied} item{undo.data.applied === 1 ? "" : "s"}{undo.data.refused.length > 0 && `; ${undo.data.refused.length} not yours to undo (${undo.data.refused.slice(0, 3).map((r) => r.reason).join("; ")})`}.
      </Callout></div>}
    </Card>
  );
}

/** The audit trail: every event in the store, newest first. */
export function ActivityPage() {
  const [params, setParams] = useSearchParams();
  const type = params.get("type") ?? "";
  const who = params.get("actor") ?? "";
  const { actor, actors } = useSession();
  const q = useQuery({ queryKey: ["events", type, who], queryFn: () => api.events({ type: type || undefined, actor_id: who || undefined, limit: 500 }), placeholderData: keepPreviousData });

  const cols: Column<EventOut>[] = [
    { id: "seq", header: "#", width: "56px", align: "right", cell: (e) => <span className="mono text-tertiary">{e.seq}</span> },
    { id: "at", header: "When", width: "128px", cell: (e) => <span className="nowrap text-secondary">{fmtDateTime(e.at)}</span> },
    { id: "who", header: "Who", width: "170px", cell: (e) => <span className="truncate" style={{ display: "block" }}>{e.actor_name}</span> },
    { id: "kind", header: "Event", width: "170px", cell: (e) => e.type === "view.logged"
      ? <Badge tone={(e.payload as { masked?: boolean }).masked ? "warning" : "neutral"} icon={(e.payload as { masked?: boolean }).masked ? <EyeOff aria-hidden /> : <Eye aria-hidden />}>{(e.payload as { masked?: boolean }).masked ? "masked view" : "unmasked view"}</Badge>
      : <span className="mono text-sm">{e.type}</span> },
    { id: "node", header: "On", width: "150px", cell: (e) => e.node && e.node !== "engagement" && e.node !== "values"
      ? <span onClick={(ev) => ev.stopPropagation()}><RefChip refId={e.node} /></span> : <span className="text-tertiary">{e.node ?? "—"}</span> },
    { id: "what", header: "Detail", width: "minmax(280px, 3fr)", cell: (e) => <span className="truncate" style={{ display: "block" }} title={describe(e)}>{describe(e)}</span> },
  ];

  const canSeeAll = actor && ["firm_administrator", "partner", "quality_reviewer"].includes(actor.role);
  return (
    <div className="page page--fill">
      <PageHeader title="Activity"
        meta={<span>Every workpaper action, as an immutable event. {type === "view." && !canSeeAll && "You see your own view-log entries; administrators, partners and quality reviewers see everyone's."}</span>} />
      <div className="toolbar">
        <FilterGroup label="Event type" selected={[type]} onToggle={(id) => { const n = new URLSearchParams(params); if (id) n.set("type", id); else n.delete("type"); setParams(n, { replace: true }); }} items={FILTERS} />
        <Select label="Person" value={who} onChange={(v) => { const n = new URLSearchParams(params); if (v) n.set("actor", v); else n.delete("actor"); setParams(n, { replace: true }); }}
          options={[{ value: "", label: "Everyone" }, ...(actors ?? []).map((a) => ({ value: a.id, label: a.name }))]} />
        <span className="toolbar__count">{q.data ? `${q.data.items.length} shown · store at #${q.data.last_seq}` : ""}</span>
      </div>
      {!type && !who && <div style={{ marginBottom: 16 }}><BulkActions /></div>}
      {q.isError ? <Card><ErrorState error={q.error} onRetry={() => q.refetch()} /></Card> : (
        <Card flush className="fill-card">
          <Table label="Activity" columns={cols} rows={q.data?.items ?? []} rowKey={(e) => e.id} virtual rowHeight={40}
            loading={q.isPending} empty={<EmptyState icon={<History />} title="Nothing yet" description="Actions appear here as people verify, note, sign and correct." />} />
        </Card>
      )}
    </div>
  );
}
