// Domain-aware building blocks on top of the UI primitives: reference chips,
// printed-page match badges, document status badges, people/role labels.
import { Link } from "react-router-dom";
import { CheckCircle2, CircleDashed, Copy, FileWarning } from "lucide-react";
import type { DocumentSummary, MatchStatus } from "../api/client";
import { useResolvedRef } from "../api/refs";
import { useTrace } from "../trace";
import { Badge, type Tone } from "../ui";

export const LOW_CONFIDENCE = 0.8;

export function RefChip({ refId, showLabel = false }: { refId: string; showLabel?: boolean }) {
  const { data, isLoading, isError } = useResolvedRef(refId);
  const { href } = useTrace();
  if (isLoading) return <span className="ui-chip ui-chip--loading">{refId}</span>;
  if (isError || !data || !data.found) {
    return <span className="ui-chip ui-chip--error" title={data?.label ?? "Could not resolve"}>{refId}</span>;
  }
  const title = `${data.kind.replace(/_/g, " ")} · ${data.label}`;
  const body = showLabel ? data.label : refId;
  // A return line opens its trace drawer in place: one click from number to evidence and math.
  if (data.kind === "return_line") {
    return <Link className="ui-chip ui-chip--line" to={href(refId, data.version ?? undefined)} title={title}>{body}</Link>;
  }
  return data.link
    ? <Link className="ui-chip" to={data.link} title={title}>{body}</Link>
    : <span className="ui-chip" title={title}>{body}</span>;
}

const MATCH: Record<MatchStatus, { tone: Tone; text: string; help: string }> = {
  exact: { tone: "verified", text: "On page", help: "The value appears on its page's printed content." },
  ambiguous: { tone: "warning", text: "Repeated", help: "The value appears on the page more than once; the most likely spot is highlighted." },
  not_found: { tone: "error", text: "Not on page", help: "What the pipeline read does not appear in the page's printed content in any normal formatting. Check the read." },
  empty: { tone: "neutral", text: "Blank", help: "Nothing was printed where the pipeline read this field." },
};

export function MatchBadge({ status, normalized, matched, candidates = 0 }: {
  status: MatchStatus; normalized?: boolean; matched?: string | null; candidates?: number;
}) {
  const m = MATCH[status];
  const text = status === "ambiguous" && candidates > 1 ? `Repeated ×${candidates}` : m.text;
  const help = m.help + (normalized && matched ? ` Printed as “${matched}”.` : "");
  return <Badge tone={m.tone} dot title={help}>{text}</Badge>;
}

export function ExtractionBadge({ status, reason }: { status: DocumentSummary["extraction"]["status"]; reason?: string | null }) {
  if (status === "extracted") return <Badge tone="verified" icon={<CheckCircle2 aria-hidden />} title={reason ?? undefined}>Extracted</Badge>;
  if (status === "partial") return <Badge tone="warning" icon={<FileWarning aria-hidden />} title={reason ?? undefined}>Partial</Badge>;
  return <Badge tone="neutral" icon={<CircleDashed aria-hidden />} title={reason ?? undefined}>Not extracted</Badge>;
}

export function UseBadge({ use, version }: { use: DocumentSummary["current_use"]; version?: string }) {
  if (use === "used") return <Badge tone="outline" dot>Used</Badge>;
  if (use === "superseded") {
    return <Badge tone="error" dot title={`Superseded in ${version ?? "the current return"}: its figures must not flow through`}>Superseded</Badge>;
  }
  return <Badge tone="neutral">Not used</Badge>;
}

export const ROLE_LABEL: Record<string, string> = {
  preparer: "Preparer",
  reviewer: "Reviewer",
  partner: "Partner",
  firm_administrator: "Administrator",
  quality_reviewer: "Quality reviewer",
  client: "Client",
};

const ROLE_COLOR: Record<string, string> = {
  preparer: "#4b5878",
  reviewer: "#2f6582",
  partner: "#5f4a85",
  firm_administrator: "#77553a",
  quality_reviewer: "#2f6b5e",
  client: "#7e4655",
};

export function Avatar({ name, role }: { name: string; role: string }) {
  const initials = name.split(/\s+/).map((p) => p[0]).slice(0, 2).join("");
  return (
    <span className="ui-avatar" style={{ background: ROLE_COLOR[role] ?? "#4b5262" }} aria-hidden>
      {initials}
    </span>
  );
}

export function CopyRef({ value }: { value: string }) {
  return (
    <button type="button" className="ui-btn ui-btn--ghost ui-btn--sm ui-btn--icon" title={`Copy ${value}`}
      aria-label={`Copy reference ${value}`}
      onClick={() => { void navigator.clipboard?.writeText(value); }}>
      <Copy aria-hidden />
    </button>
  );
}
