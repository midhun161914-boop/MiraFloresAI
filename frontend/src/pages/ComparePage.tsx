import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { ArrowRight, Bookmark, ChevronRight, GitCompare } from "lucide-react";
import { api, type LineDiff } from "../api/client";
import { useReviewWrite } from "../components/review/ReviewPanel";
import { RefChip } from "../components/evidence";
import { LineChip } from "../components/trace/bits";
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, PageSkeleton, SearchInput, Select } from "../ui";
import { fmtAccounting, fmtValue } from "../format";

function Delta({ d }: { d: LineDiff }) {
  if (d.delta == null) return <span className="text-tertiary">—</span>;
  return <span className={d.delta > 0 ? "up" : d.delta < 0 ? "down" : ""}>{d.delta > 0 ? "+" : ""}{fmtAccounting(d.delta)}</span>;
}

/** Diff any two states of the return — engine versions, the workpaper now, or saved states. */
export function ComparePage() {
  const [params, setParams] = useSearchParams();
  const a = params.get("a") ?? "v2";
  const b = params.get("b") ?? "v3";
  const [filter, setFilter] = useState("");
  const [name, setName] = useState("");
  const states = useQuery({ queryKey: ["states"], queryFn: api.states });
  const cmp = useQuery({ queryKey: ["compare", a, b], queryFn: () => api.compare(a, b), enabled: a !== b });
  const save = useReviewWrite(() => api.saveState(name));
  const set = (k: string, v: string) => { const n = new URLSearchParams(params); n.set(k, v); setParams(n, { replace: true }); };

  const groups = useMemo(() => {
    const t = filter.toLowerCase().trim();
    return (cmp.data?.groups ?? []).map((g) => ({ ...g, lines: g.lines.filter((d) => !t || `${d.key} ${d.label} ${d.why.join(" ")}`.toLowerCase().includes(t)) }))
      .filter((g) => g.lines.length);
  }, [cmp.data, filter]);

  if (states.isPending) return <PageSkeleton label="Loading states" />;
  if (states.isError) return <div className="page"><ErrorState error={states.error} /></div>;
  const opts = states.data.map((s) => ({ value: s.id, label: `${s.label}${s.detail && s.kind !== "engine" ? ` — ${s.detail}` : ""}` }));
  const c = cmp.data;

  return (
    <div className="page">
      <PageHeader title="Compare versions"
        meta={<span>Engine versions use each version's <span className="mono">changes_from_previous</span> and evidence; workpaper states replay adjustments from the event log as of when they were saved.</span>} />
      <div className="toolbar">
        <Select label="From" value={a} onChange={(v) => set("a", v)} options={opts} />
        <ArrowRight aria-hidden className="cmp__arrow" />
        <Select label="To" value={b} onChange={(v) => set("b", v)} options={opts} />
        <span className="spacer" />
        <input className="ui-input" placeholder="Name this state…" value={name} onChange={(e) => setName(e.target.value)} aria-label="Saved state name" />
        <Button icon={<Bookmark aria-hidden />} disabled={!name.trim() || save.isPending} onClick={() => save.mutate(undefined, { onSuccess: () => setName("") })}>Save current state</Button>
      </div>

      {a === b ? <Card><EmptyState icon={<GitCompare />} title="Pick two different states" /></Card> :
        cmp.isPending ? <PageSkeleton label="Diffing" /> : cmp.isError ? <ErrorState error={cmp.error} /> : c && <>
          <section className="cmp__summary">
            <div className="cmp__stat"><strong>{c.summary.lines_changed as number}</strong><span>changed</span></div>
            <div className="cmp__stat"><strong>{c.summary.lines_added as number}</strong><span>added</span></div>
            <div className="cmp__stat"><strong>{c.summary.lines_removed as number}</strong><span>removed</span></div>
            <div className="cmp__stat"><strong>{c.summary.forms as number}</strong><span>forms</span></div>
            {(c.summary.adjustment_driven as number) > 0 && <div className="cmp__stat"><strong>{c.summary.adjustment_driven as number}</strong><span>from adjustments</span></div>}
            {c.b.detail && <p className="cmp__trigger"><Badge tone="outline">{c.b.label}</Badge> {c.b.detail}</p>}
          </section>

          <Card title="Headline figures" flush>
            <table className="mini mini--wide">
              <thead><tr><th>Line</th><th>Description</th><th className="num">{c.a.label}</th><th className="num">{c.b.label}</th><th className="num">Change</th></tr></thead>
              <tbody>{c.headline.map((h) => {
                const o = h.old as number | null, n = h.new as number | null;
                const d = o != null && n != null ? n - o : null;
                return (<tr key={String(h.key)}><td><LineChip lineKey={String(h.key)} /></td><td>{String(h.label)}</td>
                  <td className="num">{o == null ? "—" : fmtAccounting(o)}</td><td className="num">{n == null ? "—" : fmtAccounting(n)}</td>
                  <td className="num">{d == null ? "—" : d === 0 ? <span className="text-tertiary">no change</span> : <span className={d > 0 ? "up" : "down"}>{d > 0 ? "+" : ""}{fmtAccounting(d)}</span>}</td></tr>);
              })}</tbody>
            </table>
          </Card>

          <div className="toolbar" style={{ marginTop: 16 }}>
            <SearchInput label="Filter changed lines" value={filter} onChange={setFilter} placeholder="Filter by line, description or reason…" />
            <span className="toolbar__count">{groups.reduce((n, g) => n + g.lines.length, 0)} lines in {groups.length} forms</span>
          </div>
          {groups.length === 0 ? <Card><EmptyState title="No differences" /></Card> : (
            <div className="stack-2">
              {groups.map((g) => (
                <details key={g.form} className="cmp__group" open={g.lines.length <= 12 || !!filter}>
                  <summary className="cmp__ghead">
                    <ChevronRight aria-hidden className="check__chev" />
                    <strong className="mono">{g.form}</strong>
                    <span className="text-secondary">{g.lines.length} line{g.lines.length === 1 ? "" : "s"}</span>
                    {g.net != null && <span className="text-tertiary text-sm">net {g.net > 0 ? "+" : ""}{fmtAccounting(g.net)}</span>}
                  </summary>
                  <table className="mini mini--wide cmp__table">
                    <thead><tr><th>Line</th><th>Description</th><th className="num">Old</th><th className="num">New</th><th className="num">Δ</th><th>Why</th></tr></thead>
                    <tbody>{g.lines.map((d) => (
                      <tr key={d.key}>
                        <td className="nowrap"><LineChip lineKey={d.key} />{d.change !== "changed" && <> <Badge tone={d.change === "added" ? "open" : "neutral"}>{d.change}</Badge></>}</td>
                        <td className="cmp__label">{d.label}</td>
                        <td className="num">{d.old == null ? "—" : fmtValue(d.old)}</td>
                        <td className="num"><strong>{d.new == null ? "—" : fmtValue(d.new)}</strong></td>
                        <td className="num"><Delta d={d} /></td>
                        <td className="cmp__why">
                          <ul>{d.why.filter((w) => !w.includes(" trigger: ")).map((w, i) => <li key={i}>{w}</li>)}</ul>
                          {d.refs.length > 0 && <span className="jt-inline">{d.refs.slice(0, 4).map((r) => <RefChip key={r} refId={r} />)}</span>}
                        </td>
                      </tr>
                    ))}</tbody>
                  </table>
                </details>
              ))}
            </div>
          )}
        </>}
    </div>
  );
}
