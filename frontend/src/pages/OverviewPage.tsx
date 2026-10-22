import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { AlertOctagon, AlertTriangle, ArrowDownRight, ArrowUpRight, Bot, ChevronRight, ClipboardCheck, Lock, ShieldCheck, TrendingUp } from "lucide-react";
import { api, type AreaSummary, type VersionSummary } from "../api/client";
import { Avatar } from "../components/evidence";
import { TraceNumber } from "../components/trace/bits";
import { Badge, Card, ErrorState, PageHeader, PageSkeleton, Table, type Column } from "../ui";
import { fmtAccounting, fmtDate, fmtMoney } from "../format";
import { useSession } from "../session";

const VERSION_COLUMNS: Column<VersionSummary>[] = [
  { id: "v", header: "Version", width: "112px", cell: (v) => <span className="row"><strong>{v.version}</strong>{v.is_current && <Badge tone="accent">Current</Badge>}</span> },
  { id: "at", header: "Computed", width: "104px", cell: (v) => <span className="nowrap">{fmtDate(v.computed_at)}</span> },
  { id: "trigger", header: "Trigger", width: "minmax(280px, 1fr)", cell: (v) => <span className="text-secondary">{v.trigger}</span> },
  { id: "tax", header: "Fed tax", width: "88px", align: "right", cell: (v) => fmtMoney(v.summary.federal.total_tax) },
  { id: "due", header: "Fed due", width: "88px", align: "right", cell: (v) => fmtAccounting(v.summary.federal.balance_due) },
  { id: "catax", header: "CA tax", width: "88px", align: "right", cell: (v) => fmtMoney(v.summary.california.total_tax) },
  { id: "cadue", header: "CA due", width: "88px", align: "right", cell: (v) => fmtAccounting(v.summary.california.balance_due) },
];

function Delta({ delta, pct, flagged }: { delta: number | null | undefined; pct: number | null | undefined; flagged?: boolean }) {
  if (delta == null) return <span className="text-tertiary text-sm">no 2024 line</span>;
  const up = delta > 0;
  return (
    <span className={`delta${flagged ? " delta--flag" : ""}`} title={flagged ? "Over the firm's variance threshold (>10% and >$1,000)" : undefined}>
      {up ? <ArrowUpRight aria-hidden /> : <ArrowDownRight aria-hidden />}
      {fmtAccounting(delta)}{pct != null && ` (${pct > 0 ? "+" : ""}${pct}%)`}
      {flagged && <TrendingUp aria-hidden className="delta__flag" />}
    </span>
  );
}

const STATUS = {
  attention: { tone: "error" as const, label: "Needs attention" },
  in_progress: { tone: "warning" as const, label: "In progress" },
  clear: { tone: "verified" as const, label: "Clear" },
};

function AreaCard({ a }: { a: AreaSummary }) {
  const navigate = useNavigate();
  const st = STATUS[a.status];
  return (
    <article className={`area area--${a.status}`} onClick={() => navigate(`/areas/${a.id}`)}
      onKeyDown={(e) => { if (e.key === "Enter") navigate(`/areas/${a.id}`); }} tabIndex={0} aria-label={`${a.name}: ${st.label}`}>
      <header className="area__head">
        <h2 className="area__name">{a.name}</h2>
        <Badge tone={st.tone} dot>{st.label}</Badge>
      </header>
      <div className="area__figure">
        <span className="text-tertiary text-xs">{a.headline_label} · {a.headline_line}</span>
        <span className="area__value" onClick={(e) => e.stopPropagation()}>
          <TraceNumber lineKey={a.headline_line}>{a.current == null ? "—" : fmtAccounting(a.current)}</TraceNumber>
        </span>
        <Delta delta={a.delta} pct={a.delta_pct} flagged={a.headline_flagged} />
      </div>
      <ul className="area__stats">
        <li className={a.findings_error ? "is-bad" : a.findings_warning ? "is-warn" : ""}>
          {a.findings_error ? <AlertOctagon aria-hidden /> : <AlertTriangle aria-hidden />}
          <span>{a.findings_error} error{a.findings_error === 1 ? "" : "s"} · {a.findings_warning} warning{a.findings_warning === 1 ? "" : "s"}</span>
        </li>
        <li className={a.blocking_notes || a.reopened_signoffs ? "is-bad" : ""}>
          <Lock aria-hidden /><span>{a.open_notes} open note{a.open_notes === 1 ? "" : "s"}{a.blocking_notes ? ` (${a.blocking_notes} blocking)` : ""}{a.reopened_signoffs ? ` · ${a.reopened_signoffs} reopened` : ""}</span>
        </li>
        <li className={a.variance_unexplained ? "is-warn" : ""}>
          <TrendingUp aria-hidden /><span>{a.variance_flags} variance flag{a.variance_flags === 1 ? "" : "s"}{a.variance_flags ? ` · ${a.variance_unexplained} unexplained` : ""}</span>
        </li>
        <li>
          <ShieldCheck aria-hidden /><span>{a.verified_lines} of {a.evidence_lines} evidenced lines verified{a.signed_lines ? ` · ${a.signed_lines} signed` : ""}</span>
        </li>
      </ul>
      <footer className="area__foot">
        <span className="row"><Avatar name={a.owner.name} role="preparer" /><span className="text-sm">{a.owner.name}</span></span>
        <span className="text-tertiary text-xs">{a.budget_hours != null ? `${a.budget_hours} h budget · ` : ""}{a.lines} lines</span>
        <ChevronRight aria-hidden className="area__chev" />
      </footer>
    </article>
  );
}

export function OverviewPage() {
  const { actor } = useSession();
  const ov = useQuery({ queryKey: ["overview"], queryFn: api.overview, staleTime: Infinity });
  const h = useQuery({ queryKey: ["health"], queryFn: api.returnHealth, enabled: actor?.kind === "staff" });

  if (ov.isPending || h.isPending) return <PageSkeleton label="Loading return health" />;
  if (ov.isError) return <div className="page"><ErrorState error={ov.error} onRetry={() => ov.refetch()} /></div>;
  if (h.isError) return <div className="page"><ErrorState error={h.error} onRetry={() => h.refetch()} /></div>;
  const o = ov.data;
  const d = h.data;
  const c = d.counts;

  return (
    <div className="page">
      <PageHeader title={o.household_name.split(" - ")[0]}
        meta={<><span>{o.people.map((p) => p.name).join(" · ")}</span><span className="text-tertiary">{o.client_id} · Tax year {o.tax_year} · return {d.version}</span></>} />

      <section className="totals" aria-label="Return totals vs 2024">
        {d.totals.map((t) => {
          const delta = t.current != null && t.prior != null ? t.current - t.prior : null;
          return (
            <div key={t.key} className="totals__item">
              <span className="totals__label">{t.label}</span>
              <TraceNumber lineKey={t.key}><span className="totals__value">{t.current == null ? "—" : fmtAccounting(t.current)}</span></TraceNumber>
              <span className="text-tertiary text-xs">{t.prior != null ? `2024 ${fmtAccounting(t.prior)}${delta != null ? ` · ${delta >= 0 ? "+" : ""}${fmtAccounting(delta)}` : ""}` : t.key}</span>
            </div>
          );
        })}
      </section>

      <section className="healthbar" aria-label="Check suite">
        <Link to="/findings?sev=error" className={`healthbar__item${c.open_errors ? " is-bad" : ""}`}>
          <AlertOctagon aria-hidden /><strong>{c.open_errors}</strong><span>open errors</span>
        </Link>
        <Link to="/findings?sev=warning" className={`healthbar__item${c.open_warnings ? " is-warn" : ""}`}>
          <AlertTriangle aria-hidden /><strong>{c.open_warnings}</strong><span>open warnings</span>
        </Link>
        <Link to="/findings?engine=missed" className="healthbar__item">
          <Bot aria-hidden /><strong>{c.engine_missed}</strong><span>the engine missed</span>
        </Link>
        <Link to="/variance" className={`healthbar__item${c.variance_unexplained ? " is-warn" : ""}`}>
          <TrendingUp aria-hidden /><strong>{c.variance_unexplained}</strong><span>of {c.variance_flags} variances unexplained</span>
        </Link>
        <Link to="/findings?tab=checks" className="healthbar__item">
          <ClipboardCheck aria-hidden /><strong>{c.checks_pass}/{c.checks_pass + c.checks_fail + c.checks_warn + c.checks_info}</strong><span>checks pass</span>
        </Link>
      </section>

      <div className="areas" role="list" aria-label="Areas">
        {d.areas.map((a) => <div role="listitem" key={a.id}><AreaCard a={a} /></div>)}
      </div>

      <div className="overview-grid" style={{ marginTop: 24 }}>
        <Card title="Return versions" description="Engine output at three moments; the workpaper's own changes are tracked against these." flush>
          <Table label="Return versions" columns={VERSION_COLUMNS} rows={o.versions} rowKey={(v) => v.version}
            rowClassName={(v) => (v.is_current ? "ui-table__row--tone-current" : undefined)} density="default" />
        </Card>
        <Card title="Packet integrity" actions={<Badge tone="verified" icon={<ShieldCheck aria-hidden />}>Verified</Badge>}>
          <dl className="ui-dl">
            <dt>Documents</dt><dd className="tabular">{o.counts.documents}</dd>
            <dt>Extracted values</dt><dd className="tabular">{o.counts.extracted_values.toLocaleString()}</dd>
            <dt>Return versions</dt><dd className="tabular">{o.counts.return_versions}</dd>
            <dt>SHA-256</dt><dd className="hash">{o.packet_sha256}</dd>
          </dl>
        </Card>
      </div>
    </div>
  );
}
