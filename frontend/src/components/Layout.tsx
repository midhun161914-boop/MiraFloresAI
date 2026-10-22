import { useEffect } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertOctagon, Bell, CheckCircle2, ClipboardCheck, FileText, FlaskConical, GitCompare, History, Gauge, Clock, Forward, Mail, Send, Snowflake, FilePlus2, LayoutDashboard, Lock, Scale, ShieldCheck, Sigma, Table2, TrendingUp } from "lucide-react";
import { api } from "../api/client";
import { ClientPortal } from "../pages/ClientPortal";
import { useSession } from "../session";
import { useTrace } from "../trace";
import { GlobalSearch } from "./GlobalSearch";
import { RoleSwitcher } from "./RoleSwitcher";
import { TraceDrawer } from "./trace/TraceDrawer";

function Brand() {
  return (
    <div className="topbar__brand">
      <span className="brand-mark" aria-hidden>
        <svg viewBox="0 0 16 16" width="14" height="14"><path d="M3 12V4l5 5 5-5v8" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </span>
      <span className="brand-word">Miraflores</span>
    </div>
  );
}

/** Filing readiness, always visible: open blocking notes and reopened sign-offs. */
function ReadinessChip() {
  const r = useQuery({ queryKey: ["readiness"], queryFn: api.readiness, refetchInterval: 15_000 });
  if (!r.data) return null;
  const n = r.data.blockers.length;
  return (
    <Link to="/review" className={`readiness${n ? " readiness--blocked" : ""}`}
      title={n ? r.data.blockers.map((b) => b.title).join("\n") : "No open blocking notes or reopened sign-offs"}>
      {n ? <Lock aria-hidden /> : <CheckCircle2 aria-hidden />}
      {n ? `${n} filing blocker${n === 1 ? "" : "s"}` : "No blockers"}
    </Link>
  );
}

/** Once filed, every screen says so: the return is frozen; changes go into an amendment. */
function FrozenChip() {
  const f = useQuery({ queryKey: ["filing"], queryFn: api.filing, refetchInterval: 30_000 });
  if (!f.data?.filed) return null;
  return (
    <Link to="/filing" className="frozen-banner" title={`Accepted ${f.data.filed.accepted_at.slice(0, 10)} — snapshot ${f.data.filed.snapshot_hash}`}>
      <Snowflake aria-hidden />Filed · frozen
    </Link>
  );
}

/** "What changed since I last looked" — count of other people's events after this user's seen mark. */
function DigestBell() {
  const { actor } = useSession();
  const d = useQuery({ queryKey: ["digest", actor?.id], queryFn: api.digest, refetchInterval: 15_000 });
  const n = d.data?.count ?? 0;
  const label = n ? `${n} change${n === 1 ? "" : "s"} by others since you last looked` : "Nothing new since you last looked";
  return (
    <Link to="/whats-new" className={`digest-bell${n ? " digest-bell--new" : ""}`} aria-label={label} title={label}>
      <Bell aria-hidden />{n > 0 && <span className="digest-bell__count">{n > 99 ? "99+" : n}</span>}
    </Link>
  );
}

/** On every route change: move focus to the main region (so keyboard and screen-reader
 *  users land on the new screen, not on the link they left) and title the tab after
 *  the page heading. Query-string changes (filters, the trace drawer) don't count. */
function useRouteFocus() {
  const { pathname } = useLocation();
  useEffect(() => {
    const t = window.setTimeout(() => {
      const main = document.getElementById("main");
      const h1 = main?.querySelector("h1");
      document.title = h1?.textContent ? `${h1.textContent} · Miraflores` : "Miraflores Workpaper";
      if (main && !main.contains(document.activeElement)) main.focus({ preventScroll: true });
    }, 60);
    return () => window.clearTimeout(t);
  }, [pathname]);
}

export function Layout() {
  useRouteFocus();
  const { actor } = useSession();
  const { key: traceKey } = useTrace();
  const staff = actor?.kind === "staff";
  const ov = useQuery({ queryKey: ["overview"], queryFn: api.overview, staleTime: Infinity, enabled: staff });
  const o = ov.data;
  const health = useQuery({ queryKey: ["health"], queryFn: api.returnHealth, enabled: staff }).data;

  // Client users get the client surface only; the server refuses firm endpoints for them anyway.
  if (actor && !staff) {
    return (
      <div className="shell shell--client">
        <a className="skip-link" href="#main">Skip to content</a>
        <header className="topbar">
          <Brand />
          <span className="topbar__divider" aria-hidden />
          <span className="eng-name">Client portal</span>
          <span className="spacer" />
          <RoleSwitcher />
        </header>
        <main id="main" className="main" tabIndex={-1}><ClientPortal /></main>
      </div>
    );
  }

  return (
    <div className={`shell${traceKey ? " shell--drawer" : ""}`}>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="topbar">
        <Brand />
        <span className="topbar__divider" aria-hidden />
        <div className="topbar__engagement" aria-label="Engagement">
          {o ? (
            <>
              <span className="eng-name">{o.household_name.split(" - ")[0]}</span>
              <span className="eng-meta">{o.client_id} · {o.tax_year} Form 1040 · {o.filing_status === "married_filing_jointly" ? "MFJ" : o.filing_status}</span>
            </>
          ) : <span className="eng-meta">Loading engagement…</span>}
        </div>
        <div className="topbar__search"><GlobalSearch /></div>
        {staff && <ReadinessChip />}
        {staff && <FrozenChip />}
        {staff && <DigestBell />}
        <RoleSwitcher />
      </header>

      <nav className="sidenav" aria-label="Workpaper">
        <div className="sidenav__label overline">Workpaper</div>
        <NavLink to="/status" className="navitem"><Gauge aria-hidden /><span>Status</span></NavLink>
        <NavLink to="/" end className="navitem"><LayoutDashboard aria-hidden /><span>Return health</span></NavLink>
        <NavLink to="/return" className="navitem">
          <Sigma aria-hidden /><span>Return</span>
          {o && <span className="navitem__count">{o.current_version}</span>}
        </NavLink>
        <NavLink to="/documents" className="navitem">
          <FileText aria-hidden /><span>Documents</span>
          {o && <span className="navitem__count">{o.counts.documents}</span>}
        </NavLink>
        <NavLink to="/values" className="navitem">
          <Table2 aria-hidden /><span>Extracted values</span>
          {o && <span className="navitem__count">{o.counts.extracted_values.toLocaleString()}</span>}
        </NavLink>
        <div className="sidenav__label overline">Checks</div>
        <NavLink to="/findings" className="navitem">
          <AlertOctagon aria-hidden /><span>Checks & findings</span>
          {health && <span className={`navitem__count${health.counts.open_errors ? " navitem__count--bad" : ""}`}>{health.counts.open_errors + health.counts.open_warnings}</span>}
        </NavLink>
        <NavLink to="/variance" className="navitem">
          <TrendingUp aria-hidden /><span>Variance vs 2024</span>
          {health && <span className="navitem__count">{health.counts.variance_unexplained}</span>}
        </NavLink>
        <div className="sidenav__label overline">Change</div>
        <NavLink to="/adjustments" className="navitem"><Scale aria-hidden /><span>Adjustments</span></NavLink>
        <NavLink to="/compare" className="navitem"><GitCompare aria-hidden /><span>Compare versions</span></NavLink>
        <NavLink to="/whatif" className="navitem"><FlaskConical aria-hidden /><span>What-ifs</span></NavLink>
        <div className="sidenav__label overline">Filing & after</div>
        <NavLink to="/filing" className="navitem"><Send aria-hidden /><span>Filing</span></NavLink>
        <NavLink to="/amend" className="navitem"><FilePlus2 aria-hidden /><span>Amendments</span></NavLink>
        <NavLink to="/notices" className="navitem"><Mail aria-hidden /><span>Notices</span></NavLink>
        <NavLink to="/carryforward" className="navitem"><Forward aria-hidden /><span>Carry forward</span></NavLink>
        <div className="sidenav__label overline">Review</div>
        <NavLink to="/review" className="navitem"><ClipboardCheck aria-hidden /><span>Review queue</span></NavLink>
        <NavLink to="/activity" className="navitem"><History aria-hidden /><span>Activity & view log</span></NavLink>
        <NavLink to="/budget" className="navitem"><Clock aria-hidden /><span>Time & budget</span></NavLink>
        <div className="sidenav__foot">
          {o && (
            <div className="sidenav__status" title={`Packet SHA-256 ${o.packet_sha256}`}>
              <ShieldCheck aria-hidden />
              <div>
                <div>Packet verified</div>
                <div className="text-tertiary text-xs">Return {o.current_version} · current</div>
              </div>
            </div>
          )}
        </div>
      </nav>

      <main id="main" className="main" tabIndex={-1}>
        <Outlet />
      </main>
      <TraceDrawer />
    </div>
  );
}
