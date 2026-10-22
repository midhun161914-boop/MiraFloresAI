// How a number was built (down: inputs) or where it goes (up: the lines that
// consume it). The packet's calc graph is a DAG up to 42 levels deep with 500+
// lines under total tax, so the tree is lazy: only expanded branches render,
// each row states its rule, and the same line reached by two paths is marked
// rather than silently duplicated.
//
// ARIA tree: ↑/↓ move, → expands / enters, ← collapses / goes to parent,
// Enter opens that line's trace, Space toggles.
import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight, CornerDownRight, Repeat2 } from "lucide-react";
import type { CalcGraph, GraphNode } from "../../api/client";
import { Badge, Button } from "../../ui";
import { fmtValue } from "../../format";
import { RefChip } from "../evidence";

interface Row {
  id: string;           // path id: unique per position in the tree
  key: string;
  depth: number;
  parentId: string | null;
  hasChildren: boolean;
  repeat: boolean;      // this line already appears earlier in the visible tree
  kind: "line" | "sources";
}

function children(n: GraphNode, dir: "down" | "up") {
  return dir === "down" ? n.inputs : n.used_by;
}

export function CalcTree({ graph, onOpen, initialDepth = 1, focusKey }: {
  graph: CalcGraph;
  onOpen: (key: string) => void;
  initialDepth?: number;
  focusKey?: string;
}) {
  const dir = graph.direction;
  const { nodes, root } = graph;
  const initial = useMemo(() => {
    const open = new Set<string>();
    const walk = (key: string, id: string, depth: number) => {
      const n = nodes[key];
      if (!n || depth > initialDepth) return;
      const kids = children(n, dir);
      if (kids.length === 0 && dir === "down" && n.sources.length && depth <= initialDepth) open.add(id);
      if (kids.length === 0) return;
      open.add(id);
      if (kids.length <= 12) kids.forEach((k) => walk(k, `${id}/${k}`, depth + 1));
    };
    walk(root, root, 0);
    return open;
  }, [nodes, root, dir, initialDepth]);
  const [expanded, setExpanded] = useState<Set<string>>(initial);
  useEffect(() => setExpanded(initial), [initial]);

  const rows = useMemo(() => {
    const out: Row[] = [];
    const seen = new Set<string>();
    const walk = (key: string, id: string, depth: number, parentId: string | null) => {
      const n = nodes[key];
      if (!n) return;
      const kids = children(n, dir);
      const leafWithSources = kids.length === 0 && dir === "down" && n.sources.length > 0;
      const repeat = seen.has(key);
      seen.add(key);
      out.push({ id, key, depth, parentId, hasChildren: kids.length > 0 || leafWithSources, repeat, kind: "line" });
      if (!expanded.has(id)) return;
      if (leafWithSources) out.push({ id: `${id}#src`, key, depth: depth + 1, parentId: id, hasChildren: false, repeat: false, kind: "sources" });
      kids.forEach((k) => walk(k, `${id}/${k}`, depth + 1, id));
    };
    walk(root, root, 0, null);
    return out;
  }, [nodes, root, dir, expanded]);

  const [active, setActive] = useState(rows[0]?.id);
  const list = useRef<HTMLUListElement>(null);
  // Focus synchronously when the row is already rendered so fast key presses stay
  // in step; wait a frame only for a row that an expansion is about to render.
  const focusRow = (id: string) => {
    setActive(id);
    const find = () => list.current?.querySelector<HTMLElement>(`[data-row="${CSS.escape(id)}"]`);
    const row = find();
    if (row) row.focus();
    else requestAnimationFrame(() => find()?.focus());
  };

  const toggle = (id: string, open?: boolean) => setExpanded((prev) => {
    const next = new Set(prev);
    const want = open ?? !next.has(id);
    if (want) next.add(id); else next.delete(id);
    return next;
  });

  const expandLevel = () => setExpanded((prev) => {
    const next = new Set(prev);
    rows.forEach((r) => { if (r.kind === "line" && r.hasChildren && !r.repeat) next.add(r.id); });
    return next;
  });

  const onKey = (e: React.KeyboardEvent, r: Row, i: number) => {
    const open = expanded.has(r.id);
    if (e.key === "ArrowDown" && rows[i + 1]) { e.preventDefault(); focusRow(rows[i + 1].id); }
    else if (e.key === "ArrowUp" && rows[i - 1]) { e.preventDefault(); focusRow(rows[i - 1].id); }
    else if (e.key === "ArrowRight") {
      e.preventDefault();
      if (r.hasChildren && !open) toggle(r.id, true);
      else if (open && rows[i + 1]) focusRow(rows[i + 1].id);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      if (r.hasChildren && open) toggle(r.id, false);
      else if (r.parentId) focusRow(r.parentId);
    } else if (e.key === "Enter" && r.kind === "line") { e.preventDefault(); onOpen(r.key); }
    else if (e.key === " " && r.hasChildren) { e.preventDefault(); toggle(r.id); }
  };

  const total = Object.keys(nodes).length - 1;
  return (
    <div className="calc">
      <div className="calc__bar">
        <span className="text-secondary text-sm">
          {dir === "down"
            ? total ? `${total.toLocaleString()} line${total === 1 ? "" : "s"} feed this number · ${graph.depth} level${graph.depth === 1 ? "" : "s"} deep` : "A leaf of the calculation — built directly from evidence"
            : total ? `Flows into ${total.toLocaleString()} line${total === 1 ? "" : "s"} · ${graph.depth} level${graph.depth === 1 ? "" : "s"} up` : "Nothing consumes this line"}
        </span>
        <span className="spacer" />
        {total > 0 && <>
          <Button size="sm" variant="ghost" onClick={expandLevel}>Expand a level</Button>
          <Button size="sm" variant="ghost" onClick={() => setExpanded(new Set([root]))}>Collapse</Button>
        </>}
      </div>
      <ul className="calc__tree" role="tree" aria-label={dir === "down" ? "How this number was built" : "Where this number goes"} ref={list}>
        {rows.map((r, i) => {
          const n = nodes[r.key];
          const pad = { paddingLeft: `${8 + r.depth * 20}px` };
          if (r.kind === "sources") {
            return (
              <li key={r.id} role="treeitem" aria-level={r.depth + 1} data-row={r.id} tabIndex={active === r.id ? 0 : -1}
                className="calc__row calc__row--sources" style={pad} onKeyDown={(e) => onKey(e, r, i)}
                onFocus={() => setActive(r.id)}>
                <CornerDownRight className="calc__src-icon" aria-hidden />
                <span className="text-tertiary text-sm">Evidence</span>
                <span className="jt-inline">{n.sources.map((s) => <RefChip key={s} refId={s} />)}</span>
              </li>
            );
          }
          const open = expanded.has(r.id);
          return (
            <li key={r.id} role="treeitem" aria-level={r.depth + 1} aria-expanded={r.hasChildren ? open : undefined}
              aria-selected={r.key === (focusKey ?? root) && r.depth === 0}
              data-row={r.id} tabIndex={active === r.id ? 0 : -1}
              className={`calc__row${r.depth === 0 ? " calc__row--root" : ""}`} style={pad}
              onKeyDown={(e) => onKey(e, r, i)} onFocus={() => setActive(r.id)}>
              <span className="calc__guides" aria-hidden style={{ width: r.depth * 20 }} />
              {r.hasChildren ? (
                <button type="button" tabIndex={-1} className={`calc__caret${open ? " is-open" : ""}`}
                  aria-label={open ? "Collapse" : "Expand"} onClick={() => toggle(r.id)}>
                  <ChevronRight aria-hidden />
                </button>
              ) : <span className="calc__caret calc__caret--leaf" aria-hidden />}
              <button type="button" tabIndex={-1} className="calc__key" onClick={() => onOpen(r.key)} title={`Open the trace for ${r.key}`}>
                {r.key}
              </button>
              <span className="calc__text">
                <span className="calc__label">{n.label}</span>
                <span className="calc__rule" title={n.rule_text ?? undefined}>
                  <span className="mono">{n.rule}</span>{n.rule_text && <> · {n.rule_text}</>}
                </span>
              </span>
              {r.repeat && <Badge tone="neutral" icon={<Repeat2 aria-hidden />} title="This line also appears elsewhere in this tree">also above</Badge>}
              <span className="calc__value">{fmtValue(n.value)}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
