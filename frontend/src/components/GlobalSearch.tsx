import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, FileText, Hash, History, LayoutGrid, ListTree, Mail, MessageSquare, Scale, Search, Sigma, User } from "lucide-react";
import { api } from "../api/client";
import { useTrace } from "../trace";
import { Kbd } from "../ui";

const ICONS: Record<string, JSX.Element> = {
  document: <FileText aria-hidden />,
  return_line: <Sigma aria-hidden />,
  extracted_value: <Hash aria-hidden />,
  client: <MessageSquare aria-hidden />,
  finding: <AlertTriangle aria-hidden />,
  adjustment: <Scale aria-hidden />,
  notice: <Mail aria-hidden />,
  person: <User aria-hidden />,
  event: <History aria-hidden />,
  screen: <LayoutGrid aria-hidden />,
};

type Option = { key: string; label: string; sublabel?: string | null; link: string; kind: string; exact?: boolean };

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

// Global search: references, documents, return lines, extracted values and
// client answers in one box. "/" or Ctrl/⌘K focuses it from anywhere.
// Combobox pattern: ↑/↓ moves through results, Enter opens, Esc closes.
export function GlobalSearch() {
  const navigate = useNavigate();
  const { href } = useTrace();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const debounced = useDebounced(q.trim(), 120);

  const results = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => api.search(debounced),
    enabled: debounced.length > 0,
    staleTime: 60_000,
  });

  const options: (Option & { group?: string })[] = useMemo(() => {
    const r = results.data;
    if (!r) return [];
    const out: (Option & { group?: string })[] = [];
    if (r.exact?.link) {
      out.push({ key: `exact:${r.exact.ref}`, label: r.exact.label, sublabel: r.exact.kind.replace(/_/g, " "), link: r.exact.link, kind: "exact", exact: true, group: "Go to reference" });
    }
    for (const g of r.groups) {
      g.items.forEach((h, i) => out.push({ key: `${g.kind}:${h.id}`, label: h.label, sublabel: h.sublabel, link: h.link, kind: g.kind, group: i === 0 ? `${g.label} · ${g.total.toLocaleString()}` : undefined }));
    }
    return out;
  }, [results.data]);

  useEffect(() => setActive(0), [results.data]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) || t.isContentEditable;
      if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !typing)) {
        e.preventDefault();
        input.current?.focus();
        input.current?.select();
        setOpen(true);
      }
    };
    const onDown = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    window.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => { window.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onDown); };
  }, []);

  // Return lines open in the trace drawer over the current screen; everything else navigates.
  const go = (o: Option) => {
    const lineKey = o.kind === "return_line" ? o.key.split(":")[1]
      : o.exact && o.sublabel === "return line" ? o.key.slice("exact:".length) : null;
    navigate(lineKey ? href(lineKey) : o.link);
    setOpen(false);
    setQ("");
    input.current?.blur();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((i) => Math.min(i + 1, options.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); if (options[active]) go(options[active]); }
    else if (e.key === "Escape") { if (q) setQ(""); else { setOpen(false); input.current?.blur(); } }
  };

  const showPanel = open && q.trim().length > 0;
  const pending = results.isFetching && !results.data;

  return (
    <div className="gsearch" ref={wrap}>
      <div className="ui-search gsearch__box">
        <Search aria-hidden />
        <input
          ref={input}
          role="combobox"
          aria-expanded={showPanel}
          aria-controls="gsearch-list"
          aria-autocomplete="list"
          aria-activedescendant={showPanel && options[active] ? `gs-${active}` : undefined}
          aria-label="Search the workpaper"
          placeholder="Search documents, lines, values, findings, people, activity…"
          value={q}
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKey}
        />
        {!q && <span className="gsearch__hint" aria-hidden><Kbd>/</Kbd></span>}
      </div>
      {showPanel && (
        <div className="ui-popover gsearch__panel">
          {pending && <div className="gsearch__status">Searching…</div>}
          {!pending && results.isError && <div className="gsearch__status">Search failed. Try again.</div>}
          {!pending && results.data && options.length === 0 && (
            <div className="gsearch__status">No matches for “{q.trim()}”.</div>
          )}
          {options.length > 0 && (
            <ul id="gsearch-list" role="listbox" aria-label="Search results" className="gsearch__list">
              {options.map((o, i) => (
                <li key={o.key} role="presentation">
                  {o.group && <div className="gsearch__group overline">{o.group}</div>}
                  <div id={`gs-${i}`} role="option" aria-selected={i === active}
                    className={`ui-option${i === active ? " ui-option--active" : ""}`}
                    onMouseEnter={() => setActive(i)} onMouseDown={(e) => e.preventDefault()} onClick={() => go(o)}>
                    <span className="gsearch__icon">{o.exact ? <ArrowRight aria-hidden /> : ICONS[o.kind] ?? <ListTree aria-hidden />}</span>
                    <div className="ui-option__main">
                      <div className="truncate">{o.label}</div>
                      {o.sublabel && <div className="ui-option__sub truncate">{o.sublabel}</div>}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <div className="gsearch__foot text-xs">
            <span><Kbd>↑</Kbd><Kbd>↓</Kbd> move</span><span><Kbd>↵</Kbd> open</span><span><Kbd>esc</Kbd> close</span>
          </div>
        </div>
      )}
    </div>
  );
}
