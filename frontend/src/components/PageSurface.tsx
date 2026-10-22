import type { ValueOut } from "../api/client";

// The page "image". The packet has no scans, so the surface is reconstructed
// from the extracted fields' positions. The trace contract is
// {document_id, page, position}: to use a real PDF later, render the page
// raster as the sheet background and keep this exact overlay.
export function PageSurface({ values, selectedId, onSelect, pageLabel }: {
  values: ValueOut[];
  selectedId?: string | null;
  onSelect: (id: string) => void;
  pageLabel: string;
}) {
  return (
    <div className="sheet" role="group" aria-label={`${pageLabel}: field layout`}>
      {values.length === 0 && <div className="sheet__empty">No fields were extracted from this page.</div>}
      {values.map((v) => {
        const p = v.position;
        const selected = v.id === selectedId;
        return (
          <button
            key={v.id}
            type="button"
            className={`field-box field-box--${v.match.status}`}
            style={{
              left: `${p.x0 * 100}%`,
              top: `${p.y0 * 100}%`,
              width: `${Math.max(p.x1 - p.x0, 0.02) * 100}%`,
              height: `${Math.max(p.y1 - p.y0, 0.012) * 100}%`,
            }}
            title={`${v.label}: ${v.text_as_read || "(blank)"}`}
            aria-label={`${v.label}: ${v.text_as_read || "blank"}`}
            aria-pressed={selected}
            onClick={() => onSelect(v.id)}
          >
            <span className="field-box__text">{v.text_as_read}</span>
            {selected && <span className="field-box__tag">{v.label}</span>}
          </button>
        );
      })}
    </div>
  );
}
