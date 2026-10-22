import { useQuery } from "@tanstack/react-query";
import { FileText, MessageSquare, ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import { ClientApproval } from "../components/ClientApproval";
import { Card, ErrorState, PageHeader, PageSkeleton, Table, type Column } from "../ui";
import { fmtDate, fmtDateTime } from "../format";

type Doc = { id: string; title: string; received_at: string };

/** What a client user sees: their own uploads, answers and messages. The server
 *  refuses every firm workpaper endpoint for client identities. */
export function ClientPortal() {
  const q = useQuery({ queryKey: ["client-home"], queryFn: api.clientHome });
  if (q.isPending) return <PageSkeleton label="Loading your file" />;
  if (q.isError) return <div className="page"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>;
  const d = q.data;
  const cols: Column<Doc>[] = [
    { id: "t", header: "Document", width: "minmax(280px, 3fr)", cell: (x) => <span className="row"><FileText aria-hidden className="client-icon" />{x.title}</span> },
    { id: "r", header: "Received", width: "140px", cell: (x) => <span className="text-secondary">{fmtDate(x.received_at)}</span> },
  ];
  return (
    <div className="page">
      <PageHeader title={`Welcome, ${d.you.split(" ")[0]}`}
        meta={<span>{d.household_name} · {d.tax_year} return, prepared by Miraflores</span>} />
      <div className="client-note">
        <ShieldCheck aria-hidden />
        <span>This is your client view. You can see what you've sent us and your messages. Our working papers stay with the firm.</span>
      </div>
      <div className="stack-4">
        <ClientApproval />
        <Card title={`Documents you sent · ${d.documents.length}`} flush>
          <Table label="Your documents" columns={cols} rows={d.documents} rowKey={(x) => x.id} />
        </Card>
        <div className="landing-grid">
          <Card title="Messages">
            <ol className="stack-3">
              {d.messages.map((m) => (
                <li key={String(m.id)} className="stack-1">
                  <span className="row text-secondary text-sm"><MessageSquare aria-hidden className="client-icon" />{String(m.from)} · {fmtDateTime(String(m.sent_at))}</span>
                  <span>{String(m.text)}</span>
                </li>
              ))}
            </ol>
          </Card>
          <Card title="Your questionnaire answers">
            <dl className="stack-3">
              {d.questionnaire.slice(0, 20).map((qa) => (
                <div key={String(qa.id)}><dt className="text-secondary text-sm">{String(qa.question)}</dt><dd>{String(qa.answer)}</dd></div>
              ))}
            </dl>
          </Card>
        </div>
      </div>
    </div>
  );
}
