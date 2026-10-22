import { useQuery } from "@tanstack/react-query";
import { BellOff, CheckCheck } from "lucide-react";
import { api } from "../api/client";
import { RefChip } from "../components/evidence";
import { useReviewWrite } from "../components/review/ReviewPanel";
import { useSession } from "../session";
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, PageSkeleton } from "../ui";
import { fmtDateTime } from "../format";

/** What changed since *you* last looked — other people's actions after your last "seen" mark. */
export function WhatsNewPage() {
  const { actor } = useSession();
  const q = useQuery({ queryKey: ["digest", actor?.id], queryFn: api.digest });
  const seen = useReviewWrite((seq: number | undefined) => api.markSeen(seq));
  if (q.isPending) return <PageSkeleton label="Checking what's new" />;
  if (q.isError) return <div className="page"><ErrorState error={q.error} /></div>;
  const d = q.data;
  return (
    <div className="page">
      <PageHeader title="What's new for you"
        meta={<span>{d.count} change{d.count === 1 ? "" : "s"} by others since your last look (event #{d.last_seen_seq}; the log is at #{d.current_seq}). Your own actions and view-log entries are left out.</span>}
        actions={<Button variant="primary" icon={<CheckCheck aria-hidden />} disabled={seen.isPending || d.count === 0}
          onClick={() => seen.mutate(d.current_seq)}>Mark all as seen</Button>} />
      {Object.keys(d.by_type).length > 0 && (
        <div className="row-wrap" style={{ marginBottom: 16 }}>
          {Object.entries(d.by_type).map(([k, n]) => <Badge key={k} tone="outline">{n} {k}</Badge>)}
        </div>
      )}
      <Card flush>
        {d.count === 0 ? <EmptyState icon={<BellOff />} title="You're up to date" description="Nothing has changed since you last looked." /> : (
          <ol className="news">
            {d.items.map((it) => (
              <li key={String(it.seq)} className="news__item">
                <span className="mono text-tertiary">#{String(it.seq)}</span>
                <span className="news__who">{String(it.actor_name)}</span>
                <span className="news__text">{String(it.text)}</span>
                {(() => { const n = String(it.node ?? ""); return n && n !== "engagement" && !n.includes(":") ? <RefChip refId={n} /> : null; })()}
                <span className="text-tertiary text-xs nowrap">{fmtDateTime(String(it.at))}</span>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}
