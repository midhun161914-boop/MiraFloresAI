// Table primitive: one look for every list in the app, from 3 rows to 3,012.
// Div-based CSS grid with ARIA table roles so columns can be sized with grid
// tracks and the same markup can be virtualized. Rows are keyboard-reachable:
// Tab into the table, ↑/↓ to move, Enter to open.
import { useRef, type ReactNode, type KeyboardEvent } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { cx, Skeleton } from "./primitives";

export interface Column<T> {
  id: string;
  header: ReactNode;
  /** CSS grid track, e.g. "88px" or "minmax(240px, 2fr)". */
  width?: string;
  align?: "left" | "right" | "center";
  cell: (row: T) => ReactNode;
}

export interface TableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  label: string;
  onRowClick?: (row: T) => void;
  selectedKey?: string | null;
  rowClassName?: (row: T) => string | undefined;
  density?: "compact" | "default";
  /** Virtualize rows; the table fills its flex parent and scrolls internally. */
  virtual?: boolean;
  rowHeight?: number;
  loading?: boolean;
  empty?: ReactNode;
  /** Multi-select for bulk actions: a checkbox column; Space toggles a focused row. */
  selection?: { selected: Set<string>; onChange: (next: Set<string>) => void; canSelect?: (row: T) => boolean };
  /** Cap the scroll height (px) — lets a virtual table live inside a normal page instead of a fill card. */
  maxHeight?: number;
}

export function Table<T>({
  columns, rows, rowKey, label, onRowClick, selectedKey, rowClassName,
  density = "compact", virtual = false, rowHeight, loading, empty, selection, maxHeight,
}: TableProps<T>) {
  const template = (selection ? "32px " : "") + columns.map((c) => c.width ?? "minmax(0, 1fr)").join(" ");
  const selectable = selection ? rows.filter((r) => selection.canSelect?.(r) ?? true) : [];
  const allOn = !!selection && selectable.length > 0 && selectable.every((r) => selection.selected.has(rowKey(r)));
  const toggle = (row: T) => {
    if (!selection || !(selection.canSelect?.(row) ?? true)) return;
    const next = new Set(selection.selected);
    const k = rowKey(row);
    if (next.has(k)) next.delete(k); else next.add(k);
    selection.onChange(next);
  };
  const scrollRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const height = rowHeight ?? (density === "compact" ? 36 : 44);
  const virt = useVirtualizer({
    count: virtual ? rows.length : 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => height,
    overscan: 12,
  });

  // Focus synchronously when the row is already rendered so rapid key presses
  // stay in step; only wait a frame when virtualization must render it first.
  const focusRow = (index: number) => {
    const find = () => bodyRef.current?.querySelector<HTMLElement>(`[data-index="${index}"]`);
    if (virtual) virt.scrollToIndex(index, { align: "auto" });
    const row = find();
    if (row) row.focus({ preventScroll: virtual }); // the virtualizer already scrolled
    else requestAnimationFrame(() => find()?.focus());
  };

  const onKey = (e: KeyboardEvent<HTMLDivElement>, index: number, row: T) => {
    if (e.key === " " && selection) {
      e.preventDefault();
      toggle(row);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onRowClick?.(row);
    } else if (e.key === "ArrowDown" && index < rows.length - 1) {
      e.preventDefault();
      focusRow(index + 1);
    } else if (e.key === "ArrowUp" && index > 0) {
      e.preventDefault();
      focusRow(index - 1);
    }
  };

  const renderRow = (row: T, index: number, style?: React.CSSProperties) => {
    const key = rowKey(row);
    const interactive = !!onRowClick || !!selection;
    const checked = !!selection?.selected.has(key);
    return (
      <div
        key={key}
        role="row"
        data-index={index}
        aria-rowindex={index + 2}
        aria-selected={selection ? checked : selectedKey != null ? key === selectedKey : undefined}
        tabIndex={interactive ? (index === 0 ? 0 : -1) : undefined}
        className={cx("ui-table__row", interactive && "ui-table__row--interactive", rowClassName?.(row))}
        style={{ gridTemplateColumns: template, ...style }}
        onClick={interactive ? () => (onRowClick ? onRowClick(row) : toggle(row)) : undefined}
        onKeyDown={interactive ? (e) => onKey(e, index, row) : undefined}
      >
        {selection && (
          <div role="cell" className="ui-table__cell ui-table__cell--check" onClick={(e) => { e.stopPropagation(); toggle(row); }}>
            <input type="checkbox" tabIndex={-1} checked={checked} disabled={!(selection.canSelect?.(row) ?? true)}
              aria-label={`Select ${key}`} onChange={() => toggle(row)} onClick={(e) => e.stopPropagation()} />
          </div>
        )}
        {columns.map((c) => (
          <div key={c.id} role="cell" className={cx("ui-table__cell", c.align && `ui-table__cell--${c.align}`)}>
            {c.cell(row)}
          </div>
        ))}
      </div>
    );
  };

  let body: ReactNode;
  if (loading) {
    body = Array.from({ length: 8 }, (_, i) => (
      <div key={i} className="ui-table__row" style={{ gridTemplateColumns: template }} aria-hidden>
        {selection && <div className="ui-table__cell" />}
        {columns.map((c) => <div key={c.id} className="ui-table__cell"><Skeleton width={i % 2 ? "70%" : "90%"} /></div>)}
      </div>
    ));
  } else if (rows.length === 0) {
    body = <div className="ui-table__empty">{empty}</div>;
  } else if (virtual) {
    body = (
      <div style={{ height: virt.getTotalSize(), position: "relative" }}>
        {virt.getVirtualItems().map((v) =>
          renderRow(rows[v.index], v.index, {
            position: "absolute", top: 0, left: 0, right: 0, height, transform: `translateY(${v.start}px)`,
          }),
        )}
      </div>
    );
  } else {
    body = rows.map((r, i) => renderRow(r, i));
  }

  return (
    <div className={cx("ui-table", `ui-table--${density}`, virtual && !maxHeight && "ui-table--fill")}
      role="table" aria-label={label} aria-rowcount={loading ? -1 : rows.length + 1} aria-busy={loading || undefined}>
      <div className="ui-table__scroll" ref={scrollRef} style={maxHeight ? { maxHeight } : undefined}>
        <div className="ui-table__grid">
          <div role="rowgroup">
            <div role="row" className="ui-table__row ui-table__head" style={{ gridTemplateColumns: template }} aria-rowindex={1}>
              {selection && (
                <div role="columnheader" className="ui-table__cell ui-table__cell--check">
                  <input type="checkbox" checked={allOn} aria-label="Select all rows"
                    onChange={() => selection.onChange(allOn ? new Set() : new Set(selectable.map(rowKey)))} />
                </div>
              )}
              {columns.map((c) => (
                <div key={c.id} role="columnheader" className={cx("ui-table__cell", c.align && `ui-table__cell--${c.align}`)}>
                  {c.header}
                </div>
              ))}
            </div>
          </div>
          <div role="rowgroup" className="ui-table__body" ref={bodyRef}>{body}</div>
        </div>
      </div>
    </div>
  );
}
