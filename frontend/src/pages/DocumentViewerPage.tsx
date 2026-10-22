import { useEffect, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";
import { MousePointerClick } from "lucide-react";
import { api, type ValueOut } from "../api/client";
import { CopyRef, ExtractionBadge, MatchBadge } from "../components/evidence";
import { LandingBadge, LineChip } from "../components/trace/bits";
import { LandingView } from "../components/trace/LandingView";
import { ReviewPanel } from "../components/review/ReviewPanel";
import { PageSurface } from "../components/PageSurface";
import { PrintedText } from "../components/PrintedText";
import {
  Badge, Callout, Card, ConfidenceMeter, EmptyState, ErrorState, PageHeader, PageSkeleton, Panel, PanelSection,
} from "../ui";
import { belongsLabel, fmtDate, fmtValue } from "../format";

export function DocumentViewerPage() {
  const { docId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const doc = useQuery({ queryKey: ["document", docId], queryFn: () => api.document(docId), staleTime: Infinity });
  const ov = useQuery({ queryKey: ["overview"], queryFn: api.overview, staleTime: Infinity });

  const selectedId = params.get("ev");
  const view = params.get("view") === "landing" ? "landing" : "pages";
  const selected = doc.data?.values.find((v) => v.id === selectedId) ?? null;
  // A deep link with ?ev= but no page lands on that value's page.
  const page = Number(params.get("page")) || selected?.page || 1;

  const pageValues = useMemo(() => (doc.data?.values ?? []).filter((v) => v.page === page), [doc.data, page]);
  const perPage = useMemo(() => {
    const m = new Map<number, ValueOut[]>();
    for (const v of doc.data?.values ?? []) m.set(v.page, [...(m.get(v.page) ?? []), v]);
    return m;
  }, [doc.data]);

  const select = (id: string | null, toPage = page) => {
    const next = new URLSearchParams(params);
    next.set("page", String(toPage));
    next.delete("view");
    if (id) next.set("ev", id); else next.delete("ev");
    setParams(next, { replace: true });
  };
  const setView = (v: "pages" | "landing") => {
    const next = new URLSearchParams(params);
    if (v === "landing") next.set("view", "landing"); else next.delete("view");
    setParams(next, { replace: true });
  };

  if (doc.isPending) return <PageSkeleton label={`Loading ${docId}`} />;
  if (doc.isError) return <div className="page"><ErrorState error={doc.error} onRetry={() => doc.refetch()} /></div>;
  const d = doc.data;
  const pg = d.pages[page - 1];
  if (!pg) return <div className="page"><ErrorState title="Page not found" error={`${d.id} has ${d.page_count} page(s); there is no page ${page}.`} /></div>;
  const version = ov.data?.current_version;

  return (
    <div className="viewer">
      <div className="viewer__head">
        <PageHeader
          crumbs={[{ label: "Documents", to: "/documents" }, { label: d.id }]}
          title={d.title}
          meta={<>
            <span>{d.document_type}</span>
            <span>{d.issuer}</span>
            <span>{belongsLabel(d.belongs_to, ov.data?.people)}</span>
            <span>Received {fmtDate(d.received_at)} · {d.uploaded_by}</span>
            <span className="mono text-tertiary">{d.file_name}</span>
          </>}
        />
        <div className="viewer__flags">
          <ExtractionBadge status={d.extraction.status} reason={d.extraction.reason} />
          <Badge tone="outline">{d.value_count} values · {d.page_count} {d.page_count === 1 ? "page" : "pages"}</Badge>
          <LandingBadge status={d.landing_status as never} lines={d.lines_fed}
            title={d.current_use === "superseded" ? `Superseded in ${version}` : undefined} />
          {d.marked_corrected && <Badge tone="open">Issuer marked CORRECTED</Badge>}
          {d.redacted && <Badge tone="warning">Identifiers masked for your role</Badge>}
          {d.extraction.reason && <span className="text-tertiary text-sm">{d.extraction.reason}</span>}
        </div>
        <div className="viewer__tabs" role="tablist" aria-label="Document views">
          <button type="button" role="tab" aria-selected={view === "pages"} className="drawer__tab" onClick={() => setView("pages")}>
            Source pages
          </button>
          <button type="button" role="tab" aria-selected={view === "landing"} className="drawer__tab" onClick={() => setView("landing")}>
            Where it landed{d.lines_fed ? ` · ${d.lines_fed} line${d.lines_fed === 1 ? "" : "s"}` : ""}
          </button>
        </div>
      </div>

      {view === "landing" ? (
        <div className="viewer__landing"><div className="viewer__column viewer__column--wide"><LandingView docId={d.id} /></div></div>
      ) : (

      <div className="viewer__body">
        <nav className="page-rail" aria-label="Pages">
          {d.pages.map((p) => {
            const vs = perPage.get(p.page) ?? [];
            const alert = vs.some((v) => v.match.status === "not_found");
            return (
              <button key={p.page} type="button"
                className={`page-tab${vs.length === 0 ? " page-tab--unread" : ""}`}
                aria-current={p.page === page ? "page" : undefined}
                aria-label={`Page ${p.page}, ${vs.length ? `${vs.length} values` : "not read by the pipeline"}${alert ? ", has reads not on page" : ""}`}
                onClick={() => select(null, p.page)}>
                <span>{p.page}</span>
                <span className="page-tab__n">{vs.length || "—"}</span>
                {alert && <span className="page-tab__alert" aria-hidden />}
              </button>
            );
          })}
        </nav>

        <section className="viewer__main" aria-label={`Page ${page} of ${d.page_count}`}>
          <div className="viewer__column">
            {d.current_use === "superseded" && (
              <Callout tone="error">Superseded in {version}: figures on this document must not flow into the return.</Callout>
            )}
            <Card title={`Printed content · page ${page} of ${d.page_count}`}
              actions={<Badge tone="outline">Ground truth</Badge>}>
              <div className="stack-3">
                {pageValues.length === 0 && (
                  <Callout tone="warning">The pipeline did not read this page. Anything printed here is not in the extracted values.</Callout>
                )}
                <PrintedText text={pg.printed_content} values={pageValues} selectedId={selectedId} onSelect={(id) => select(id)} />
              </div>
            </Card>
            <Card title="Field layout" description="Reconstructed from the pipeline's field positions — the packet has no page images. A real scan drops in behind the same overlay.">
              <PageSurface values={pageValues} selectedId={selectedId} onSelect={(id) => select(id)} pageLabel={`${d.id} page ${page}`} />
            </Card>
          </div>
        </section>

        <Panel title="Evidence" subtitle={`${d.id} · page ${page}`} aria-label="Evidence on this page">
          <PanelSection title="Selected value" actions={selected && <CopyRef value={selected.id} />}>
            {selected && selected.page === page ? (
              <div className="selected-scroll">
                <SelectedValue v={selected} />
                <details className="review-details">
                  <summary>Review &amp; correct this value</summary>
                  <ReviewPanel node={selected.id} compact />
                </details>
              </div>
            ) : (
              <EmptyState icon={<MousePointerClick />} title="Nothing selected"
                description="Pick a value in the list, the printed text or the field layout to see exactly what was read." />
            )}
          </PanelSection>
          <PanelSection title={`On this page · ${pageValues.length}`} flush scroll>
            <ValueList values={pageValues} selectedId={selectedId} onSelect={(id) => select(id)} />
          </PanelSection>
        </Panel>
      </div>
      )}
    </div>
  );
}

function SelectedValue({ v }: { v: ValueOut }) {
  return (
    <div className="stack-3" aria-live="polite">
      <div>
        <div className="text-secondary text-sm">{v.label}</div>
        <div className="value-big">{fmtValue(v.value, v.value_type)}</div>
      </div>
      <dl className="ui-dl">
        <dt>Text as read</dt><dd className="mono">{v.text_as_read || "(blank)"}</dd>
        {v.correction && <>
          <dt>Corrected to</dt>
          <dd><span className="mono"><strong>{fmtValue(v.correction.to)}</strong></span> <Badge tone="open">corrected</Badge>
            <div className="text-secondary text-sm">{String(v.correction.by)}: {String(v.correction.reason)}</div></dd>
        </>}
        <dt>Printed page</dt>
        <dd className="row-wrap">
          <MatchBadge status={v.match.status} normalized={v.match.normalized} matched={v.match.matched_text} candidates={v.match.candidates} />
          {v.match.normalized && v.match.matched_text && <span className="text-tertiary text-sm">printed as “{v.match.matched_text}”</span>}
        </dd>
        <dt>Confidence</dt><dd><ConfidenceMeter value={v.confidence} /></dd>
        <dt>Field</dt><dd className="mono">{v.field}</dd>
        <dt>Type</dt><dd>{v.value_type.replace("_", " ")}{v.redacted && <> · <Badge tone="warning">masked</Badge></>}</dd>
        <dt>Reference</dt><dd className="mono">{v.id} · {v.document_id} p.{v.page}</dd>
        <dt>Feeds</dt>
        <dd className="jt-inline">
          {v.lands_in.length ? v.lands_in.map((k) => <LineChip key={k} lineKey={k} />)
            : <span className="text-tertiary text-sm">No return line cites this value</span>}
        </dd>
      </dl>
    </div>
  );
}

function ValueList({ values, selectedId, onSelect }: { values: ValueOut[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const ref = useRef<HTMLUListElement>(null);
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>("[aria-selected='true']")?.scrollIntoView({ block: "nearest" });
  }, [selectedId]);

  if (values.length === 0) {
    return <div style={{ padding: "0 16px 16px" }} className="text-tertiary text-sm">No values were extracted from this page.</div>;
  }
  // ↑/↓ walks the values on the page; the list is one tab stop.
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const i = values.findIndex((v) => v.id === selectedId);
    const next = e.key === "ArrowDown" ? Math.min(i + 1, values.length - 1) : Math.max(i - 1, 0);
    if (values[next]) onSelect(values[next].id);
  };
  return (
    <ul ref={ref} className="value-list" role="listbox" aria-label="Values on this page" tabIndex={0} onKeyDown={onKey}
      aria-activedescendant={selectedId ? `vl-${selectedId}` : undefined}>
      {values.map((v) => (
        <li key={v.id} id={`vl-${v.id}`} role="option" aria-selected={v.id === selectedId} className="value-row" onClick={() => onSelect(v.id)}>
          <span className="value-row__label truncate" title={v.label}>{v.label}</span>
          <span className="value-row__value">{v.text_as_read || "—"}</span>
          <span className="value-row__meta">
            <span className="mono text-tertiary text-xs">{v.id}</span>
            {v.match.status !== "exact" && <MatchBadge status={v.match.status} candidates={v.match.candidates} />}
            {v.lands_in.length > 0 && <span className="value-row__feeds" title={`Feeds ${v.lands_in.join(", ")}`}>→ {v.lands_in[0]}{v.lands_in.length > 1 ? ` +${v.lands_in.length - 1}` : ""}</span>}
            <ConfidenceMeter value={v.confidence} />
          </span>
        </li>
      ))}
    </ul>
  );
}
