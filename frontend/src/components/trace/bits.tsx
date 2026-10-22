import { Link } from "react-router-dom";
import { ArrowUpRight, FileText } from "lucide-react";
import type { LandingStatus, Position, TraceSource } from "../../api/client";
import { useTrace } from "../../trace";
import { Badge, ButtonLink, ConfidenceMeter, type Tone } from "../../ui";
import { fmtValue } from "../../format";
import { MatchBadge, RefChip } from "../evidence";

/** A return line reference. One click opens its trace drawer. */
export function LineChip({ lineKey, version, label }: { lineKey: string; version?: string; label?: string }) {
  const { href } = useTrace();
  return (
    <Link className="ui-chip ui-chip--line" to={href(lineKey, version)} title={label ? `${lineKey} · ${label}` : `Trace ${lineKey}`}>
      {lineKey}{label && <span className="ui-chip__kind">{label}</span>}
    </Link>
  );
}

/** A number rendered as a link into its trace. */
export function TraceNumber({ lineKey, children, version }: { lineKey: string | null | undefined; children: React.ReactNode; version?: string }) {
  const { href } = useTrace();
  if (!lineKey) return <>{children}</>;
  return (
    <Link className="trace-number" to={href(lineKey, version)} title={`Trace ${lineKey}: sources and math`}>
      {children}
    </Link>
  );
}

const LANDING: Record<LandingStatus, { tone: Tone; label: string }> = {
  lands: { tone: "outline", label: "Lands" },
  lands_indirectly: { tone: "open", label: "Lands via records" },
  superseded: { tone: "error", label: "Superseded" },
  duplicate: { tone: "warning", label: "Duplicate" },
  not_extracted: { tone: "neutral", label: "Not extracted" },
  support_only: { tone: "neutral", label: "Support only" },
  not_used: { tone: "neutral", label: "Not used" },
};

export function LandingBadge({ status, lines, title }: { status: LandingStatus; lines?: number; title?: string }) {
  const s = LANDING[status];
  const text = (status === "lands" || status === "lands_indirectly") && lines !== undefined
    ? `${lines} line${lines === 1 ? "" : "s"}${status === "lands_indirectly" ? " · indirect" : ""}`
    : s.label;
  return <Badge tone={s.tone} dot={status === "lands"} title={title}>{text}</Badge>;
}

/** A thumbnail page with only the cited field's position box: the trace contract made visible. */
export function MiniPage({ position, label }: { position?: Position | null; label: string }) {
  return (
    <div className="mini-page" aria-label={label} role="img">
      {position && (
        <span className="mini-page__box" style={{
          left: `${position.x0 * 100}%`, top: `${position.y0 * 100}%`,
          width: `${Math.max(position.x1 - position.x0, 0.04) * 100}%`,
          height: `${Math.max(position.y1 - position.y0, 0.02) * 100}%`,
        }} />
      )}
    </div>
  );
}

export function ExcerptText({ excerpt }: { excerpt: NonNullable<TraceSource["excerpt"]> }) {
  const { text, start, end, clipped_left, clipped_right } = excerpt;
  return (
    <p className="excerpt">
      {clipped_left && "… "}{text.slice(0, start)}
      <mark className="hl hl--selected">{text.slice(start, end)}</mark>
      {text.slice(end)}{clipped_right && " …"}
    </p>
  );
}

/** One source of a line: what was read, where (page + position box), and the printed words. */
export function SourceCard({ src, compact }: { src: TraceSource; compact?: boolean }) {
  const { keepOpen } = useTrace();
  const r = src.resolution;
  if (r.kind !== "extracted_value") {
    return (
      <div className="source source--record">
        <div className="row-wrap">
          <Badge tone="outline">{r.kind.replace(/_/g, " ")}</Badge>
          <RefChip refId={src.ref} showLabel />
        </div>
        {src.behind.length > 0 && (
          <div className="source__behind">
            <div className="overline">Evidence behind this record</div>
            {src.behind.map((b) => <SourceCard key={b.ref} src={b} compact />)}
          </div>
        )}
      </div>
    );
  }
  const t = r.target as { label: string; value: unknown; value_type: string; text_as_read: string; confidence: number; page: number };
  const docLink = keepOpen(r.link ?? `/documents/${r.document_id}`);
  return (
    <article className={`source${compact ? " source--compact" : ""}`}>
      <MiniPage position={r.position as Position | undefined} label={`${r.document_id} page ${r.page}, field position`} />
      <div className="source__body">
        <div className="source__head">
          <span className="source__label">{t.label}</span>
          <span className="source__value">{fmtValue(t.value, t.value_type)}</span>
        </div>
        <div className="source__meta">
          <Link to={docLink} className="source__doc"><FileText aria-hidden />{r.document_id} p.{r.page}</Link>
          <span className="mono text-tertiary">{src.ref}</span>
          {src.document_status && src.document_status !== "lands" && <LandingBadge status={src.document_status} />}
          <ConfidenceMeter value={t.confidence} />
        </div>
        {src.excerpt ? <ExcerptText excerpt={src.excerpt} /> : (
          <div className="row"><MatchBadge status="not_found" /><span className="text-tertiary text-sm">Read as “{t.text_as_read}” — not found on the printed page.</span></div>
        )}
        {!compact && (
          <ButtonLink to={docLink} size="sm" variant="ghost" iconRight={<ArrowUpRight aria-hidden />}>
            Open {r.document_id} with this field highlighted
          </ButtonLink>
        )}
      </div>
    </article>
  );
}
