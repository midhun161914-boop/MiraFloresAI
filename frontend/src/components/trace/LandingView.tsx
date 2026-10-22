// Document -> where it landed. Every line its values feed (directly or through a
// record), and when it feeds nothing, the reason, derived from the data.
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type DocumentLanding } from "../../api/client";
import { useTrace } from "../../trace";
import { Badge, Callout, Card, EmptyState, ErrorState, Skeleton, Table, type Column } from "../../ui";
import { fmtValue } from "../../format";
import { RefChip } from "../evidence";
import { LandingBadge } from "./bits";

type Landed = DocumentLanding["lines"][number];

export function LandingView({ docId }: { docId: string }) {
  const { open, keepOpen } = useTrace();
  const q = useQuery({ queryKey: ["landing", docId], queryFn: () => api.landing(docId), staleTime: Infinity });
  if (q.isPending) return <div className="stack-3"><Skeleton height={72} /><Skeleton height={240} /></div>;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const L = q.data;

  const columns: Column<Landed>[] = [
    { id: "key", header: "Line", width: "132px", cell: (x) => <span className="mono">{x.line.key}</span> },
    { id: "label", header: "Description", width: "minmax(220px, 2fr)", cell: (x) => <span className="truncate" style={{ display: "block" }}>{x.line.label}</span> },
    { id: "value", header: "Amount", width: "110px", align: "right", cell: (x) => fmtValue(x.line.value) },
    { id: "via", header: "From this document", width: "minmax(220px, 2fr)", cell: (x) => (
      <span className="jt-inline" onClick={(e) => e.stopPropagation()}>
        {x.evidence.map((e) => (
          <Link key={`${e.ev}-${e.via ?? ""}`} className="ui-chip" to={keepOpen(`/documents/${docId}?ev=${e.ev}`)}
            title={e.via ? `${e.ev}, via ${e.via}` : e.ev}>
            {e.ev}{e.via && <span className="ui-chip__kind">via {e.via.replace(/^py:\/return_2024\/lines\//, "2024 ")}</span>}
          </Link>
        ))}
      </span>
    ) },
  ];

  const tone = (t: string) => (t === "verified" ? "neutral" : t) as "neutral" | "open" | "warning" | "error";
  return (
    <div className="stack-4">
      <Card>
        <div className="landing-head">
          <LandingBadge status={L.status} lines={L.lines.length} />
          <h2 className="landing-head__title">{L.headline}</h2>
          <span className="spacer" />
          <span className="text-secondary text-sm tabular">{L.values_cited} of {L.values_total} values cited</span>
        </div>
        {L.reasons.length > 0 && (
          <div className="stack-2" style={{ marginTop: 12 }}>
            {L.reasons.map((r) => (
              <Callout key={r.code} tone={tone(r.tone)}>
                <div className="stack-1">
                  <strong>{r.title}</strong>
                  <div>{r.detail}</div>
                  {r.refs.length > 0 && <div className="jt-inline">{r.refs.map((x) => <RefChip key={x} refId={x} />)}</div>}
                </div>
              </Callout>
            ))}
          </div>
        )}
      </Card>

      <Card title={`Return lines fed · ${L.version}`} flush
        description={L.lines.length ? "Click a line to trace it. Evidence chips open the exact field on this document." : undefined}>
        <Table label="Return lines fed by this document" columns={columns} rows={L.lines} rowKey={(x) => x.line.key}
          density="default" onRowClick={(x) => open(x.line.key)}
          virtual={L.lines.length > 60} rowHeight={44} maxHeight={L.lines.length > 60 ? 560 : undefined}
          empty={<EmptyState title="No return line uses this document" description={L.reasons[0]?.title ?? L.headline} />} />
      </Card>

      <div className="landing-grid">
        <Card title="Across versions">
          <dl className="ui-dl">
            {L.by_version.map((b) => [
              <dt key={`${b.version}-t`}>{b.version}</dt>,
              <dd key={`${b.version}-d`} className="row">
                <Badge tone={b.use === "used" ? "outline" : b.use === "superseded" ? "error" : "neutral"}>{b.use.replace("_", " ")}</Badge>
                <span className="text-secondary text-sm">{b.lines} line{b.lines === 1 ? "" : "s"}</span>
              </dd>,
            ])}
          </dl>
        </Card>
        <Card title="Mentioned in" description="Other records in the file that name this document or its values.">
          {L.mentions.length ? (
            <div className="stack-2">{L.mentions.map((m) => <div key={m.ref}><RefChip refId={m.ref} showLabel /></div>)}</div>
          ) : <span className="text-tertiary text-sm">Nothing else in the file refers to it.</span>}
        </Card>
      </div>
    </div>
  );
}
