import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { ErrorState, Skeleton } from "../../ui";
import { SignOffSection } from "./ReviewPanel";

/** Return-level sign-off: the reviewer and partner sign the return as a whole, not
 *  a line. Same event, same rules as any sign-off (reviewer before partner, no
 *  self-review). The fingerprint covers every source value *and* the adjustments
 *  in force, so a later correction or adjustment reopens it. */
export function ReturnSignoff({ compact }: { compact?: boolean }) {
  const q = useQuery({ queryKey: ["review", "return", undefined], queryFn: () => api.review("return") });
  if (q.isPending) return <Skeleton height={96} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  return (
    <div id="return-signoff" className="return-signoff" tabIndex={-1} aria-label="Sign off on the return">
      {!compact && (
        <p className="text-secondary text-sm">
          Signs the whole return: {q.data.evidence_count.toLocaleString()} source values and every adjustment in force.
          A later correction or adjustment reopens it.
        </p>
      )}
      <SignOffSection r={q.data} />
    </div>
  );
}
