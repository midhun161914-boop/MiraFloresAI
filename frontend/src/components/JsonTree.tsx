import { RefChip } from "./evidence";

// Strings that are unambiguously references in the packet's pointer grammar.
const REF = /^(ev-\d{4}|D\d{2}|doc:D\d{2}#page\d+|qa-\d+|msg-\d+|call-\d+|py:\/.+|agency:\/.+|asset:.+|household:.+|ref:param\..+|ref:fx\..+|timeline:.+|v\d+|R-[A-Z0-9-]+)$/;
// Keys whose string values are references even when they look like line keys.
const REF_KEYS = new Set(["sources", "inputs", "refs", "documents_used", "documents_superseded", "rule", "document", "source_document"]);
const LINE_KEY = /^[A-Za-z][\w-]*\.[\w.-]+$/;

function isRef(value: string, parentKey?: string) {
  return REF.test(value) || (!!parentKey && REF_KEYS.has(parentKey) && LINE_KEY.test(value));
}

function Leaf({ value, parentKey }: { value: unknown; parentKey?: string }) {
  if (typeof value === "string" && isRef(value, parentKey)) return <RefChip refId={value} />;
  if (value === null || value === undefined) return <span className="jt-null">—</span>;
  if (typeof value === "number") return <span className="jt-num">{value.toLocaleString("en-US")}</span>;
  if (typeof value === "boolean") return <span>{value ? "Yes" : "No"}</span>;
  return <span>{String(value)}</span>;
}

export function JsonTree({ value, parentKey }: { value: unknown; parentKey?: string }) {
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="jt-null">None</span>;
    if (value.every((v) => typeof v !== "object" || v === null)) {
      return <span className="jt-inline">{value.map((v, i) => <Leaf key={i} value={v} parentKey={parentKey} />)}</span>;
    }
    return (
      <ol className="jt-list">
        {value.map((v, i) => <li key={i}><JsonTree value={v} parentKey={parentKey} /></li>)}
      </ol>
    );
  }
  if (value && typeof value === "object") {
    return (
      <dl className="jt">
        {Object.entries(value as Record<string, unknown>).map(([k, v]) => [
          <dt key={`${k}-t`}>{k.replace(/_/g, " ")}</dt>,
          <dd key={`${k}-d`}><JsonTree value={v} parentKey={k} /></dd>,
        ])}
      </dl>
    );
  }
  return <Leaf value={value} parentKey={parentKey} />;
}
