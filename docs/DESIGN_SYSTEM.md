# Design system

A short reference for building screens. The reasoning behind it lives in
[implementation_explanation.md §9](../implementation_explanation.md#9-design-system).

**Principles:** a calm instrument, not a dashboard toy. Neutral surfaces. One accent,
used only for interaction and selection. Status colour carries meaning, never
decoration. Dense tables with tabular numbers, and whitespace *between* groups
rather than inside them.

## Tokens: `frontend/src/ui/tokens.css`

| Group | Values |
|---|---|
| Type | Inter Variable (self-hosted). Scale 11 / 12 / **13 (base)** / 14 / 16 / 20 / 24 px. Weights 420 / 520 / 600. `tabular-nums` on every table and number. Document text uses a serif so source material reads differently from the app. |
| Space | 8pt grid with a 4px half-step: 4, 8, 12, 16, 24, 32, 40, 48, 64 |
| Size | controls 24 / 32px · table rows 32 (compact) / 40 (default) · top bar 48 · side nav 216 · side panel 380 |
| Radius | 4 / 6 / 8 |
| Neutrals | gray-0 … gray-900 (cool). Roles: `--bg`, `--bg-canvas`, `--bg-subtle`, `--border*`, `--text-primary/secondary/tertiary` |
| Accent | `--accent` #4747c9 (indigo): links, primary buttons, selection, focus ring |
| Status | **verified** green · **open** blue · **warning** amber · **error** red · neutral gray. Each has `-fg`, `-bg`, `-border`, `-solid`. |
| Evidence | `--highlight` (pale yellow), only for the cited words on a source page |

`npm run check:contrast` (also part of `npm test`) reads this file and checks 24
foreground/background pairs against WCAG AA. All pass, including tertiary text
and every status badge.

## Primitives: `frontend/src/ui`

| Primitive | Use |
|---|---|
| `Button`, `ButtonLink` | variants `primary` · `secondary` · `ghost` · `danger`; sizes `sm` · `md`; icon-only when no children |
| `Card` | `title`, `description`, `actions`, `footer`; `flush` for a table body |
| `Table` | column defs with CSS-grid widths; `onRowClick`; keyboard ↑/↓/Enter; `virtual` for thousands of rows; built-in skeleton and empty state |
| `Badge` | tones `neutral` · `verified` · `open` · `warning` · `error` · `accent` · `outline`; optional status `dot` and `icon` |
| `Panel`, `PanelSection` | right-side detail/trace panel. A `scroll` section fills the remaining height so the sections above it stay pinned. |
| `PageHeader` | breadcrumbs, title, meta row, actions |
| `SearchInput`, `Select`, `FilterGroup`, `Kbd` | toolbar controls. `FilterGroup` is a radio or toggle pill group with counts. |
| `ConfidenceMeter`, `Stat`, `Callout` | small data displays |
| `EmptyState`, `ErrorState` (with retry), `Skeleton`, `PageSkeleton` | every async surface has all three states |

Domain components built on these live in `src/components/`: `RefChip`, `MatchBadge`,
`ExtractionBadge`, `UseBadge`, `Avatar`, `RoleSwitcher`, `GlobalSearch`.

## Status vocabulary

| Tone | Means | Examples |
|---|---|---|
| verified | checked and fine | extracted, on page, packet verified |
| open | needs attention, not wrong | corrected document, notes |
| warning | possibly wrong | partial extraction, repeated on page, 80–90% confidence, identifiers masked |
| error | wrong or must not flow through | not on page, superseded, < 80% confidence |
| neutral | informational | not used, blank |

## Keyboard

`/` or `Ctrl/⌘ K` focuses search. ↑/↓ and Enter work in search results, tables,
the page's value list and the role switcher. Esc closes popovers. There's a skip
link to the main content, and every control has an accessible name (checked in
the browser).
