import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { FileSearch } from "lucide-react";
import { api, type DocumentSummary } from "../api/client";
import { ExtractionBadge } from "../components/evidence";
import { LandingBadge } from "../components/trace/bits";
import type { LandingStatus } from "../api/client";
import { Badge, Button, Card, EmptyState, ErrorState, FilterGroup, PageHeader, SearchInput, Table, type Column } from "../ui";
import { belongsLabel, fmtDate } from "../format";

const FILTERS: { id: string; label: string; test: (d: DocumentSummary) => boolean }[] = [
  { id: "all", label: "All", test: () => true },
  { id: "lands", label: "Lands in return", test: (d) => d.landing_status === "lands" || d.landing_status === "lands_indirectly" },
  { id: "nolanding", label: "Doesn’t land", test: (d) => !(d.landing_status === "lands" || d.landing_status === "lands_indirectly") },
  { id: "superseded", label: "Superseded", test: (d) => d.landing_status === "superseded" },
  { id: "duplicate", label: "Duplicate", test: (d) => d.landing_status === "duplicate" },
  { id: "partial", label: "Not fully extracted", test: (d) => d.extraction.status !== "extracted" },
  { id: "corrected", label: "Corrected", test: (d) => d.marked_corrected },
  { id: "unlocated", label: "Reads not on page", test: (d) => d.unlocated_count > 0 },
  { id: "lowconf", label: "Low confidence", test: (d) => d.low_confidence_count > 0 },
];

export function DocumentsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const filter = params.get("filter") ?? "all";
  const q = params.get("q") ?? "";
  const docs = useQuery({ queryKey: ["documents"], queryFn: api.documents, staleTime: Infinity });
  const ov = useQuery({ queryKey: ["overview"], queryFn: api.overview, staleTime: Infinity });

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v && v !== "all") next.set(k, v); else next.delete(k);
    setParams(next, { replace: true });
  };

  const rows = useMemo(() => {
    const f = FILTERS.find((x) => x.id === filter) ?? FILTERS[0];
    const tokens = q.toLowerCase().split(/\s+/).filter(Boolean);
    return (docs.data ?? []).filter((d) => {
      const hay = `${d.id} ${d.title} ${d.issuer} ${d.document_type} ${d.file_name}`.toLowerCase();
      return f.test(d) && tokens.every((t) => hay.includes(t));
    });
  }, [docs.data, filter, q]);

  const people = ov.data?.people ?? [];
  const columns: Column<DocumentSummary>[] = [
    { id: "id", header: "ID", width: "52px", cell: (d) => <span className="mono">{d.id}</span> },
    { id: "doc", header: "Document", width: "minmax(240px, 4fr)", cell: (d) => (
      <div className="stack-1" style={{ padding: "4px 0" }}>
        <div className="truncate" style={{ fontWeight: 520 }}>{d.title}</div>
        <div className="text-tertiary text-xs truncate">{d.document_type} · {d.issuer}</div>
      </div>
    ) },
    { id: "who", header: "Belongs to", width: "minmax(112px, 1fr)", cell: (d) => <span className="truncate">{belongsLabel(d.belongs_to, people)}</span> },
    { id: "rcvd", header: "Received", width: "96px", cell: (d) => <span className="nowrap text-secondary">{fmtDate(d.received_at)}</span> },
    { id: "pages", header: "Pages", width: "56px", align: "right", cell: (d) => d.page_count },
    { id: "values", header: "Values", width: "60px", align: "right", cell: (d) => d.value_count },
    { id: "ext", header: "Extraction", width: "116px", cell: (d) => <ExtractionBadge status={d.extraction.status} reason={d.extraction.reason} /> },
    { id: "use", header: `Lands in ${ov.data?.current_version ?? "return"}`, width: "124px", cell: (d) => <LandingBadge status={d.landing_status as LandingStatus} lines={d.lines_fed} /> },
    { id: "flags", header: "Flags", width: "minmax(120px, 1fr)", cell: (d) => (
      <span className="row-wrap" style={{ gap: 4 }}>
        {d.marked_corrected && <Badge tone="open">Corrected</Badge>}
        {d.unlocated_count > 0 && <Badge tone="error" title="Reads not found on the printed page">{d.unlocated_count} not on page</Badge>}
        {d.low_confidence_count > 0 && <Badge tone="warning">{d.low_confidence_count} low conf.</Badge>}
      </span>
    ) },
  ];

  return (
    <div className="page">
      <PageHeader title="Documents"
        meta={<span>Everything the client and firm uploaded, with how the pipeline read it and whether the current return uses it.</span>} />
      <div className="toolbar">
        <SearchInput label="Filter documents" value={q} onChange={(v) => set("q", v)} placeholder="Filter by id, title, issuer, type…" />
        <FilterGroup label="Document status" selected={[filter]} onToggle={(id) => set("filter", id)}
          items={FILTERS.map((f) => ({ id: f.id, label: f.label, count: (docs.data ?? []).filter(f.test).length }))} />
      </div>
      {docs.isError ? <Card><ErrorState error={docs.error} onRetry={() => docs.refetch()} /></Card> : (
        <Card flush footer={docs.data ? `${rows.length} of ${docs.data.length} documents` : undefined}>
          <Table label="Documents" columns={columns} rows={rows} rowKey={(d) => d.id} loading={docs.isPending}
            density="default" rowHeight={52} onRowClick={(d) => navigate(`/documents/${d.id}`)}
            empty={<EmptyState icon={<FileSearch />} title="No documents match"
              description="Try a different filter or clear the search."
              action={<Button size="sm" onClick={() => setParams({}, { replace: true })}>Clear filters</Button>} />} />
        </Card>
      )}
    </div>
  );
}
