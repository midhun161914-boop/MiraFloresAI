import { useMemo } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { SearchX } from "lucide-react";
import { api, type ValueOut } from "../api/client";
import { MatchBadge } from "../components/evidence";
import { LineChip } from "../components/trace/bits";
import {
  Badge, Button, Card, ConfidenceMeter, EmptyState, ErrorState, FilterGroup, PageHeader, SearchInput, Select, Table, type Column,
} from "../ui";
import { fmtValue } from "../format";

const TYPES = ["money", "date", "text", "integer", "quantity", "percent", "boolean", "code", "ssn", "ein", "account_number"];
const MATCHES = [
  { id: "not_found", label: "Not on page" },
  { id: "ambiguous", label: "Repeated" },
  { id: "empty", label: "Blank" },
  { id: "exact", label: "On page" },
];

const COLUMNS: Column<ValueOut>[] = [
  { id: "id", header: "ID", width: "76px", cell: (v) => <span className="mono">{v.id}</span> },
  { id: "doc", header: "Source", width: "84px", cell: (v) => <span className="mono" title={v.document_title}>{v.document_id} p.{v.page}</span> },
  { id: "label", header: "Field", width: "minmax(220px, 2fr)", cell: (v) => <span className="truncate" title={`${v.label} (${v.field})`} style={{ display: "block" }}>{v.label}</span> },
  { id: "read", header: "Text as read", width: "minmax(140px, 1.2fr)", cell: (v) => (
    <span className="row"><span className="mono truncate">{v.text_as_read || "—"}</span>{v.redacted && <Badge tone="warning">masked</Badge>}</span>
  ) },
  { id: "value", header: "Value", width: "minmax(110px, 1fr)", align: "right", cell: (v) => <span className="truncate" style={{ display: "block" }}>{fmtValue(v.value, v.value_type)}</span> },
  { id: "feeds", header: "Feeds", width: "132px", cell: (v) => v.lands_in.length ? (
    <span className="row" onClick={(e) => e.stopPropagation()}>
      <LineChip lineKey={v.lands_in[0]} />{v.lands_in.length > 1 && <span className="text-tertiary text-xs">+{v.lands_in.length - 1}</span>}
    </span>
  ) : <span className="text-tertiary text-sm">—</span> },
  { id: "match", header: "Printed page", width: "116px", cell: (v) => (
    <MatchBadge status={v.match.status} normalized={v.match.normalized} matched={v.match.matched_text} candidates={v.match.candidates} />
  ) },
  { id: "conf", header: "Confidence", width: "96px", cell: (v) => <ConfidenceMeter value={v.confidence} /> },
];

export function ValuesPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const q = params.get("q") ?? "";
  const doc = params.get("doc") ?? "";
  const types = params.get("types") ?? "";
  const match = params.get("match") ?? "";
  const max = params.get("max") ?? "";
  const sort = (params.get("sort") ?? "id") as "id" | "confidence" | "document";

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v); else next.delete(k);
    setParams(next, { replace: true });
  };
  const toggle = (k: string, current: string, item: string) => {
    const s = new Set(current ? current.split(",") : []);
    if (s.has(item)) s.delete(item); else s.add(item);
    set(k, [...s].join(","));
  };

  const docs = useQuery({ queryKey: ["documents"], queryFn: api.documents, staleTime: Infinity });
  const values = useQuery({
    queryKey: ["values", { q, doc, types, match, max, sort }],
    queryFn: () => api.values({
      q, document_id: doc, value_type: types, match, sort, limit: 5000,
      max_confidence: max ? Number(max) : undefined,
    }),
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  });

  const items = values.data?.items ?? [];
  const docOptions = useMemo(() => [
    { value: "", label: "All documents" },
    ...(docs.data ?? []).filter((d) => d.value_count > 0).map((d) => ({ value: d.id, label: `${d.id} · ${d.title}` })),
  ], [docs.data]);
  const filtered = !!(q || doc || types || match || max);

  return (
    <div className="page page--fill">
      <PageHeader title="Extracted values"
        meta={<span>What the pipeline read — it can be wrong. Each value opens highlighted on its source page.</span>} />
      <div className="toolbar">
        <SearchInput label="Search values" value={q} onChange={(v) => set("q", v)} placeholder="Search id, field, label, text read…" />
        <Select label="Document" hideLabel value={doc} onChange={(v) => set("doc", v)} options={docOptions} />
        <Select label="Confidence" value={max} onChange={(v) => set("max", v)} options={[
          { value: "", label: "Any" }, { value: "0.5", label: "≤ 50%" }, { value: "0.8", label: "≤ 80%" },
          { value: "0.9", label: "≤ 90%" }, { value: "0.95", label: "≤ 95%" },
        ]} />
        <Select label="Sort" value={sort} onChange={(v) => set("sort", v === "id" ? "" : v)} options={[
          { value: "id", label: "ID" }, { value: "confidence", label: "Lowest confidence" }, { value: "document", label: "Document & page" },
        ]} />
        {filtered && <Button variant="ghost" size="sm" onClick={() => setParams({}, { replace: true })}>Clear all</Button>}
      </div>
      <div className="toolbar">
        <FilterGroup label="Printed page" multi selected={match.split(",").filter(Boolean)} onToggle={(id) => toggle("match", match, id)}
          items={MATCHES} />
        <span className="topbar__divider" style={{ marginLeft: 0 }} aria-hidden />
        <FilterGroup label="Value type" multi selected={types.split(",").filter(Boolean)} onToggle={(id) => toggle("types", types, id)}
          items={TYPES.map((t) => ({ id: t, label: t.replace("_", " ") }))} />
        <span className="toolbar__count" aria-live="polite">
          {values.isPending ? "Loading…" : `${items.length.toLocaleString()} of 3,012`}{values.isFetching && !values.isPending ? " · updating" : ""}
        </span>
      </div>

      {values.isError ? <Card><ErrorState error={values.error} onRetry={() => values.refetch()} /></Card> : (
        <Card flush className="fill-card">
          <Table label="Extracted values" columns={COLUMNS} rows={items} rowKey={(v) => v.id} virtual rowHeight={36}
            loading={values.isPending}
            onRowClick={(v) => navigate(`/documents/${v.document_id}?page=${v.page}&ev=${v.id}`)}
            empty={<EmptyState icon={<SearchX />} title="No values match these filters"
              action={<Button size="sm" onClick={() => setParams({}, { replace: true })}>Clear filters</Button>} />} />
        </Card>
      )}
    </div>
  );
}
