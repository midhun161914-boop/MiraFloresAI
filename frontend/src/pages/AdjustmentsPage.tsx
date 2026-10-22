import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Scale } from "lucide-react";
import { api } from "../api/client";
import { AdjustmentCard } from "../components/changes/AdjustmentCard";
import { Card, EmptyState, ErrorState, FilterGroup, PageHeader, PageSkeleton } from "../ui";

/** Every adjustment to the return: proposed, awaiting a partner, active, rejected or reversed. */
export function AdjustmentsPage() {
  const [params, setParams] = useSearchParams();
  const show = params.get("show") ?? "";
  const q = useQuery({ queryKey: ["adjustments"], queryFn: api.adjustments });
  if (q.isPending) return <PageSkeleton label="Loading adjustments" />;
  if (q.isError) return <div className="page"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>;
  const all = q.data;
  const rows = all.filter((a) => !show || a.status === show);
  const count = (s: string) => all.filter((a) => a.status === s).length;
  const threshold = all[0]?.threshold ?? 1000;
  return (
    <div className="page">
      <PageHeader title="Adjustments"
        meta={<span>Changes to return values. The engine's value is preserved beside each one. Firm rule: tax effect over ${threshold.toLocaleString()} (federal or state) needs partner sign-off — enforced by the server; pending ones block filing. Totals are not recomputed (the engine can't be rerun); the tax effect uses the packet's tax_effect_rates.</span>} />
      <div className="toolbar">
        <FilterGroup label="Status" selected={[show]} onToggle={(id) => setParams(id ? { show: id } : {}, { replace: true })}
          items={[{ id: "", label: "All", count: all.length }, { id: "pending_partner", label: "Awaiting partner", count: count("pending_partner") },
            { id: "active", label: "Active", count: count("active") }, { id: "reversed", label: "Reversed", count: count("reversed") },
            { id: "rejected", label: "Rejected", count: count("rejected") }]} />
      </div>
      {rows.length === 0 ? (
        <Card><EmptyState icon={<Scale />} title="No adjustments"
          description="Propose one from a finding's computed fix (Checks & findings), or adjust a line from its trace." /></Card>
      ) : <div className="stack-3">{rows.map((a) => <AdjustmentCard key={a.id} a={a} />)}</div>}
    </div>
  );
}
