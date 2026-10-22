import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { CheckCircle2 } from "lucide-react";
import { api, type LineRow, type NodeSummary } from "../api/client";
import { FindingCard } from "../components/health/FindingCard";
import { ReviewBadges } from "../components/review/ReviewBadges";
import { LineChip, TraceNumber } from "../components/trace/bits";
import { useTrace } from "../trace";
import { Badge, ButtonLink, Card, EmptyState, ErrorState, PageHeader, PageSkeleton, Table, type Column } from "../ui";
import { fmtAccounting, fmtValue } from "../format";

/** One area of the return: its findings, variances and every line, with review state. */
export function AreaPage() {
  const { areaId = "" } = useParams();
  const { open } = useTrace();
  const h = useQuery({ queryKey: ["health"], queryFn: api.returnHealth });
  const checks = useQuery({ queryKey: ["checks"], queryFn: api.checks });
  const variance = useQuery({ queryKey: ["variance"], queryFn: api.variance });
  const ov = useQuery({ queryKey: ["overview"], queryFn: api.overview, staleTime: Infinity });
  const v = ov.data?.current_version ?? "v3";
  const lines = useQuery({ queryKey: ["lines", v, "", "", "all", false], queryFn: () => api.lines(v), enabled: !!ov.data });
  const summary = useQuery({ queryKey: ["review-summary", undefined], queryFn: () => api.reviewSummary() });

  if (h.isPending) return <PageSkeleton label="Loading area" />;
  if (h.isError) return <div className="page"><ErrorState error={h.error} onRetry={() => h.refetch()} /></div>;
  const a = h.data.areas.find((x) => x.id === areaId);
  if (!a) return <div className="page"><EmptyState title={`No area “${areaId}”`} /></div>;
  const keys = new Set(a.line_keys);
  const rows = (lines.data?.items ?? []).filter((l) => keys.has(l.key));
  const findings = (checks.data?.findings ?? []).filter((f) => f.area === areaId);
  const flags = (variance.data?.flags ?? []).filter((f) => f.area === areaId);
  const rs: Record<string, NodeSummary> = summary.data ?? {};
  const flagSet = new Map(flags.map((f) => [f.line, f]));

  const cols: Column<LineRow>[] = [
    { id: "k", header: "Line", width: "140px", cell: (l) => <span className="mono">{l.key}</span> },
    { id: "l", header: "Description", width: "minmax(240px, 3fr)", cell: (l) => <span className="truncate" style={{ display: "block" }}>{l.label}</span> },
    { id: "v", header: "Amount", width: "120px", align: "right", cell: (l) => fmtValue(l.value) },
    { id: "var", header: "vs 2024", width: "120px", cell: (l) => { const f = flagSet.get(l.key); return f ? <Badge tone={f.explanation ? "neutral" : "warning"}>{f.pct == null ? "from 0" : `${f.pct > 0 ? "+" : ""}${f.pct}%`}</Badge> : null; } },
    { id: "r", header: "Review", width: "170px", cell: (l) => <ReviewBadges s={rs[l.key]} /> },
  ];

  return (
    <div className="page">
      <PageHeader crumbs={[{ label: "Return health", to: "/" }, { label: a.name }]} title={a.name}
        meta={<>
          <span>{a.headline_label}: <TraceNumber lineKey={a.headline_line}><strong>{a.current == null ? "—" : fmtAccounting(a.current)}</strong></TraceNumber></span>
          {a.prior != null && <span className="text-secondary">2024 {fmtAccounting(a.prior)}{a.delta_pct != null && ` (${a.delta_pct > 0 ? "+" : ""}${a.delta_pct}%)`}</span>}
          <span>Owner {a.owner.name}</span>{a.budget_hours != null && <span>{a.budget_hours} h budget</span>}
        </>}
        actions={<ButtonLink to={`/variance?area=${a.id}`} variant="secondary">Variances ({a.variance_flags})</ButtonLink>} />
      <div className="stack-4">
        <Card title={`Findings · ${findings.filter((f) => f.status === "open").length} open`} flush={findings.length === 0}>
          {findings.length === 0 ? <EmptyState icon={<CheckCircle2 />} title="No findings in this area" /> :
            <div className="stack-3">{findings.map((f) => <FindingCard key={f.id} f={f} />)}</div>}
        </Card>
        {flags.length > 0 && (
          <Card title={`Variance flags · ${flags.filter((f) => !f.explanation).length} unexplained`}>
            <div className="row-wrap">{flags.map((f) => (
              <span key={f.line} className="row"><LineChip lineKey={f.line} label={`${f.pct == null ? "from 0" : `${f.pct > 0 ? "+" : ""}${f.pct}%`}`} />{f.explanation && <CheckCircle2 aria-hidden style={{ width: 14, color: "var(--verified-solid)" }} />}</span>
            ))}</div>
          </Card>
        )}
        <Card title={`Lines · ${rows.length}`} flush>
          <Table label={`${a.name} lines`} columns={cols} rows={rows} rowKey={(l) => l.key} loading={lines.isPending}
            onRowClick={(l) => open(l.key)} density="compact"
            virtual={rows.length > 60} rowHeight={36} maxHeight={rows.length > 60 ? 560 : undefined} />
        </Card>
      </div>
    </div>
  );
}
