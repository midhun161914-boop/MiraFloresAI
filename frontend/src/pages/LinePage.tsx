import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { TraceFacts, TraceMath, TraceSources } from "../components/trace/sections";
import { CopyRef } from "../components/evidence";
import { ReviewPanel } from "../components/review/ReviewPanel";
import { Badge, Card, ErrorState, PageHeader, PageSkeleton, Panel, PanelSection, Select } from "../ui";
import { fmtValue } from "../format";

/** Full trace for one return line: math down and up in the main column, evidence in the side panel. */
export function LinePage() {
  const { key = "" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const version = params.get("version") ?? undefined;
  const ov = useQuery({ queryKey: ["overview"], queryFn: api.overview, staleTime: Infinity });
  const t = useQuery({ queryKey: ["line", key, version], queryFn: () => api.lineTrace(key, version), staleTime: Infinity, retry: false });

  if (t.isPending) return <PageSkeleton label={`Tracing ${key}`} />;
  if (t.isError) return <div className="page"><ErrorState title={`Couldn't trace ${key}`} error={t.error} /></div>;
  const d = t.data;
  const versions = ov.data?.versions.map((v) => ({ value: v.version, label: `${v.version}${v.is_current ? " (current)" : ""}` })) ?? [];

  return (
    <div className="line-page">
      <div className="line-page__main">
        <PageHeader
          crumbs={[{ label: "Return", to: `/return${version ? `?version=${version}` : ""}` }, { label: d.line.form, to: `/return?form=${d.line.form}${version ? `&version=${version}` : ""}` }, { label: d.line.key }]}
          title={d.line.label}
          meta={<>
            <span className="mono">{d.line.key}</span><CopyRef value={d.line.key} />
            <Badge tone="neutral">{d.line.jurisdiction}</Badge>
            <span>Form {d.line.form}, line {d.line.line}</span>
          </>}
          actions={versions.length > 0 && (
            <Select label="Version" value={d.version} options={versions}
              onChange={(v) => navigate(`/lines/${encodeURIComponent(key)}${v === ov.data?.current_version ? "" : `?version=${v}`}`)} />
          )}
        />
        <div className="line-figure">
          <span className="line-figure__value">{fmtValue(d.line.value)}</span>
          <span className="line-figure__rule"><span className="mono">{d.line.rule}</span>{d.rule_text && <> · {d.rule_text}</>}</span>
        </div>
        <div className="stack-4">
          <Card title="How it was built" description="Inputs and rules down to the evidence. Click a line to trace it; ←/→ collapse and expand.">
            <TraceMath lineKey={key} version={version} direction="down" />
          </Card>
          <Card title="Where it goes" description="Every line that takes this number as an input, up to the return totals.">
            <TraceMath lineKey={key} version={version} direction="up" />
          </Card>
        </div>
      </div>
      <Panel title="Evidence" subtitle={`${d.sources.length} source${d.sources.length === 1 ? "" : "s"} · ${d.version}`} aria-label="Evidence for this line">
        <PanelSection title="Review"><ReviewPanel node={key} version={version} /></PanelSection>
        <PanelSection title="Sources"><TraceSources trace={d} /></PanelSection>
        <PanelSection title="Context"><TraceFacts trace={d} /></PanelSection>
      </Panel>
    </div>
  );
}
