import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Clock, Plus, Undo2 } from "lucide-react";
import { api } from "../api/client";
import type { BucketRow, TimeEntry } from "../api/lifecycle";
import { useReviewWrite } from "../components/review/ReviewPanel";
import { useSession } from "../session";
import { Badge, Button, Callout, Card, EmptyState, ErrorState, PageHeader, PageSkeleton, Select, Table, type Column } from "../ui";
import { fmtDateTime } from "../format";

const TONE = { over: "error", near: "warning", under: "verified", not_started: "neutral" } as const;
const LABEL = { over: "Over", near: "Near", under: "Under", not_started: "Not started" } as const;

function Meter({ r }: { r: BucketRow }) {
  return (
    <div className="meter meter--inline" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(100, r.pct)} aria-label={`${r.label}: ${r.pct}% of budget`}>
      <span className={`meter__fill meter__fill--${r.status}`} style={{ width: `${Math.min(100, r.pct)}%` }} />
    </div>
  );
}

/** Time logged against firm.budget_hours, by area. Entries are events; void is the undo. */
export function BudgetPage() {
  const { actor } = useSession();
  const q = useQuery({ queryKey: ["budget"], queryFn: api.budget });
  const [bucket, setBucket] = useState("");
  const [hours, setHours] = useState("");
  const [day, setDay] = useState(new Date().toISOString().slice(0, 10));
  const [note, setNote] = useState("");
  const log = useReviewWrite(() => api.logTime(bucket, Number(hours), day, note));
  const voidIt = useReviewWrite((id: string) => api.voidTime(id));
  if (q.isPending) return <PageSkeleton label="Loading time" />;
  if (q.isError) return <div className="page"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>;
  const b = q.data;
  const cols: Column<BucketRow>[] = [
    { id: "area", header: "Area", width: "minmax(200px, 2fr)", cell: (r) => r.label },
    { id: "budget", header: "Budget", width: "90px", align: "right", cell: (r) => `${r.budget} h` },
    { id: "logged", header: "Logged", width: "90px", align: "right", cell: (r) => <strong>{r.logged} h</strong> },
    { id: "left", header: "Remaining", width: "100px", align: "right", cell: (r) => <span className={r.remaining < 0 ? "up" : ""}>{r.remaining} h</span> },
    { id: "meter", header: "Used", width: "minmax(140px, 1fr)", cell: (r) => <Meter r={r} /> },
    { id: "status", header: "Status", width: "110px", cell: (r) => <Badge tone={TONE[r.status]}>{LABEL[r.status]}{r.status !== "not_started" ? ` · ${r.pct}%` : ""}</Badge> },
    { id: "who", header: "By", width: "minmax(160px, 1.5fr)", cell: (r) => <span className="text-secondary text-sm truncate" style={{ display: "block" }}>{Object.entries(r.by_person).map(([n, h]) => `${n.split(" ")[0]} ${h}h`).join(", ") || "—"}</span> },
  ];
  const ecols: Column<TimeEntry>[] = [
    { id: "date", header: "Date", width: "100px", cell: (e) => <span className="mono text-sm">{e.date}</span> },
    { id: "who", header: "Who", width: "140px", cell: (e) => e.actor_name },
    { id: "area", header: "Area", width: "180px", cell: (e) => b.buckets.find((x) => x.bucket === e.bucket)?.label ?? e.bucket },
    { id: "h", header: "Hours", width: "70px", align: "right", cell: (e) => <span className={e.voided ? "struck" : ""}>{e.hours}</span> },
    { id: "note", header: "What", width: "minmax(200px, 3fr)", cell: (e) => <span className={`truncate${e.voided ? " struck" : ""}`} style={{ display: "block" }} title={e.note}>{e.note}</span> },
    { id: "act", header: "", width: "90px", align: "right", cell: (e) => e.voided ? <Badge tone="neutral">voided</Badge>
      : e.actor === actor?.id ? <Button size="sm" variant="ghost" icon={<Undo2 aria-hidden />} onClick={(ev) => { ev.stopPropagation(); voidIt.mutate(e.id); }}>Void</Button> : null },
  ];
  return (
    <div className="page">
      <PageHeader title="Time & budget"
        meta={<span>{b.total_logged} h logged of {b.total_budget} h budgeted ({b.pct}%) · budget from firm.budget_hours · “near” at 85%</span>} />
      <div className="stack-4">
        <Card title="By area" flush>
          <Table label="Time vs budget by area" columns={cols} rows={b.buckets} rowKey={(r) => r.bucket} />
        </Card>
        <Card title="Log time">
          <div className="review__form">
            <Select label="Area" hideLabel value={bucket} onChange={setBucket}
              options={[{ value: "", label: "Choose an area…" }, ...b.buckets.map((x) => ({ value: x.bucket, label: x.label }))]} />
            <input className="ui-input review__input--short" inputMode="decimal" placeholder="Hours (0.25 steps)" value={hours} onChange={(e) => setHours(e.target.value)} aria-label="Hours" />
            <input className="ui-input review__input--short" type="date" value={day} onChange={(e) => setDay(e.target.value)} aria-label="Date" />
            <input className="ui-input review__input" placeholder="What the time was spent on" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Time note" />
            <Button variant="primary" icon={<Plus aria-hidden />} disabled={!bucket || !hours || !note.trim() || log.isPending}
              onClick={() => log.mutate(undefined, { onSuccess: () => { setHours(""); setNote(""); } })}>Log</Button>
          </div>
          {(log.error || voidIt.error) && <Callout tone="error">Refused by the server: {(log.error ?? voidIt.error)?.message}</Callout>}
        </Card>
        <Card title={`Entries · ${b.entries.length}`} flush>
          <Table label="Time entries" columns={ecols} rows={b.entries} rowKey={(e) => e.id}
            empty={<EmptyState icon={<Clock />} title="No time logged yet" description="Log time above; it counts against the area's budget." />} />
        </Card>
        {b.entries.length > 0 && <p className="text-tertiary text-xs">Last entry {fmtDateTime(b.entries[0].at)}.</p>}
      </div>
    </div>
  );
}
