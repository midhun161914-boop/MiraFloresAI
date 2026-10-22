import { useEffect, useMemo, useRef } from "react";
import type { ValueOut } from "../api/client";

type Span = { start: number; end: number; id: string; label: string };

// Renders a page's printed_content (ground truth) with every located value
// underlined and the selected one highlighted on the actual printed words.
export function PrintedText({ text, values, selectedId, onSelect }: {
  text: string;
  values: ValueOut[];
  selectedId?: string | null;
  onSelect: (id: string) => void;
}) {
  const selRef = useRef<HTMLElement | null>(null);

  const segments = useMemo(() => {
    const spans: Span[] = values
      .filter((v) => v.match.start != null && v.match.end != null)
      .map((v) => ({ start: v.match.start!, end: v.match.end!, id: v.id, label: v.label }));
    const selected = spans.find((s) => s.id === selectedId);
    const chosen: Span[] = selected ? [selected] : [];
    for (const s of spans.sort((a, b) => a.start - b.start || b.end - a.end)) {
      if (s === selected) continue;
      if (chosen.every((c) => s.end <= c.start || s.start >= c.end)) chosen.push(s);
    }
    chosen.sort((a, b) => a.start - b.start);
    const out: (string | Span)[] = [];
    let at = 0;
    for (const s of chosen) {
      if (s.start > at) out.push(text.slice(at, s.start));
      out.push(s);
      at = s.end;
    }
    if (at < text.length) out.push(text.slice(at));
    return out;
  }, [text, values, selectedId]);

  useEffect(() => {
    selRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedId]);

  return (
    <p className="printed">
      {segments.map((seg, i) =>
        typeof seg === "string" ? (
          <span key={i}>{seg}</span>
        ) : (
          <mark
            key={seg.id}
            ref={seg.id === selectedId ? selRef : undefined}
            className={seg.id === selectedId ? "hl hl--selected" : "hl"}
            title={seg.label}
            onClick={() => onSelect(seg.id)}
          >
            {text.slice(seg.start, seg.end)}
          </mark>
        ),
      )}
    </p>
  );
}
