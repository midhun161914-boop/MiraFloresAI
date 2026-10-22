import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { CheckCheck, SearchX, X } from "lucide-react";
import { api, type LineRow, type NodeSummary } from "../api/client";
import { ReviewBadges } from "../components/review/ReviewBadges";
import { methodLabel, useReviewWrite } from "../components/review/ReviewPanel";
import { useTrace } from "../trace";
import {
  Badge, Button, Callout, Card, EmptyState, ErrorState, FilterGroup, PageHeader, SearchInput, Select, Table, type Column,
} from "../ui";
import { fmtValue } from "../format";

/** Every line of the computed return. One click on any row opens its trace. */
export function ReturnPage() {
  const [params, setParams] = useSearchParams();
  const { open, key: traced } = useTrace();
  const ov = useQuery({ queryKey: ["overview"], queryFn: api.overview, staleTime: Infinity });
  const version = params.get("version") ?? ov.data?.current_version ?? "v3";
  const form = params.get("form") ?? "";
  const q = params.get("q") ?? "";
  const juris = params.get("j") ?? "all";
  const changed = params.get("changed") === "1";

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v && v !== "all") next.set(k, v); else next.delete(k);
    setParams(next, { replace: true });
  };

  const lines = useQuery({
    queryKey: ["lines", version, form, q, juris, changed],
    queryFn: () => api.lines(version, { form, q, jurisdiction: juris === "all" ? undefined : juris, changed }),
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    enabled: !!ov.data,
  });

  const isCurrent = version === ov.data?.current_version;
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [method, setMethod] = useState("agreed_to_source_document");
  const [bulkNote, setBulkNote] = useState("");
  const methods = useQuery({ queryKey: ["methods"], queryFn: api.methods, staleTime: Infinity });
  const bulk = useReviewWrite(() => api.bulkVerify([...selected], method, bulkNote));

  const summary = useQuery({ queryKey: ["review-summary", version], queryFn: () => api.reviewSummary(version), enabled: !!ov.data });
  const rs: Record<string, NodeSummary> = summary.data ?? {};
  const columns: Column<LineRow>[] = useMemo(() => [
    { id: "key", header: "Line", width: "132px", cell: (l) => <span className="mono">{l.key}</span> },
    { id: "label", header: "Description", width: "minmax(260px, 3fr)", cell: (l) => <span className="truncate" style={{ display: "block" }} title={l.label}>{l.label}</span> },
    { id: "value", header: "Amount", width: "140px", align: "right", cell: (l) => l.adjusted_value != null ? (
      <span className="adj-amount" title={`Engine ${fmtValue(l.value)} → adjusted ${fmtValue(l.adjusted_value)} (${l.adjustments.join(", ")})`}>
        {l.rule !== "ADJUSTMENT" && <s>{fmtValue(l.value)}</s>}<strong>{fmtValue(l.adjusted_value)}</strong>
      </span>
    ) : <span className="truncate" style={{ display: "block" }}>{fmtValue(l.value)}</span> },
    { id: "built", header: "Built from", width: "150px", cell: (l) => (
      <span className="text-secondary text-sm nowrap">
        {l.inputs.length > 0 && `${l.inputs.length} line${l.inputs.length === 1 ? "" : "s"}`}
        {l.inputs.length > 0 && l.sources.length > 0 && " · "}
        {l.sources.length > 0 && `${l.sources.length} source${l.sources.length === 1 ? "" : "s"}`}
        {!l.inputs.length && !l.sources.length && <span className="text-tertiary">—</span>}
      </span>
    ) },
    { id: "review", header: "Review", width: "170px", cell: (l) => <ReviewBadges s={rs[l.key]} /> },
    { id: "rule", header: "Rule", width: "minmax(140px, 1fr)", cell: (l) => <span className="mono text-tertiary truncate" style={{ display: "block" }}>{l.rule}</span> },
    { id: "chg", header: "Change", width: "120px", cell: (l) => l.change ? (
      <Badge tone={l.change === "changed" ? "warning" : l.change === "added" ? "open" : "neutral"}
        title={l.change === "changed" ? `Was ${fmtValue(l.previous_value)}` : undefined}>
        {l.change}{l.change === "changed" && l.previous_value != null ? ` from ${fmtValue(l.previous_value)}` : ""}
      </Badge>
    ) : null },
  ], [rs]);

  const versions = ov.data?.versions ?? [];
  const forms = lines.data?.forms ?? [];
  const filtered = !!(form || q || juris !== "all" || changed);

  return (
    <div className="page page--fill">
      <PageHeader title="Return"
        meta={<span>Every computed line. Click any amount to see its evidence and its math.</span>} />
      <div className="toolbar">
        <SearchInput label="Filter lines" value={q} onChange={(v) => set("q", v)} placeholder="Filter by line or description…" />
        <Select label="Version" value={version} onChange={(v) => set("version", v === ov.data?.current_version ? "" : v)}
          options={versions.map((v) => ({ value: v.version, label: `${v.version}${v.is_current ? " · current" : ""}` }))} />
        <Select label="Form" value={form} onChange={(v) => set("form", v)}
          options={[{ value: "", label: "All forms" }, ...forms.map((f) => ({ value: f, label: f }))]} />
        <FilterGroup label="Jurisdiction" selected={[juris]} onToggle={(id) => set("j", id)}
          items={[{ id: "all", label: "All" }, { id: "federal", label: "Federal" }, { id: "california", label: "California" }]} />
        <FilterGroup label="Changed" multi selected={changed ? ["changed"] : []} onToggle={() => set("changed", changed ? "" : "1")}
          items={[{ id: "changed", label: `Changed in ${version}` }]} />
        <span className="toolbar__count">{lines.data ? `${lines.data.total.toLocaleString()} lines` : ""}</span>
      </div>
      {selected.size > 0 && (
        <div className="bulkbar" role="region" aria-label="Bulk actions">
          <strong>{selected.size} selected</strong>
          <Select label="Method" hideLabel value={method} onChange={setMethod}
            options={(methods.data ?? []).map((m) => ({ value: m, label: methodLabel(m) }))} />
          <input className="ui-input review__input" placeholder="Note (optional)" value={bulkNote} onChange={(e) => setBulkNote(e.target.value)} aria-label="Bulk verification note" />
          <Button size="sm" variant="primary" icon={<CheckCheck aria-hidden />} disabled={bulk.isPending}
            onClick={() => bulk.mutate(undefined, { onSuccess: () => { setSelected(new Set()); setBulkNote(""); } })}>Verify {selected.size}</Button>
          <Button size="sm" variant="ghost" icon={<X aria-hidden />} onClick={() => setSelected(new Set())}>Clear</Button>
        </div>
      )}
      {bulk.error && <Callout tone="error">Refused by the server: {bulk.error instanceof Error ? bulk.error.message : String(bulk.error)}</Callout>}
      {bulk.data && (
        <Callout tone={bulk.data.refused.length ? "warning" : "neutral"}>
          {bulk.data.bulk_id}: verified {bulk.data.applied} line{bulk.data.applied === 1 ? "" : "s"}
          {bulk.data.refused.length > 0 && <> · {bulk.data.refused.length} refused ({bulk.data.refused.slice(0, 3).map((r) => `${r.item}: ${r.reason}`).join("; ")}{bulk.data.refused.length > 3 ? "…" : ""})</>}
          {" "}— undo it from <a href="/activity">Activity</a>.
        </Callout>
      )}
      {lines.isError ? <Card><ErrorState error={lines.error} onRetry={() => lines.refetch()} /></Card> : (
        <Card flush className="fill-card">
          <Table label={`Return lines, ${version}`} columns={columns} rows={lines.data?.items ?? []} rowKey={(l) => l.key}
            virtual rowHeight={36} loading={lines.isPending} selectedKey={traced}
            selection={isCurrent ? { selected, onChange: setSelected, canSelect: (l) => l.rule !== "ADJUSTMENT" } : undefined}
            onRowClick={(l) => open(l.key, version === ov.data?.current_version ? undefined : version)}
            empty={<EmptyState icon={<SearchX />} title="No lines match"
              action={filtered ? <Button size="sm" onClick={() => setParams({}, { replace: true })}>Clear filters</Button> : undefined} />} />
        </Card>
      )}
    </div>
  );
}
