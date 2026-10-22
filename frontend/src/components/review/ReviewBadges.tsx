import { AlertTriangle, CheckCircle2, Lock } from "lucide-react";
import type { NodeSummary } from "../../api/client";
import { Badge } from "../../ui";

/** Compact review state for a row: verified, sign-offs, open/blocking notes, reopened. */
export function ReviewBadges({ s }: { s?: NodeSummary }) {
  if (!s) return <span className="text-tertiary text-sm">—</span>;
  return (
    <span className="row" style={{ gap: 4 }}>
      {s.reopened > 0 && <Badge tone="error" icon={<AlertTriangle aria-hidden />} title="Sign-off reopened: signed content changed">reopened</Badge>}
      {s.blocking > 0 && <Badge tone="error" icon={<Lock aria-hidden />} title="Open blocking note">{s.blocking}</Badge>}
      {s.open_notes - s.blocking > 0 && <Badge tone="open" title="Open notes">{s.open_notes - s.blocking} note</Badge>}
      {s.signed.length > 0 && <Badge tone="verified" title={`Signed: ${s.signed.join(", ")}`}>{s.signed.map((l) => l[0].toUpperCase()).join("·")} ✓</Badge>}
      {s.signed.length === 0 && s.verified > 0 && <Badge tone="verified" icon={<CheckCircle2 aria-hidden />} title="Verified">verified</Badge>}
      {s.stale > 0 && <Badge tone="warning" title="Verification stale: evidence changed">stale</Badge>}
    </span>
  );
}
