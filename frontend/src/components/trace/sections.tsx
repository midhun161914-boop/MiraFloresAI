import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Info } from "lucide-react";
import { api, type LineTrace } from "../../api/client";
import { Badge, Callout, EmptyState, ErrorState, Skeleton } from "../../ui";
import { fmtAccounting, fmtValue } from "../../format";
import { useTrace } from "../../trace";
import { CalcTree } from "./CalcTree";
import { LineChip, SourceCard } from "./bits";

/** Number -> documents: every source, plus an independent check that the read values add up. */
export function TraceSources({ trace }: { trace: LineTrace }) {
  const evs = trace.sources.filter((s) => s.resolution.kind === "extracted_value");
  const records = trace.sources.filter((s) => s.resolution.kind !== "extracted_value");
  const numeric = evs.map((s) => (s.resolution.target as { value: unknown }).value).filter((v): v is number => typeof v === "number");
  const value = trace.line.value;
  const sum = numeric.reduce((a, b) => a + b, 0);
  const foots = typeof value === "number" && numeric.length === evs.length && numeric.length > 1 && Math.abs(sum - value) < 0.5;

  if (trace.sources.length === 0) {
    return (
      <EmptyState icon={<Info />} title="No direct evidence"
        description={trace.line.inputs.length
          ? "This line is computed from other lines — see how it was built."
          : "The engine produced this line without citing evidence. Worth a reviewer's question."} />
    );
  }
  return (
    <div className="stack-3">
      {numeric.length > 1 && typeof value === "number" && (
        foots
          ? <Callout tone="neutral" icon={<CheckCircle2 aria-hidden style={{ color: "var(--verified-solid)" }} />}>The {numeric.length} source values add to {fmtAccounting(sum)} — equal to the line.</Callout>
          : <Callout tone="neutral">Source values add to {fmtAccounting(sum)}; the line is {fmtAccounting(value)}. Rule {trace.line.rule} is not a straight sum — read its description.</Callout>
      )}
      {evs.map((s) => <SourceCard key={s.ref} src={s} />)}
      {records.length > 0 && (
        <div className="stack-2">
          <div className="overline">Other evidence</div>
          {records.map((s) => <SourceCard key={s.ref} src={s} />)}
        </div>
      )}
    </div>
  );
}

/** Number -> math, in either direction. */
export function TraceMath({ lineKey, version, direction }: { lineKey: string; version?: string; direction: "down" | "up" }) {
  const { open } = useTrace();
  const g = useQuery({
    queryKey: ["graph", lineKey, version, direction],
    queryFn: () => api.lineGraph(lineKey, direction, version),
    staleTime: Infinity,
  });
  if (g.isPending) return <div className="stack-2">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} height={28} />)}</div>;
  if (g.isError) return <ErrorState error={g.error} onRetry={() => g.refetch()} />;
  return <CalcTree graph={g.data} onOpen={(k) => open(k, version)} initialDepth={direction === "down" ? 1 : 2} />;
}

/** The facts around a line: versions, prior year, used-by, diagnostics, note. */
export function TraceFacts({ trace }: { trace: LineTrace }) {
  const v = trace.version;
  return (
    <div className="stack-4">
      {trace.line.note && <Callout tone="open">{trace.line.note}</Callout>}
      {trace.diagnostics.map((d, i) => (
        <Callout key={i} tone={d.severity === "warning" ? "warning" : "neutral"}>
          <strong className="mono">{String(d.code)}</strong> — {String(d.message)}
        </Callout>
      ))}
      <dl className="ui-dl">
        <dt>By version</dt>
        <dd className="row-wrap">
          {trace.by_version.map((b) => (
            <span key={b.version} className="version-value">
              <span className="text-tertiary">{b.version}</span>
              <span className="tabular">{b.present ? fmtValue(b.value) : "—"}</span>
              {b.change && <Badge tone={b.change === "changed" ? "warning" : "open"}>{b.change}</Badge>}
            </span>
          ))}
        </dd>
        <dt>2024 as filed</dt>
        <dd>{trace.prior_year ? <span className="tabular">{fmtValue(trace.prior_year.value)}</span> : <span className="text-tertiary">No matching 2024 line</span>}</dd>
        <dt>Feeds into</dt>
        <dd className="jt-inline">
          {trace.used_by.length ? trace.used_by.map((u) => <LineChip key={u.key} lineKey={u.key} version={v} label={u.label} />)
            : <span className="text-tertiary">Nothing — a top-level figure</span>}
        </dd>
        <dt>Built from</dt>
        <dd className="jt-inline">
          {trace.inputs.length ? trace.inputs.map((u) => <LineChip key={u.key} lineKey={u.key} version={v} label={u.label} />)
            : <span className="text-tertiary">Evidence only (no input lines)</span>}
        </dd>
      </dl>
    </div>
  );
}
