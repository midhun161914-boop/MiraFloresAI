import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowRight, CalendarClock, CheckCircle2, Circle, Clock, Lock, Snowflake, Users } from "lucide-react";
import { api } from "../api/client";
import { Badge, ButtonLink, Card, ErrorState, PageHeader, PageSkeleton } from "../ui";
import { fmtDateTime } from "../format";

const STAGE_ORDER = ["preparing", "presented", "authorized", "transmitted", "filed"];

/** The return at a glance: lifecycle stage, what blocks the next step, who owns what. */
export function StatusPage() {
  const q = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 20_000 });
  if (q.isPending) return <PageSkeleton label="Loading status" />;
  if (q.isError) return <div className="page"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>;
  const s = q.data;
  const at = Math.max(0, STAGE_ORDER.indexOf(["amending", "amend_ready", "notice"].includes(s.stage) ? "filed" : s.stage));
  const b = s.budget;
  return (
    <div className="page">
      <PageHeader title="Return status" meta={<span>Okafor-Lindqvist · 2025 Form 1040 + 540NR · derived live from the event log</span>} />
      <section className={`status-hero status-hero--${s.blockers ? "blocked" : s.filed_snapshot ? "filed" : "moving"}`} aria-labelledby="stage">
        <div className="status-hero__stage">
          {s.filed_snapshot ? <Snowflake aria-hidden /> : s.blockers ? <Lock aria-hidden /> : <CheckCircle2 aria-hidden />}
          <div>
            <div className="overline">Stage</div>
            <h2 id="stage" className="status-hero__title">{s.stage_label}</h2>
            <p className="text-secondary">{s.headline}</p>
          </div>
        </div>
        {s.next_step && (
          <div className="status-hero__next">
            <div className="overline">Next step</div>
            <div className="status-hero__nextlabel">{s.next_step.label}</div>
            <div className="text-tertiary text-sm">Who: {s.next_step.who}</div>
            <ButtonLink to={s.next_step.link} size="sm" variant="primary" iconRight={<ArrowRight aria-hidden />}>Go</ButtonLink>
          </div>
        )}
      </section>

      <ol className="stepper" aria-label="Lifecycle">
        {["Preparing", "Client approval", "8879 signed", "E-file", "Filed"].map((label, i) => (
          <li key={label} className={`stepper__step${i < at || (i === at && s.filed_snapshot) ? " is-done" : i === at ? " is-current" : ""}`}
            aria-current={i === at ? "step" : undefined}>
            <span className="stepper__dot">{i < at || (i === at && s.filed_snapshot) ? <CheckCircle2 aria-hidden /> : i + 1}</span>{label}
          </li>
        ))}
      </ol>

      <div className="status-grid">
        <Card title="Outstanding" description={s.blockers ? `${s.blockers} item(s) block the next step` : "Nothing blocks the next step"}>
          {s.outstanding.length === 0 ? <p className="text-secondary">All clear.</p> : (
            <ul className="status-list">
              {s.outstanding.map((o) => (
                <li key={o.kind}>
                  <Link to={o.link} className="status-list__row">
                    <span className={`status-count status-count--${o.tone}`}>{o.count}</span>
                    <span>{o.label}</span><ArrowRight aria-hidden className="status-list__go" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {s.blocker_titles.length > 0 && (
            <details className="status-more"><summary>Blocking items</summary>
              <ul className="finding__facts">{s.blocker_titles.map((t) => <li key={t}>{t}</li>)}</ul></details>
          )}
        </Card>

        <Card title="Owners" actions={<Users aria-hidden className="card-icon" />}>
          <dl className="owners">
            {s.owners.map((o) => <div key={o.role + o.name}><dt>{o.role}</dt><dd>{o.name}</dd></div>)}
          </dl>
        </Card>

        <Card title="Milestones">
          <ol className="milestones">
            {s.milestones.map((m) => (
              <li key={m.label} className={m.done ? "is-done" : ""}>
                {m.done ? <CheckCircle2 aria-hidden className="ck ck--pass" /> : <Circle aria-hidden className="ck" />}
                <span>{m.label}</span>
                <span className="text-tertiary text-xs">{m.at ? fmtDateTime(m.at) : ""}{m.who ? ` · ${m.who}` : ""}</span>
              </li>
            ))}
          </ol>
        </Card>

        <Card title="Time vs budget" actions={<Clock aria-hidden className="card-icon" />}>
          <div className="stack-2">
            <div className="row"><strong className="num">{b.total_logged} h</strong><span className="text-secondary">of {b.total_budget} h budgeted</span>
              <span className="spacer" /><Badge tone={b.status === "over" ? "error" : b.status === "near" ? "warning" : "neutral"}>{b.pct}%</Badge></div>
            <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(100, b.pct)} aria-label="Budget used">
              <span className={`meter__fill meter__fill--${b.status}`} style={{ width: `${Math.min(100, b.pct)}%` }} /></div>
            {b.over.length > 0 && <p className="text-sm" style={{ color: "var(--error-fg)" }}>Over budget: {b.over.join(", ")}</p>}
            <Link to="/budget" className="text-sm">Time by area</Link>
          </div>
        </Card>

        <Card title="Deadlines" actions={<CalendarClock aria-hidden className="card-icon" />}>
          <ul className="status-list">
            {s.deadlines.map((d) => (
              <li key={d.what} className="status-list__row status-list__row--static"><span className="mono text-sm nowrap">{d.date ?? "—"}</span><span>{d.what}</span></li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}
