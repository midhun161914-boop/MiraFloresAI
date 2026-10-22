import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { CheckCircle2, ChevronRight, Circle, XCircle, AlertTriangle, Info, X } from "lucide-react";
import { api, type CheckResult } from "../api/client";
import { AREA_NAME, FindingCard } from "../components/health/FindingCard";
import { RefChip } from "../components/evidence";
import { useReviewWrite } from "../components/review/ReviewPanel";
import { Badge, Button, Callout, Card, EmptyState, ErrorState, FilterGroup, PageHeader, PageSkeleton, Select } from "../ui";
import { fmtMoney } from "../format";

const STATUS_ICON = {
  pass: <CheckCircle2 aria-hidden className="ck ck--pass" />,
  fail: <XCircle aria-hidden className="ck ck--fail" />,
  warn: <AlertTriangle aria-hidden className="ck ck--warn" />,
  info: <Info aria-hidden className="ck ck--info" />,
};
const KIND_LABEL = { reconciliation: "Reconciliations", detector: "Error detectors", independent: "Independent re-computation", completeness: "Completeness" };

function CheckRow({ c }: { c: CheckResult }) {
  const m = c.metrics as Record<string, unknown>;
  const assets = (m.assets as Record<string, unknown>[] | undefined) ?? null;
  return (
    <details className="ck-row">
      <summary className="check__sum">
        {STATUS_ICON[c.status]}
        <span className="check__title">{c.title}</span>
        <span className="check__summary">{c.summary}</span>
        <span className="mono text-tertiary text-xs">{c.id}</span>
        <ChevronRight aria-hidden className="check__chev" />
      </summary>
      <div className="check__body stack-2">
        <p className="text-secondary">{c.description}</p>
        {assets && (
          <table className="mini">
            <thead><tr><th>Asset</th><th>Method</th><th className="num">Fed recomputed</th><th className="num">Fed engine</th><th className="num">CA recomputed</th><th className="num">CA engine</th><th></th></tr></thead>
            <tbody>{assets.map((a) => (
              <tr key={String(a.asset)}><td className="mono">{String(a.asset)}</td><td>{String(a.method)}</td>
                <td className="num">{a.recomputed_federal != null ? fmtMoney(Number(a.recomputed_federal)) : "—"}</td><td className="num">{a.engine_federal != null ? fmtMoney(Number(a.engine_federal)) : "—"}</td>
                <td className="num">{a.recomputed_california != null ? fmtMoney(Number(a.recomputed_california)) : "—"}</td><td className="num">{a.engine_california != null ? fmtMoney(Number(a.engine_california)) : "—"}</td>
                <td>{a.status === "pass" ? <Badge tone="verified">match</Badge> : <Badge tone="neutral">{String(a.status)}</Badge>}</td></tr>
            ))}</tbody>
          </table>
        )}
        {Array.isArray(m.chain) && <ul className="finding__facts">{(m.chain as string[]).map((x, i) => <li key={i}>{x}</li>)}</ul>}
        {!assets && !m.chain && Object.keys(m).length > 0 && !m.items && (
          <pre className="metrics">{JSON.stringify(m, null, 1).slice(0, 1200)}</pre>
        )}
        {c.findings.length > 0 && <span className="text-tertiary text-sm">{c.findings.length} finding(s) — listed under Findings.</span>}
      </div>
    </details>
  );
}

/** Findings, the check suite that produced them, outside filings and the engine's own diagnostics. */
export function FindingsPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "findings";
  const sev = params.get("sev") ?? "";
  const area = params.get("area") ?? "";
  const status = params.get("status") ?? "open";
  const engine = params.get("engine") ?? "";
  const focus = params.get("q") ?? "";
  const q = useQuery({ queryKey: ["checks"], queryFn: api.checks });
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [bulkNote, setBulkNote] = useState("");
  const bulk = useReviewWrite((d: "resolved" | "accepted" | "not_an_issue") => api.bulkDisposition([...picked], d, bulkNote));
  const toggle = (id: string) => setPicked((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const done = { onSuccess: () => { setPicked(new Set()); setBulkNote(""); } };
  const set = (k: string, v: string) => {
    const n = new URLSearchParams(params);
    if (v) n.set(k, v); else n.delete(k);
    setParams(n, { replace: true });
  };
  const list = useMemo(() => (q.data?.findings ?? []).filter((f) => focus ? f.id === focus :
    (!sev || f.severity === sev) && (!area || f.area === area) &&
    (status === "all" || (status === "open" ? f.status === "open" : f.status !== "open")) &&
    (!engine || (engine === "missed" ? !f.engine_diagnostic && f.severity !== "info" : !!f.engine_diagnostic))), [q.data, sev, area, status, engine, focus]);

  if (q.isPending) return <PageSkeleton label="Running the check suite" />;
  if (q.isError) return <div className="page"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>;
  const run = q.data;
  const kinds = ["reconciliation", "detector", "independent", "completeness"] as const;

  return (
    <div className="page">
      <PageHeader title="Checks & findings"
        meta={<span>{run.checks.length} checks run against the packet and the review log (as of event #{run.seq}). Findings are computed, not typed in.</span>} />
      <div className="drawer__tabs tabs-page" role="tablist">
        {[["findings", `Findings · ${run.findings.filter((f) => f.status === "open").length} open`], ["checks", `Check suite · ${run.counts.checks_pass} pass`],
          ["outside", `Outside filings · ${run.outside_filings.length}`], ["engine", `Engine diagnostics · ${run.engine_diagnostics.length}`]].map(([id, label]) => (
          <button key={id} role="tab" type="button" aria-selected={tab === id} className="drawer__tab" onClick={() => set("tab", id === "findings" ? "" : id)}>{label}</button>
        ))}
      </div>

      {tab === "findings" && <>
        <div className="toolbar">
          <FilterGroup label="Severity" selected={[sev]} onToggle={(id) => set("sev", id)}
            items={[{ id: "", label: "All" }, { id: "error", label: "Errors", count: run.findings.filter((f) => f.severity === "error" && f.status === "open").length },
              { id: "warning", label: "Warnings", count: run.findings.filter((f) => f.severity === "warning" && f.status === "open").length }, { id: "info", label: "Info" }]} />
          <FilterGroup label="Status" selected={[status]} onToggle={(id) => set("status", id === "open" ? "" : id)}
            items={[{ id: "open", label: "Open" }, { id: "closed", label: "Dispositioned" }, { id: "all", label: "All" }]} />
          <FilterGroup label="Engine" selected={[engine]} onToggle={(id) => set("engine", id)}
            items={[{ id: "", label: "Any" }, { id: "missed", label: "Engine missed" }, { id: "agrees", label: "Engine agrees" }]} />
          <Select label="Area" value={area} onChange={(v) => set("area", v)}
            options={[{ value: "", label: "All areas" }, ...Object.entries(AREA_NAME).map(([value, label]) => ({ value, label }))]} />
        </div>
        {picked.size > 0 && (
          <div className="bulkbar" role="region" aria-label="Bulk actions">
            <strong>{picked.size} selected</strong>
            <input className="ui-input review__input" placeholder="Decision and why (applies to each)…" value={bulkNote}
              onChange={(e) => setBulkNote(e.target.value)} aria-label="Bulk disposition note" />
            <Button size="sm" variant="primary" disabled={!bulkNote.trim() || bulk.isPending} onClick={() => bulk.mutate("resolved", done)}>Resolve</Button>
            <Button size="sm" disabled={!bulkNote.trim() || bulk.isPending} onClick={() => bulk.mutate("accepted", done)}>Accept</Button>
            <Button size="sm" variant="ghost" disabled={!bulkNote.trim() || bulk.isPending} onClick={() => bulk.mutate("not_an_issue", done)}>Not an issue</Button>
            <Button size="sm" variant="ghost" icon={<X aria-hidden />} onClick={() => setPicked(new Set())}>Clear</Button>
          </div>
        )}
        {bulk.error && <Callout tone="error">Refused by the server: {bulk.error instanceof Error ? bulk.error.message : String(bulk.error)}</Callout>}
        {bulk.data && <Callout tone={bulk.data.refused.length ? "warning" : "neutral"}>
          {bulk.data.bulk_id}: {bulk.data.applied} dispositioned{bulk.data.refused.length > 0 && `, ${bulk.data.refused.length} refused (${bulk.data.refused.map((r) => `${r.item}: ${r.reason}`).join("; ")})`} — undo it from <a href="/activity">Activity</a>.
        </Callout>}
        {focus && <Callout tone="neutral">Showing one finding from search. <button type="button" className="linklike" onClick={() => set("q", "")}>Show all findings</button></Callout>}
        <div className="stack-3">
          {list.length === 0 ? <Card><EmptyState icon={<CheckCircle2 />} title="No findings match" /></Card>
            : list.map((f) => <FindingCard key={f.id} f={f} defaultOpen={list.length <= 3 || !!focus}
                select={f.status === "open" && f.check_id !== "RECON_W2" && f.code !== "INPUTS_INCOMPLETE" ? { checked: picked.has(f.id), onToggle: () => toggle(f.id) } : undefined} />)}
        </div>
      </>}

      {tab === "checks" && (
        <div className="stack-4">
          {kinds.map((k) => (
            <Card key={k} title={KIND_LABEL[k]} flush>
              <div className="checks">{run.checks.filter((c) => c.kind === k).map((c) => <CheckRow key={c.id} c={c} />)}</div>
            </Card>
          ))}
        </div>
      )}

      {tab === "outside" && (
        <Card title="Filings this return triggers outside itself" description="Identified so the client is told in writing who files what, and by when." flush>
          <table className="mini mini--wide">
            <thead><tr><th>Filing</th><th>Required</th><th>Responsible</th><th>Due</th><th>Basis</th><th>Evidence</th></tr></thead>
            <tbody>{run.outside_filings.map((o, i) => (
              <tr key={i}>
                <td><strong>{o.filing}</strong>{!o.in_engagement && <div className="text-tertiary text-xs">outside this engagement</div>}</td>
                <td>{o.required === "yes" ? <Badge tone="warning">Required</Badge> : o.required === "check" ? <Badge tone="open">Confirm</Badge> : <Badge tone="neutral">Not required</Badge>}</td>
                <td>{o.responsible}</td><td className="nowrap">{o.due ?? "—"}</td><td className="text-secondary">{o.basis}</td>
                <td><span className="jt-inline">{o.refs.filter(Boolean).slice(0, 4).map((r) => <RefChip key={r} refId={r} />)}</span></td>
              </tr>
            ))}</tbody>
          </table>
        </Card>
      )}

      {tab === "engine" && (
        <Card title="The engine's own diagnostics" description="Each one is matched to the finding that independently reproduces it, or marked as not independently checked." flush>
          <table className="mini mini--wide">
            <thead><tr><th>Code</th><th>Severity</th><th>Message</th><th>Our finding</th></tr></thead>
            <tbody>{run.engine_diagnostics.map((d) => (
              <tr key={String(d.code)}>
                <td className="mono">{String(d.code)}</td><td><Badge tone={d.severity === "warning" ? "warning" : "neutral"}>{String(d.severity)}</Badge></td>
                <td className="text-secondary">{String(d.message)}</td>
                <td>{(d.covered_by as string[]).length ? <Badge tone="verified" icon={<CheckCircle2 aria-hidden />}>reproduced</Badge> : <Badge tone="neutral" icon={<Circle aria-hidden />}>not independently checked</Badge>}</td>
              </tr>
            ))}</tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
