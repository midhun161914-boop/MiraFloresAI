// The trace drawer: opened by ?trace=KEY on any screen. Number -> documents and
// number -> math (both directions) without leaving where you are.
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Maximize2, X } from "lucide-react";
import { api } from "../../api/client";
import { useTrace } from "../../trace";
import { Badge, Button, ButtonLink, ErrorState, Skeleton } from "../../ui";
import { fmtValue } from "../../format";
import { TraceFacts, TraceMath, TraceSources } from "./sections";
import { ReviewPanel } from "../review/ReviewPanel";
import type { NodeSummary } from "../../api/client";

type Tab = "sources" | "built" | "goes" | "review";

export function TraceDrawer() {
  const { key, version, close } = useTrace();
  const t = useQuery({
    queryKey: ["line", key, version],
    queryFn: () => api.lineTrace(key!, version),
    enabled: !!key,
    staleTime: Infinity,
  });
  const [tab, setTab] = useState<Tab>("sources");
  const summary = useQuery({ queryKey: ["review-summary", version], queryFn: () => api.reviewSummary(version), enabled: !!key });
  const rs: NodeSummary | undefined = key ? summary.data?.[key] : undefined;
  const panel = useRef<HTMLElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);

  // Take focus only when a trace opens (or switches line) — never on later re-renders,
  // which would steal focus from whatever the user is typing in beside the drawer.
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    if (!key) return;
    returnTo.current ??= document.activeElement as HTMLElement;
    panel.current?.focus();
  }, [key]);
  useEffect(() => {
    if (!key) return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.key === "Escape" && !t.closest(".ui-popover") && !["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) closeRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [key]);

  useEffect(() => {
    if (!key) { returnTo.current?.focus?.(); returnTo.current = null; }
  }, [key]);

  // Land on the most useful tab: evidence if the line has any, else the math.
  useEffect(() => {
    if (t.data) setTab(t.data.sources.length ? "sources" : "built");
  }, [t.data?.line.key]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!key) return null;
  const d = t.data;
  const tabs: { id: Tab; label: string }[] = [
    { id: "sources", label: `Evidence${d ? ` · ${d.sources.length}` : ""}` },
    { id: "built", label: d && d.closure_size ? `How it's built · ${d.closure_size}` : "How it's built" },
    { id: "goes", label: `Where it goes${d ? ` · ${d.used_by.length}` : ""}` },
    { id: "review", label: rs?.blocking ? `Review · ${rs.blocking} blocking` : rs?.reopened ? "Review · reopened" : rs?.signed.length ? `Review · ${rs.signed.join(", ")} ✓` : rs?.verified ? "Review · verified" : "Review" },
  ];

  return (
    <aside className="drawer" aria-label={`Trace for ${key}`} ref={panel} tabIndex={-1}>
      <header className="drawer__head">
        <div className="drawer__titles">
          <div className="row">
            <span className="mono drawer__key">{key}</span>
            {d && <Badge tone="outline">{d.version}</Badge>}
            {d && <Badge tone="neutral">{d.line.jurisdiction}</Badge>}
          </div>
          {d ? <h2 className="drawer__label">{d.line.label}</h2> : <Skeleton width={220} height={16} />}
        </div>
        <ButtonLink to={`/lines/${encodeURIComponent(key)}${version ? `?version=${version}` : ""}`} variant="ghost" size="sm"
          icon={<Maximize2 aria-hidden />} aria-label="Open full trace" title="Open full trace" />
        <Button variant="ghost" size="sm" icon={<X aria-hidden />} onClick={close} aria-label="Close trace (Esc)" />
      </header>
      {d && (
        <div className="drawer__figure">
          <span className="drawer__value">{fmtValue(d.line.value)}</span>
          <span className="drawer__rule"><span className="mono">{d.line.rule}</span>{d.rule_text && <> · {d.rule_text}</>}</span>
        </div>
      )}
      <div className="drawer__tabs" role="tablist" aria-label="Trace views">
        {tabs.map((x) => (
          <button key={x.id} type="button" role="tab" id={`dt-${x.id}`} aria-selected={tab === x.id} aria-controls={`dp-${x.id}`}
            className="drawer__tab" onClick={() => setTab(x.id)}>{x.label}</button>
        ))}
      </div>
      <div className="drawer__body" role="tabpanel" id={`dp-${tab}`} aria-labelledby={`dt-${tab}`}>
        {t.isPending && <div className="stack-3">{Array.from({ length: 3 }, (_, i) => <Skeleton key={i} height={88} />)}</div>}
        {t.isError && <ErrorState error={t.error} onRetry={() => t.refetch()} />}
        {d && tab === "sources" && <div className="stack-5"><TraceSources trace={d} /><TraceFacts trace={d} /></div>}
        {d && tab === "built" && <TraceMath lineKey={key} version={version} direction="down" />}
        {d && tab === "goes" && <TraceMath lineKey={key} version={version} direction="up" />}
        {d && tab === "review" && <ReviewPanel node={key} version={version} compact />}
      </div>
    </aside>
  );
}
