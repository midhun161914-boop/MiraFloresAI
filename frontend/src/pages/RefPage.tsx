import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { FileText } from "lucide-react";
import { api, ApiError } from "../api/client";
import { CopyRef } from "../components/evidence";
import { JsonTree } from "../components/JsonTree";
import { Badge, ButtonLink, Callout, Card, EmptyState, ErrorState, PageHeader, PageSkeleton } from "../ui";

// Generic inspector for any reference in the packet's pointer grammar. Every
// reference chip without a dedicated screen lands here, so no link is dead.
export function RefPage() {
  const [params] = useSearchParams();
  const ref = params.get("r") ?? "";
  const res = useQuery({ queryKey: ["resolve", ref], queryFn: () => api.resolve(ref), staleTime: Infinity, retry: false, enabled: !!ref });

  if (!ref) return <div className="page"><EmptyState title="No reference given" description="Use the search box to jump to any reference." /></div>;
  if (res.isPending) return <PageSkeleton label={`Resolving ${ref}`} />;
  if (res.isError) {
    const notFound = res.error instanceof ApiError && res.error.status === 404;
    return <div className="page"><ErrorState title={notFound ? `“${ref}” isn't a reference in this packet` : "Couldn't resolve this reference"} error={res.error} /></div>;
  }
  const r = res.data;
  return (
    <div className="page">
      <PageHeader
        crumbs={[{ label: "Reference" }, { label: r.ref }]}
        title={r.label}
        meta={<>
          <Badge tone="outline">{r.kind.replace(/_/g, " ")}</Badge>
          {r.version && <Badge tone="neutral">Return {r.version}</Badge>}
          <span className="row mono text-tertiary">{r.ref}<CopyRef value={r.ref} /></span>
        </>}
        actions={r.document_id && (
          <ButtonLink to={`/documents/${r.document_id}${r.page ? `?page=${r.page}` : ""}`} icon={<FileText aria-hidden />}>
            Open {r.document_id}{r.page ? ` p.${r.page}` : ""}
          </ButtonLink>
        )}
      />
      {r.note && <div style={{ marginBottom: 16 }}><Callout tone="open">{r.note}</Callout></div>}
      <Card title="Record" description="As stored in the packet. Linked references open their own record.">
        <JsonTree value={r.target} />
      </Card>
    </div>
  );
}
