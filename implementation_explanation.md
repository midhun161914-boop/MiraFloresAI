# Implementation explanation

*My record of how I built the Miraflores workpaper: what I built, why, how it
works, what I traded off, what I assumed, and what I'd do with more time.*

---

## 1. What I built

The packet I was given is pipeline output. It has the documents, every value
the pipeline read from them, and the return as computed at three moments. It is
not a workpaper. A workpaper has to prove the return: for any number, where it
came from, what was done to it, who checked it, and what's still open.

I built it as an **evidence graph with a review layer on top**. The packet
supplies the nodes and edges (documents → pages → extracted values → return
lines → other lines). My application adds everything a firm creates:
verifications, review notes, sign-offs, adjustments and the audit trail.

What the product covers, and where each part is explained:

| Area | Scope | Section |
|---|---|---|
| Backbone | Validated packet, `resolve_ref`, document viewer with highlights, extracted-value browser | 3–8 |
| Design system | Tokens, shared primitives, top bar with role switcher + global search | 9 |
| Trace both ways | line → sources → highlighted doc; doc → where it landed; calc graph | 10 |
| Return health + checks | home surface, prior-year Δ, completeness, error-detector suite | 11–12 |
| Review layer | SQLite event store, verifications, notes, sign-offs, roles | 13 |
| Change & versions | adjustments with tax effect, version compare, what-ifs, undo | 14 |
| Filing & after | extension, pre-file gate, 8879, e-file reject → fix, freeze + amend, notice response, carry-forward | 15 |
| Search, status, time, quality | global search, status surface, time vs budget, generated filing types, performance, accessibility, regression | 16 |

---

## 2. Architecture and stack

**What I built.** A FastAPI backend that owns all the logic, and a React +
TypeScript + Vite frontend that presents it.

- **Backend (`backend/app`)**
  - `models/packet.py`: Pydantic v2 models for the entire packet.
  - `services/loader.py`: stages, hashes, validates and indexes the packet.
  - `services/refs.py`: the reference resolver.
  - `services/locate.py`: the printed-text locator.
  - `services/actors.py`, `services/redact.py`: who is acting, and server-side
    masking for actors without sensitive-data clearance.
  - `services/search.py`: global search.
  - `api/`: routes plus I/O schemas.
- **Frontend (`frontend/src`)**
  - `ui/`: the design system (tokens + primitives); see section 9.
  - A typed API client whose types are **generated from the FastAPI OpenAPI
    schema** (`npm run gen:api` → `schema.d.ts`), so there is one source of truth
    for the contract.
  - React Query for fetching and caching.
  - React Router for deep links. Every screen state that matters (selected
    document, page, value, filters) lives in the URL.
  - `@tanstack/react-virtual` for the long lists.
- **Run:** `npm run dev` runs a small Node script (`scripts/run.mjs`) that uses
  only Node built-ins. It creates the Python venv and installs packages if
  they're missing, then runs uvicorn and Vite side by side. `npm start` builds
  the UI and serves UI + API from one FastAPI process. That is the same shape as
  the Docker image, so production is a single container.

**Why.** The hard parts of a workpaper are backend problems: the evidence graph,
reconciliation, tracing and persistence. My strength is Python/FastAPI, so the
logic lives there and the browser is a client. I chose React over
Streamlit/Gradio because a CPA's daily tool has to feel like a product. It needs
URL-addressable state, keyboard navigation and dense tables, which a notebook UI
doesn't give you.

**Tradeoffs.**
- I wrote CSS by hand on my own token layer instead of using a component
  library. That keeps the bundle small (~87 KB gzipped JS) and every style
  explainable, at the cost of building the primitives myself (section 9).
- I generate the TypeScript types rather than hand-writing them. That adds a
  build step, but the frontend can't drift from the Pydantic models without the
  typecheck failing.
- The one-command path needs only Python + Node. Docker is the deployment path:
  `docker compose up --build` is verified: the API, the UI, deep links, and that
  the event store persists on the volume (section 15).

**If I had more time.** A CI job that runs `npm test` and builds the Docker image
on every push.

---

## 3. Data model (packet side)

**What I built.** Every section of the packet is a Pydantic model
(`backend/app/models/packet.py`).

- The parts the workpaper reasons about are **strict** (`extra="forbid"`) and
  **frozen**: documents, pages, extracted values, return versions, lines,
  assets, diagnostics, changes, firm, client, timeline and agency records.
- Loose reference material is typed as dictionaries: readme prose, engine
  parameters, the 2024 line dictionaries and planning text.

At load I build indexes:
- documents by id
- values by id and by document
- lines by version and key
- client answers, messages, call notes, people, timeline events and prior-year
  assets by id

**Why.** I validated the packet with Pydantic for the same reason I validate LLM
structured output: never trust that an upstream producer kept its schema. If
the pipeline adds or renames a field, the app refuses to start. That's better
than a reviewer seeing silently stale data. The guard worked on its first run.
It caught that `prior_years.return_2024.lines` holds a few text values
(`SchB.7a = "Yes"`, `SchB.7b = "Sweden"`), which my first draft typed as numbers.

**How the graph shows up in the data model.**
- **Nodes:** documents, pages, extracted values, return lines, assets,
  questionnaire answers, messages, call notes, prior-year facts, agency records,
  people, engine parameters, FX rates, timeline events, versions and rules.
- **Edges:** every `ev-…`, `D..`, `py:/…` (and so on) string in the packet.
  These become traversable through `resolve_ref` (section 5).

Line-level `inputs`/`sources` walking and the reverse "where did this document
land" index are built on top of this (section 10).

**Assumptions.**
- Whole-dollar numbers stay integers (`int | float` unions) so the UI never shows
  `212400.0`.
- `v3` is the current return, per `readme.where_now_is`. It is configurable
  through `CURRENT_VERSION`.

---

## 4. Loading the packet: staging, hashing, integrity

**What I built.** `load_packet()` does five things, in order:
1. Reads the canonical packet at the project root. It never writes to it.
2. Copies it into `data/` and marks the copy read-only.
3. Checks that the SHA-256 of the copy matches the original.
4. Parses it into the Pydantic models.
5. Runs `check_integrity()`.

If anything fails, the server doesn't start. `backend/scripts/sanity_check.py`
runs the same loader and prints a report. Current output:

```
ASSERT OK   : documents=74  extracted_values=3012  return_versions=3
  v1: 625 lines, 9 assets, 13 diagnostics, fed total tax 77,200
  v2: 625 lines, 9 assets, 13 diagnostics, fed total tax 77,470
  v3: 627 lines, 9 assets, 11 diagnostics, fed total tax 81,962   <- current
Extraction  : {'extracted': 68, 'not_extracted': 4, 'partial': 2}
Min conf.   : 0.41
Text match  : {'exact': 2975, 'not_found': 8, 'ambiguous': 22, 'empty': 7}
```

**What the integrity checks assert:**
- the expected counts: 74, 3,012 and 3
- unique ids
- every document's pages are numbered 1..n and match `page_count`
- each document's `extraction.values` equals the number of values that point at it
- every value's document and page exist
- every line `source` (`ev-…`) exists
- every line `input` is a line key in the same version
- every line `rule` exists in `engine_reference.rules`
- every document in `documents_used` and `documents_superseded` exists

**Why.** A workpaper that half-loads a packet is worse than one that refuses to
load. The overview screen shows the hash and counts, so anyone can see what
the session is built on.

**Tests** (`tests/test_packet.py`) cover:
- the counts
- that the packet is internally consistent
- that staging never changes the original's hash and leaves a read-only copy
- that an unknown field, an out-of-range confidence and a missing document each fail

---

## 5. `resolve_ref`: one resolver for every pointer

**What I built.** `RefResolver.resolve(ref, version)` handles the whole
`readme.reference_formats` grammar: `ev-NNNN`, `D01..D74`, `doc:<id>#page<n>`,
`qa-`, `msg-` and `call-` ids, `py:/<pointer>` and `agency:/<pointer>`
(RFC 6901), `asset:<id>`, `household:<id>`, `ref:param.<name>`,
`ref:fx.SEK.<rate>`, `timeline:<id>` and line keys. It also handles two kinds of
reference the packet uses without listing them in the grammar: version ids
(`v2`) and rule ids (`R-…`). Every result has the same shape: `kind`, `label`,
`link` (a deep link into the UI), `target` (the node itself), an optional `note`,
and, for anything on a page, the **trace contract**
`{document_id, page, position}`.

It's exposed as `GET /api/resolve?ref=` and `POST /api/resolve/batch`.

**Why.** Think of it as the edge resolver of the knowledge graph. Trace views,
source chips, diagnostics and the jump box never parse reference strings
themselves, so the grammar lives in one place.

**How.** It's an ordered table of regex patterns to handlers. JSON pointers are
resolved against the raw parsed JSON. A line key resolves in the requested
version. If the line isn't there (for example, added in v3 but you asked for v1),
it falls back to the latest version that has it and says so in `note`.

**Regression test.** `test_every_reference_in_the_packet_resolves` collects every
reference string the packet uses (2,860 distinct ones from line sources/inputs,
asset sources, diagnostics, timeline refs and 2024 line sources) and asserts each
one resolves. This is how I'd wire an eval set into CI. It caught two real cases
while I built it:
- Line keys with a hyphen after the dot (`F4562-E.total-A`). I fixed the
  line-key pattern.
- A bare token, `prior_preparer_depreciation_schedule`, that prior-year asset
  records use as a source but that isn't in the grammar.

**Assumption.** I treat `prior_preparer_depreciation_schedule` as an alias for
`py:/prior_preparer_workpaper/depreciation_schedule`. The resolved result is
labelled "Alias of …" so the mapping is visible, not silent.

**On the frontend**, `RefChip` components resolve through a batcher. All chips
rendered in the same tick become one `POST /api/resolve/batch`, and React Query
caches the results forever, because the packet is immutable.

---

## 6. Finding each read on its printed page

**What I built.** `services/locate.py` finds each extracted value inside its
page's `printed_content` and records the character span and a status:
- `exact`: located
- `ambiguous`: printed more than once
- `not_found`: not on the page in any normal formatting
- `empty`: nothing was read

This runs for all 3,012 values at startup.

**Why.** The packet's own readme says `printed_content` is ground truth and
`position` boxes are synthetic. A box drawn from `position` shows where the pipeline *thinks* a field
is. It can't prove what's printed. Highlighting the actual printed words is the
proof. And a value that can't be found on its own page is a direct, mechanical
signal that the read is wrong.

**How.**
1. Try `text_as_read` verbatim.
2. Then try formatting variants derived from the typed value. The pipeline
   normalises what it reads, for example `01/10/2020` for a page that prints
   `2020-01-10`, or `24,800.00` for `24,800`. Checkboxes are read as `X` but
   printed as words like `covered`.
3. Matches are bounded on alphanumerics, so `1,840.00` never matches inside
   `11,840.00`.
4. When a value appears several times on a page, I disambiguate:
   - by row position for indexed fields (`trip7_date` → the 7th entry)
   - by the row that names the lot (`M9_acquired` → the entry containing `M9`)
   - by the nearest preceding anchor (`Box 5` beats `Box 3` for the identical
     118,000.00 on a W-2)

The first naive version left 896 values unlocated, almost all formatting
differences. After the variants and anchors, 2,975 are exact, 22 genuinely
ambiguous (identical values repeated in a row), 7 blank and **8 not found**.

**Tradeoff.** This is heuristic. I chose to surface "ambiguous" honestly rather
than force a guess. The highlighted spot is the best candidate, and the badge
says how many times the value appears.

---

## 7. The document viewer: simulated source documents

**What I built.** `/documents/:id?page=&ev=` has three columns:
- **Page rail.** Each page's value count. Pages the pipeline never read are hatched,
  and pages with an unlocated read get a red dot.
- **The page itself**, in two panels:
  - **Printed content (ground truth).** Rendered in a serif face. Every located
    value is underlined, and the selected one is highlighted on the real words.
  - **Page surface.** A page-proportioned sheet with every extracted field drawn
    at its `position`. The selected field gets a label tag, and fields not found
    on the page are drawn dashed red.
- **Side panel.** The selected value's typed value, text as read, printed-page
  status (including "printed as …" when a variant matched), confidence, field
  and reference. Below it is the page's value list (↑/↓ walks it).

Clicking a value anywhere (list, printed text or page surface) selects it in all
three places and updates the URL. Any value is therefore a shareable deep link:
`/documents/D09?page=1&ev=ev-0039`.

**Why the two panels.** There are no page images. The only honest
"representation" I can draw from `position` is the pipeline's own field layout,
so I label it that way. The printed text sits above it as the ground truth.

**Real PDFs later.** `PageSurface` takes `{document_id, page}` plus overlay boxes
from `position`. To drop in a real PDF, render the page raster as the sheet
background and keep the overlay exactly as is. Nothing in the trace links
changes.

**Header flags:** extraction status and reason, *Issuer marked CORRECTED* (D31),
*Superseded in v3 — figures must not flow to the return* (D30), and *Not used by
the current return*. Pages the pipeline didn't read (e.g. D30/D31 page 32,
"Additional transactions") show a callout that anything printed there is not in
the extracted values.

---

## 8. Extracted-value browser, document index, overview, jump box

- **Extracted values (`/values`).** All 3,012 values, filtered server-side and
  rendered in a virtualized table (~25 DOM rows at a time). You can filter by
  search, document, value type, max confidence and printed-page status, and sort
  by id, lowest confidence or document/page. Filters live in the URL. Clicking a
  row opens the value highlighted in its document.
- **Documents (`/documents`).** The index of all 74 documents. Each row shows who
  it belongs to, when it was received, pages, values, extraction status, status
  in the current return (used / superseded / not used) and flags (CORRECTED,
  reads not on page, low confidence). Filter chips show their counts.
- **Overview (`/`).** The proof that the packet loaded: counts and hash, the
  "reads that need a human look" signals (each a link into a filtered view), and
  a side-by-side of v1/v2/v3 federal and California summaries.
- **Reference inspector (`/ref?r=…`).** Reference kinds without a dedicated
  screen open here. It renders the resolved node with every nested reference
  as a clickable chip, so no link in the app is dead.
- **Global search** (top bar; sections 9 and 16) replaced an early jump box.

---

## 9. Design system

**What I built.** Before building tracing, I established a design system and
built every screen on it. Reference: [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md).

- **Tokens (`frontend/src/ui/tokens.css`)** are the only place raw values live:
  - **Type.** Inter (self-hosted via `@fontsource-variable/inter`, so it works
    offline and in Docker). A 13px base for data density, a scale of 11/12/13/14/16/20/24,
    and three weights.
  - **Space.** An 8pt grid with a 4px half-step.
  - **Colour.** Cool neutral grays and **one accent** (indigo), reserved for
    interaction and selection. **Four semantic statuses** (verified / open /
    warning / error) plus neutral.
  - **Evidence highlight.** A pale yellow used only for the cited words on a
    source page.
  - No decorative gradients anywhere.
- **Primitives (`frontend/src/ui`):** `Button`/`ButtonLink`, `Card`, `Table`,
  `Badge`, `Panel`/`PanelSection`, `PageHeader`, `SearchInput`, `Select`,
  `FilterGroup`, `ConfidenceMeter`, `Stat`, `Callout`, `EmptyState`,
  `ErrorState`, `Skeleton`. Every screen is composed from these.
- **Domain components** on top: `RefChip`, `MatchBadge`, `ExtractionBadge`,
  `UseBadge`, `Avatar`, `RoleSwitcher`, `GlobalSearch`.
- **App shell:** a persistent 48px top bar with the engagement, global search and
  role switcher; a quiet side nav with counts and a "packet verified" footer; a
  skip link.

**Why.** My bar was that a 20-year CPA finds it more trustworthy than their
current tool. Trust is partly visual. Consistent status language means a
red badge always means the same thing:
- verified = checked and fine
- open = needs attention
- warning = possibly wrong
- error = wrong or must not flow through

Numbers line up in columns, and nothing decorative competes with the data. One
set of primitives also keeps every screen consistent without re-deciding
spacing each time.

**How the key pieces work.**
- **Table.** One component for every list, from the 3 return versions to the
  3,012 values. It's a CSS-grid layout with ARIA table roles, so columns are sized
  with grid tracks and the same markup can be **virtualized**. It has built-in
  skeleton and empty states. Keyboard: Tab into the table, ↑/↓ to move, Enter to
  open.
  - **A bug I caught in the browser.** Rapid ↓ presses went out of step because
    focus moved in a deferred animation frame, so Enter could open a different
    row than the one highlighted. Focus now moves synchronously when the row is
    already rendered, and defers only when the virtualizer must render it first.
- **Panel.** The right-hand evidence panel, which also hosts the trace.
  `PanelSection scroll` makes the value list scroll on its own, so the current
  selection stays pinned at the top. The first version scrolled the selection
  out of view, which I found when checking it in the browser.
- **Accessibility.**
  - `npm run check:contrast` reads `tokens.css` and checks 24 text/background
    pairs against WCAG AA. All pass, and it runs inside `npm test`.
  - A visible focus ring, one `h1` per screen, labelled landmarks, combobox and
    listbox semantics for search and the role switcher, and `aria-live` where
    content updates.
  - A browser sweep found no unnamed controls.
  - `prefers-reduced-motion` disables the skeleton shimmer.
- **States.** Every async surface has loading (skeletons), empty (with an
  action, e.g. "Clear filters") and error (with "Try again") states, plus an
  unknown-route page.

**Data-presentation decisions a CPA will notice.**
- **Refunds in accounting style.** A negative balance due shows as `(8,256)` in
  tables and "Refund 8,256" in summaries, never "−8,256".
- **Tighter confidence colouring.** The meter is red below the firm's 80%
  threshold, amber from 80–90% and neutral above. My first draft turned every
  routine 90% read amber, which diluted the signal.

### Top bar: role switcher and global search (both functional)

**Role switcher.** "Acting as" lists every firm staff member and both client
users, with role, credential, assignment ("assigned preparer") and clearance. It
works fully by keyboard. The chosen identity is sent as an `X-Actor-Id` header on
every API call, and the **server** decides what that actor may see:
- For an actor without `sensitive_data_clearance` (Marcus Bell, `st-04`), the
  backend masks SSNs, IP PINs and account/routing numbers everywhere: printed
  text, extracted values, reference records and search.
- Masking is **length-preserving** (`666-41-2287` → `•••-••-2287`), so the
  locator's highlight spans stay exact for every role. IP PINs are masked in
  full.
- Masked values can't be found by searching their content.
- Switching roles resets the client cache, so nothing fetched under one identity
  is shown under another.
- A tested guarantee: an uncleared actor never receives a full SSN from any
  endpoint (`tests/test_actors.py`).

**Global search** (`/` or Ctrl/⌘K) is one box that returns:
- an exact reference hit (anything `resolve_ref` accepts)
- grouped matches across documents, current return lines, extracted values and
  client answers/messages

All search terms must match, and identifier-prefix matches rank first. The
results support ↑/↓, Enter and Esc.

**Tradeoffs.**
- Visibility (masking, client surface) is enforced per request. The **view log**
  and permission rules (no self-review, partner sign-off) run on the event store
  (section 13), keyed by the same `X-Actor-Id` identity.
- The identity is not authenticated. It's a role switcher for a prototype. Real authentication would replace the header with a session.

---

## 10. Tracing both ways

**What I built.** The spine of the workpaper: any return number is one click from
its documents and one click from its math, in both directions.

| Direction | Question it answers | Where |
|---|---|---|
| number → evidence | Which documents, pages and fields produced this? | drawer **Evidence** tab; line page side panel |
| number → math (down) | How was it built, rule by rule, down to the evidence? | drawer **How it's built**; line page |
| number → math (up) | What does it feed, up to the totals? | drawer **Where it goes**; line page |
| document → numbers | Which lines does this document feed, or why none? | document **Where it landed** tab; documents index |

**How it works (backend, `services/trace.py`).**
- **Indexes built at startup:**
  - value → lines, per version
  - line → the lines that consume it (`used_by`)
  - document → every record elsewhere in the packet that names it or its
    values (timeline, agency notices, basis records, messages, line notes)
- **Every edge goes through `resolve_ref`.** Each source of a line comes back as a
  `RefResolution` carrying the trace contract `{document_id, page, position}`, a
  deep link and a label. The UI never parses reference strings.
- **Evidence behind records.** Some lines cite a record rather than a value:
  - `py:/return_2024/lines/F8606.14` points to its own extracted value on D06.
  - `asset:AUS-BLDG` lists its sources.

  The service expands these, so D06 is correctly reported as landing
  *indirectly*, and a record source shows the evidence behind it.
- **Endpoints:**
  - `GET /api/lines/{key}`: sources with printed excerpts, inputs, used-by,
    value by version, 2024 as filed, diagnostics, and the size of the calc
    closure.
  - `GET /api/lines/{key}/graph?direction=down|up`: the subgraph for the tree.
  - `GET /api/documents/{id}/landing`: the reverse trace.
  - Line listings now carry `change` from the previous version.
  - Each version's summary figures map to the line that carries them
    (`federal.total_tax → F1040.24`), found by exact value on the main form, so
    the overview's headline numbers are traceable too.

**"Didn't land" is explained, never silent.** The landing service derives a
status and reasons from the data:
- **duplicate.** Another document of the same type whose read values match
  field by field (≥ 90% of shared fields). Line notes that mention the document
  are cited as corroboration. D10: 17 of 17 fields match D09, and `F1040.1a`'s
  note agrees.
- **superseded.** Listed in the version's `documents_superseded`. The
  replacement is the same issuer and type, preferring the one marked CORRECTED.
  It also shows the version and trigger that superseded it, and earlier versions
  that used it. D30 → D31, since v2, used in v1.
- **partially extracted.** Only pages the pipeline *says* it skipped count as
  unread (named in `extraction.reason`). The reason quotes what is printed on
  them.
- **not extracted / not used / support only.** Carries the pipeline's own
  reason, plus every record that mentions the document (e.g. D72 ← IRS Letter 566
  notice; D54 ← the home's basis record).
- Documents that land show their lines with the exact values (and any record
  they travelled through), and how many of their values went uncited.

**The UI** is built only from the design system:
- **Trace drawer.** Opened by `?trace=KEY` on any screen, so it's linkable and
  Back or Esc closes it. Three tabs.
  - **Evidence:** each source shows a mini page with the cited field's position
    box, plus the printed excerpt with the figure highlighted.
  - **An independent foot check:** "the 2 source values add to 212,400 — equal to
    the line". When the rule isn't a straight sum, it says so instead of
    implying a mismatch.
  - **Source links keep the drawer open:** opening a source document keeps the
    trace visible beside the highlighted field.
- **Calc tree** (`CalcTree`) is a real ARIA tree:
  - It's lazy. Only expanded branches render, which matters when total tax has
    522 lines under it, 39 levels deep.
  - Each row shows the line key, label, rule id and rule text, and the value.
  - Leaves expand to their evidence.
  - A line reached by two paths is marked "also above".
  - Keyboard: ↑/↓, → expands, ← collapses or goes to the parent, Enter traces
    that line.
- **Line page** (`/lines/F1040.11`): both trees plus the evidence panel, with a
  version switcher.
- **Return screen** (`/return`): all 627 lines, virtualized and filterable by
  form, jurisdiction and "changed in vN". One click opens the trace.
- **Everywhere else:** line chips everywhere open the drawer. The document
  viewer gains a **Where it landed** tab and a "Feeds" row on each value. The
  documents index gains a landing column and "Doesn't land / Duplicate /
  Superseded" filters. The values browser gains a "Feeds" column. Global search
  opens lines in the drawer.

**Real PDFs later.** The tracing layer only ever passes
`{document_id, page, position}`. The mini page and the viewer overlay draw from
it, so swapping the rendered page for a PDF raster changes neither the API nor
the trace components.

**Tradeoffs.**
- The calc tree is a tree, not a node-link diagram. At 500+ nodes a drawn graph
  is unreadable. An indented, collapsible tree with rule text on every row is
  what a reviewer can actually read and walk with a keyboard.
- I show the foot check only when every source is numeric and there's more than
  one. A false "mismatch" on a non-sum rule would erode trust faster than no
  check at all.

**Tests (`tests/test_trace.py`, 19 cases).** They cover:
- wages to both W-2 box 1 values, with position and excerpt
- record sources exposing the evidence behind them
- the down graph reaching wages from total tax, and the up graph from wages to
  total tax
- each "didn't land" case: D10 duplicate, D30 superseded → D31, D31 page 32
  unread and quoting "proceeds 250.00", D07 not extracted, D06 indirect
- every non-landing document has a reason
- summary-line mapping
- clearance masking on trace payloads

---

## 11. Return health: areas, variance and the check suite

**What I built.** The layer that turns the planted errors into **formal, computed
findings**, and the home surface a reviewer reads first.

- **`services/checks.py`: a registry of 17 checks** in four kinds:
  - *reconciliations*
  - *error detectors*
  - *independent re-computations*
  - *completeness proofs*

  Each check is a function over the packet and the event-sourced review state.
  It returns pass/fail/warn plus findings. A finding carries severity, area,
  computed facts, evidence refs, the return lines it touches (each one opens its
  trace), a tax effect where the packet's `tax_effect_rates` allow one, and a
  cross-reference to the engine's own diagnostic when there is one.
- **Nothing is hard-coded to a document or line.** The M18 lot is found because
  the summary−lots arithmetic fails and the unread page's text parses into a lot.
  The duplicate interest is found because two payer lines are equal *and* their
  documents print the same account number.
- **A broken check fails loudly.** The runner turns an exception into a failing
  check rather than a silent pass.
- **`services/health.py`** builds:
  - **Variance flags** under the firm rule, applied exactly: more than 10% **and**
    more than $1,000 vs 2024.
  - **Eight area summaries:** current figure, Δ vs 2024, open findings, notes,
    variances, verification state, owner, budget hours.
  - **Return totals.**

  It caches the check run on (version, last event seq), so any review action
  re-runs the suite.
- **Decisions are events.** A finding can be *resolved*, *accepted* (the fix
  follows as an adjustment, section 14) or marked *not an issue*, always with a note. Only
  a reviewer who didn't prepare the affected lines can wave off an error. A
  variance explanation is an event too.

**The checks and what they found** (current return v3):

| Check | Result |
|---|---|
| Broker summary vs sum of lots | **Error.** D31 summary 71,965 vs lots 71,715. The unread page 32 prints lot M18 (proceeds 250, basis 310) and fully explains the 250. The missing −60 short-term loss is worth federal −21 / CA −2; the CA side is flagged to confirm sourcing, since it was sold after the move. Engine agrees (it saw the gap, not the cause). |
| W-2 wages and withholding | Pass. 2 distinct W-2s foot to `F1040.1a`, federal and CA withholding. D10 is shown as a duplicate *correctly* excluded; counting it would have made wages 320,200. |
| Payments vs IRS/FTB records | **2 errors.** Federal: the IRS transcript has 4 × 3,000 = 12,000 vs `F1040.26` 13,000 → +1,000 due. California: the FTB credits 10,500 to 2025 vs `F540NR.72` 14,000 → +3,500, because a 3,500 payment was applied to 2024. Engine missed both. |
| S-corp basis roll-forward | Agrees. The chain is rebuilt from the 2022 record, the late 2023 K-1 (D40, closing the prior file's gap) and the 2024 record → 2,300 = `F7203.1`. Warnings: distributions exceed basis by 21,215 (capital gain), and Ridgeline's outside basis isn't tracked. |
| Sales at zero basis | **Error.** RSU lots N1/N3/N4 are taxed at basis 0. D11 gives 19,100 + 19,100 + 9,420, matched by acquisition date. Gain is overstated by 47,620: federal −15,536, CA −2,764; N1 and N3 were sold during CA residency, so they use `ca_source_income`. Engine missed it. Crypto C6: basis unknown, at most federal −1,853 (upper bound); engine agrees. |
| Same income twice | Warning. `SchB.1.1` / `SchB.1.2`, 1,840 each, from D28 and D29, both printing account ending 7731 → −1,840 interest, federal −640 / CA −127. Engine missed it. |
| FX rate year | **Error.** `SchB.1.6`: SEK 18,450 at the 2024 rate (10.56) instead of 2025 (9.86) → +124 interest. Engine missed it. |
| Reads that don't stand up | The 0.41 receipt prints `$?,500.00` ("could be read as 1 or 7") → at stake +6,000 itemized: federal −1,560 / CA −288 (engine agrees). The provider EIN not printed on D62 shows as *corrected* once the correction event is recorded. |
| Client answers vs documents | 3 conflicts: qa-14 "No" sales vs 282 brokerage sales (engine agrees); qa-15 "didn't really sell" vs 12 digital-asset disposals; qa-31 "no prior IRA basis" vs 7,000 on the 2024 Form 8606. |
| Due diligence | Warning. CTC/ODC claimed; Form 8867 not documented (firm rule). |
| Totals reproduce from inputs | 85 sums and 46 carries reproduced (signed arithmetic, zero floors). 4 California column-D lines foot only with their column-B/C sibling, which their input list omits (info: the value is right, the trace graph is incomplete). |
| 8949 → Schedule D cross-foot | Pass, 6 boxes. |
| Depreciation recalculated | Pass, 9/9 assets federal and CA: straight-line mid-month 27.5-yr with the disposal month, the MACRS 5-yr half-year table, 100% bonus vs CA's no-bonus, §179. |
| Superseded docs don't flow | Pass. D30 feeds nothing. |
| Documents accounted for | Pass. 74/74, each with a status and reason. |
| Outside filings | FBAR required (max SEK 1,452,300 ÷ 9.71 = $149,567) and 1099-NECs required (Mara Quintero 4,800; Dev Patel 2,600, late). Both are excluded by the engagement letter, so the client must be told. Also Ada's own return, the S-corp 1120-S and Oregon composite (confirm Erik is included), Ridgeline's 1065, and Arizona composite (no partner filing). |
| Every area considered | Warning until an area has current verification or sign-off work. |

**Tax effects.**
- **Income items:** change × `tax_effect_rates[category]`. A sale during
  California residency uses `ca_source_income` for the CA side, as the packet
  instructs.
- **Payments:** 1:1 on balance due.
- **Unknowns:** shown as an *upper bound*, never as a fact.

**Engine cross-check.** 7 of the engine's 11 diagnostics are independently
reproduced. The other 4 (AMT credit carryforward, AOTC phase-out, CA AMT not
computed, home-office area change) are listed as "not independently checked". 10
of our non-info findings are ones the engine raised no diagnostic for.

**Areas.**
- **The eight requested areas.** Lines are assigned to areas by a small
  form/line rule table (`area_of`). Return-level totals sit in a separate
  totals strip.
- **Headline figure per area**, compared with 2024:
  - Wages compares `F1040.1a` and shows the **+36.1%** jump, flagged.
  - California compares with the 2024 resident CA540 only where the lines truly
    match.
- **Status:** *needs attention* (open errors, blocking notes, reopened sign-offs),
  *in progress*, or *clear*.
- **Owner:** the engagement preparer from `firm.assignment_at_start` until an
  area assignment event exists.

**Tradeoffs.**
- **The questionnaire rules are a small table** of patterns plus evidence
  functions. Matching free-text answers needs *some* encoding of meaning. I kept
  it explicit and tested rather than pretending it's general NLP. An
  LLM-assisted matcher (structured output, citing the answer and the evidence)
  is a natural next step.
- **Footing is signed but rule-blind.** The engine's "arithmetic combination"
  doesn't say which inputs subtract, so I accept any sign assignment that
  reproduces the value. A line reproduced only with an omitted sibling is
  reported, not hidden.

**Mistakes I caught in my own work** (this part of the product is about trust):
- **My exploration printout truncated input lists**, and I first concluded that
  `SchB.2` and `SchD.15` omitted inputs. The full lists are complete. The suite's real
  incomplete-inputs findings are the California column-D lines, and I corrected
  the statement.
- **My first California prior-year mapping paired `F540NR.32` "California AGI"
  with 2024's `CA540.32` "Exemption credits"**, producing a bogus +24,929% flag.
  Cross-form pairs now require matching labels, and a regression test pins it.
- **A CSS class collision** (`.check` with the review layer's checkbox label) laid the check
  suite out two per row. I renamed it.

**Tests:** `tests/test_checks.py`, 23 cases.
- Each planted error must surface with the expected facts and tax effect.
- The independent checks must pass.
- The variance rule is applied exactly (every flag >10% and >$1,000; wages
  +36.1%).
- The eight areas, dispositions as rule-checked events, masking of finding text
  for uncleared staff, and the label-matched CA540 pairing are each covered.

---

## 12. Errors found, and how the design surfaced them

Every row below is also a computed finding in the check suite (section 11), with its tax effect where computable.

| # | What | How it surfaced |
|---|---|---|
| 1 | **Childcare provider EIN misread at 0.97 confidence.** `ev-1045` (D62, Little Sprouts) reads `74-3829516`; the page prints `74-3829156`, two digits transposed. v3 line `F2441.1b` cites it as a source, so the provider ID on Form 2441 would be wrong. | Locator: **Not on page** despite 97% confidence. Not one of the commonly expected error types. |
| 2 | **Handwritten donation read with false precision.** `ev-1049` (D64) reads `1,500.00` at 0.41; the receipt prints `$?,500.00` and notes the first digit could be 1 or 7. | Locator: **Not on page**, plus the lowest confidence in the packet. Top of "lowest confidence first". |
| 3 | **Values read where nothing is printed.** D28 lots N1–N5 "wash sale loss disallowed" read as `0.00`, but the page prints no wash-sale figure for those lots. D08 W-2 box 10 is read as `0.00` but box 10 isn't printed. Benign in amount, but they are fabricated reads. | Locator: **Not on page**. |
| 4 | **RSU lots taxed at zero basis.** D28 lots N1, N3 and N4 print `basis (not reported)`; the pipeline recorded basis `0` with a blank reading, and v3 carries it through: `F8949.B.N1` (19,240), `F8949.B.N3` (18,480) and `F8949.E.N4` (15,300) all show "basis 0.00". That is 53,020 of gain at zero basis on shares whose value was already taxed as wages (D08 box 14 shows RSU 38,200). D11 is a supplemental RSU statement with adjusted basis per lot. | Locator: **Blank** reads on the lots, visible in the D28 viewer. The reconciler ties 8949 basis to D11 and the W-2 and quantifies the tax effect. |
| 5 | **Superseded document.** D30 (original Meridian 1099) is superseded by D31 (CORRECTED) in v3. | Document index: *superseded* status and banner; *CORRECTED* badge on D31. |
| 6 | **The broker mismatch is an unread page.** D31 page 32 ("Additional transactions") was never extracted. It prints lot **M18 Ironwood REIT, cash in lieu, proceeds 250.00, basis 310.00, short-term noncovered**. 71,965 (broker summary) − 71,715 (sum of extracted lots) = **250**, so the planted `BROKER_SUMMARY_DETAIL_MISMATCH` is fully explained by this lot, and the return is missing a 60 short-term loss. | Reverse trace on D31: "Partially extracted — page 32 unread", quoting the page. Pages 11–31 ("no further transactions") are correctly *not* called unread. M4 will turn this into a reconciler finding with tax effect. |
| 7 | **Duplicate W-2 image.** D10 is a phone photo of the Halvorsen W-2 (D09). | Reverse trace: **Duplicate of D09 — counted once**, with the 17-of-17 field match and `F1040.1a`'s note as corroboration. The wages trace shows exactly two sources (D08, D09), and they foot to 212,400. |
| 8 | **Wages up sharply from 2024.** `F1040.1a` is 212,400 against 156,039 as filed for 2024 (+36%). | Shown in every wages trace ("2024 as filed"). The variance review flags it formally (>10% and >$1,000). |
| 9 | **Estimated payments overstated.** Federal by 1,000 and California by 3,500 against the IRS transcript and FTB account (the 3,500 FTB payment was designated to 2024). | Reconciler findings (errors) with a 1:1 balance-due effect; the engine raised nothing. |
| 10 | **SEK interest converted at the 2024 rate.** | FX detector against `fx_rates`; fix = the 2025 rate. |
| 11 | **Duplicated Schedule B interest.** `SchB.1.1` and `SchB.1.2` are the same 1,840. | Detector finding with a computed fix. In the demo it becomes the post-filing amendment. |
| 12 | **S-corp distributions exceed stock basis by 21,215, and Ridgeline outside basis isn't tracked.** | Independent basis re-computation plus a basis-gap finding. |
| 13 | **Questionnaire vs documents.** "No" investments sold against 282 sales; "some crypto" against 12 disposals; the Roth answer against the 2024 return. | Questionnaire-conflict findings citing the answer and the documents. |
| 14 | **Dependent TIN typo from the organizer.** Theo is `666-74-3309` in the household data; his Social Security card (D71) reads `666-74-3390`. This is the real cause of the R0000-504-02 reject. | The pre-transmit TIN check against the SSA document. It is fixed *from the evidence* and resubmitted. |
| 15 | **Schedule C gross receipts vs 1099-K.** The engine adds the whole 1099-K (12,400) as "not matched to a books deposit". | The Letter 566 bridge raises it as a question to confirm before sending, not as a conclusion. |

---

## 13. Review layer, roles and persistence

**What I built.** The packet has no review state at all, so everything here is
the workpaper's own. It's stored as an **append-only event log** in SQLite
(`data/workpaper.sqlite`) and projected into the review layer:
- **verifications**: how a number was checked, using
  `firm.starter_standards.verification_types`
- **review notes**: blocking or not, with a threaded reply / resolve / reopen
- **sign-offs**: at the preparer → reviewer → partner levels
- **value corrections**: a misread extracted value corrected to what the
  document prints
- **assignments**: seeded once from `firm.assignment_at_start`
- **a sensitive-data view log**

**The event store (`services/events.py`).**
- **Rows.** One row per action: `seq`, `id`, `at`, `actor`, `actor_role`,
  `type`, `node` (a line key, `ev-NNNN`, `D09`, `return` or `engagement`),
  `version`, a JSON `payload`, and `reverts` (the event an undo/withdraw/reopen
  acts on).
- **Append-only, enforced by the database.** SQLite triggers abort every
  `UPDATE` and `DELETE`, and a test proves it.
- **WAL mode** for concurrent readers. Writes take a lock, and each rule check
  runs *inside* that lock as a guard, so a check and the write it protects can't
  interleave with another writer.
- **What this design gives the rest of the product:**
  - *Undo* is a new event pointing at the one it reverts.
  - *"What changed since I last looked"* is `seq > my_last_seq` (`GET
    /api/events?since=`).
  - *Version compare* replays the log to any `seq`.
  - The activity page is just the log.

**Projection (`services/review.py`).** On start the service folds every event into
in-memory state, then applies each new event as it's appended. A restart or a
browser refresh rebuilds the same state, so persistence comes for free. A test
restarts the app on the same database and finds the note still there, and
assignments aren't seeded twice.

**Sign-offs that reopen themselves.**
- **What's captured at sign-off:** a sign-off (and a verification) records the
  effective value of every extracted value beneath the node, plus a fingerprint.
  "Beneath" means everything reachable through sources, inputs, records and
  assets: one value for a leaf line, 1,900+ for total tax.
- **What happens on a correction:** when a value changes, every active sign-off
  that covered it is reopened by an automatic `signoff.reopened` event (actor
  `system`). The event records exactly what changed (`ev-1045: 74-3829516 →
  74-3829156`) and which event caused it.
- **Verifications go stale too**, by the same comparison.
- **Signing up the chain:** signing AGI covers the evidence of all 441 lines
  under it, so a correction to any wage or interest value reopens it.

**Enforced rules (server-side; the UI only mirrors them).** Each refusal returns
403 with the rule's own wording. A refusal caused by someone else's earlier write
returns 409.

| Rule (from the packet unless noted) | Enforcement |
|---|---|
| "A person may not review or sign off on work they prepared." | A node's *preparers* are everyone who verified it or anything beneath it, signed it at preparer level, or corrected evidence beneath it. They can't sign it as reviewer or partner, or clear its blocking notes. |
| "Open review notes block filing." | Readiness lists every open blocking note (and every reopened sign-off) as a blocker. The top-bar chip shows the count on every screen. A blocking note on a node also blocks its reviewer/partner sign-off. |
| Review levels preparer → reviewer → partner | Role per level (a reviewer sign-off needs a reviewer or partner). Reviewer sign-off needs a current verification or a preparer sign-off; partner sign-off needs an active reviewer sign-off. |
| Blocking notes are cleared by review (my rule) | Only a reviewer or partner who didn't prepare the work can resolve a *blocking* note. A non-blocking note can be resolved by its author. |
| Sensitive data: masked without clearance, "every unmasked view is logged" | Masking is server-side. Every response carrying sensitive data writes a `view.logged` event, unmasked views (the firm's rule) and masked access by uncleared staff such as Marcus (a stricter rule I added) alike, with endpoint and field count. Repeats within 30 s coalesce. Uncleared staff can't correct sensitive values. |
| Clients see only the client surface | Every firm router carries a `require_staff` dependency: client identities get 403 from documents, values, lines, trace, review, events and overview. They get `/api/client/home` (their uploads, answers, messages) and a separate shell. |
| Administrators and quality reviewers | No verifying, signing or correcting. The view log is readable by administrators, partners and quality reviewers. Everyone else sees only their own entries. |

**No lost writes.**
- Note actions carry the `last_seq` the user saw; if someone replied in between,
  the write is refused (409) instead of overwriting.
- Sign-offs carry the fingerprint the signer looked at; if the evidence changed
  since, it's refused with "review the change, then sign". This check runs first,
  so a stale screen is the first thing reported.

**UI (design-system components only).**
- `ReviewPanel` appears in the trace drawer's **Review** tab, on the line page
  and on any selected value in the document viewer ("Review & correct"). It
  shows verifications, the sign-off ladder, and threaded notes, plus corrections
  for values. Every button the rules would refuse is disabled with the server's
  reason (e.g. "Reviewer sign-off needs a partner or reviewer; you are acting as
  preparer").
- **Review queue:** filing readiness, blockers, open notes, reopened sign-offs,
  corrections, assignments.
- **Activity & view log:** the event stream, filterable by type.
- **Elsewhere:** a Review column on the Return table, the readiness chip in the
  top bar, and the client portal.

**Demo (walked in the browser; the 11 events it produced, in order):**
1. **Priya** verifies `F2441.1b` (agreed to D62) and leaves a blocking note → "1
   filing blocker". She can't clear her own blocking note (refused inline).
2. **Daniel** can't sign while the note is open. He resolves it → "No blockers",
   then signs as reviewer.
3. **Priya** corrects `ev-1045` (the transposed provider EIN, planted error #1)
   to what D62 prints. Daniel's sign-off **reopens automatically** with the diff,
   Priya's verification goes stale, and the blocker is back.
4. **Marcus** opens D09: `SSN •••-••-2287`. The view log records "Marcus Bell —
   masked view — D09". He sees only his own entries; Jo (administrator) sees
   everyone's.
5. **Ngozi** (client) gets the client portal only. A direct call to
   `/api/documents` returns 403.

**Bugs I found by driving the demo, and fixed.**
1. *The trace drawer covered the document viewer's own panel*, so you couldn't
   correct a value with the trace open. On wide screens the drawer now docks:
   the page makes room for it.
2. *The drawer re-took focus on re-render*, which could steal keystrokes from an
   input beside it. It now takes focus only when it opens.
3. *Switching to a client refetched the open staff screens under the client
   identity*. The server correctly answered 403s, but the requests shouldn't
   happen. Switching to a client now drops the firm cache instead; staff-to-staff
   switches still refetch, so no unmasked data lingers.

**Tests:** `tests/test_review.py`, 17 cases. They cover:
- append-only triggers
- restart persistence and single seeding
- the full demo flow as one test
- no self-review, including work beneath a total
- level order and method validation
- lost-write refusals (stale note, changed fingerprint)
- administrator and client refusals
- client surface 403s on seven firm endpoints
- masked access and its log entries (with coalescing and visibility)
- uncleared staff can't correct sensitive values

**Tradeoffs.**
- **Projection in memory, log on disk.** Fine for one engagement and a
  single-process server. With several workers I'd move the projection to a read
  model updated from the log, or rebuild per worker from `seq`.
- **The identity header isn't authentication.** It's the prototype role
  switcher; a real deployment puts a session behind it.
- **Corrections don't recompute the return.** The engine can't be rerun. A
  correction changes the *evidence*, reopens what was signed on it, and leaves
  the line's value and label as the engine produced them. Adjustments
  (section 14) carry the tax effect.
- **Docking the drawer** at 1440px narrows the document's printed-text column. I
  accepted that; collapsing the viewer's own panel while the drawer is open is
  still on the list (section 16).

**Built on this same event store:** the partner rule for adjustments over
$1,000 and the digest (section 14), filing, freeze and amendments (section 15),
and time logging and status (section 16).

---

## 14. Change & versions

This part is about changing the return without losing what it was, and seeing
what changed. Everything sits on the same append-only event store as the review
layer. Nothing here edits the packet or deletes an event.

### Adjustments are not corrections

A **correction** fixes a misread *extraction* (the document says 1,240 and
we read 1,420). An **adjustment** changes a *return line* because the
treatment is wrong, even though the document was read correctly.

- **The original is preserved.** The engine's value stays in the packet. An
  adjustment is an overlay: `adjustment.proposed` → `approved` / `rejected` →
  `reversed`, each an event carrying who and why. The Return page shows the
  engine value struck through next to the adjusted value. Lines an adjustment
  adds (the missing M18 lot) appear as rows with rule `ADJUSTMENT`.
- **Tax effect.** Each adjustment is priced with the version's
  `tax_effect_rates`, federal and California. Sales during the CA residency
  period use `ca_source_income`. Payment changes move the balance due 1:1. When
  an adjustment's lines match a finding's fix, it reuses the finding's
  already-computed tax effect, so the two never disagree.
- **Partner rule, server-side.** I parse the threshold out of the firm-rule text
  in the packet ($1,000). If the effect is over it in *either* jurisdiction, the
  adjustment stays `pending_partner` and becomes a filing blocker. Only a
  partner can approve, and not the partner who proposed it. Approval requires a
  note. Reversing an active partner-level adjustment also needs a partner. A
  proposal checks for stale values (`STALE`) the same way corrections do.
- **From findings.** Findings with a mechanical fix carry it as a `fix`
  (line → new value):
  - RSU zero basis: basis from the supplemental statement, per lot;
  - duplicated Schedule B interest line → 0;
  - missing broker lot M18 → a new line;
  - FX rate → the 2025 rate;
  - federal and CA estimated payments.

  "Propose adjustment" on the finding creates the adjustment with the finding's
  evidence refs and tax effect. The finding then shows `adjustment pending` or
  `adjusted` instead of `open`.

### Comparing versions and states

`/compare?a=&b=` diffs any two of the following:
- engine `v1`, `v2` or `v3`;
- `v3` plus the workpaper's active adjustments now;
- a **saved state**, which is a `state.saved` event. It is replayed by folding
  adjustment events only up to that event's sequence number, so it shows the
  workpaper exactly as it was.

Every changed line gets a *why*, assembled from:
- an adjustment's id, reason and approver;
- an evidence change (`D30 → D31`, `— → D37`), found by comparing the documents
  beneath the line in each version;
- whether the line is listed in the version's `changes_from_previous`;
- whether it's a computed line that moved because its inputs did;
- the version's own trigger text.

For long diffs, lines are grouped by form. Large groups start collapsed.
Headline figures (AGI, taxable income, total tax, payments, balance due, CA
tax) sit on top, and a filter searches line, label and reason. v2 → v3 is 87
changed and 2 added lines across 16 forms.

### What changed since I last looked

The bell in the top bar counts other people's events after your last
`user.seen` event. The `/whats-new` page lists them in plain words. Your own
events, view-log entries and bookkeeping events are left out. "Mark all as
seen" appends a `user.seen` event. So the digest is per user, persistent, and
derived entirely from the log.

### What-ifs: engine results vs estimates

- **Scripted.** The five alternatives in the packet are engine results. I show
  them as the engine computed them, with an "Engine result" badge: federal and
  CA tax before and after, plus every line that changes.
- **Ad-hoc.** Change any category or line by an amount. The result is
  `kind: "ESTIMATE"`: change × `tax_effect_rates`. A dashed amber ESTIMATE
  banner and a disclaimer from the server ("not an engine recompute …
  thresholds and phase-outs the rates do not capture") appear above and beside
  every result, and each estimated figure is marked with ≈. Example: harvesting
  $10,000 of long-term losses ≈ −2,380 federal and −340 CA.

### Bulk actions and undo

Bulk verify (selected Return lines) and bulk disposition (selected findings)
write one ordinary event per item, each tagged with a shared `bulk_id`. Each
item runs through the same rule check as the single action. Items that fail are
reported back as refused; the rest are applied.

**Undo** appends a reversing event per item (`verification.withdrawn`, a
`reopened` disposition) and is checked against the rule for undoing that item
singly. Only the person who recorded a verification can withdraw it, so
Daniel's attempt to undo Priya's bulk is refused (`UNDO_NOT_ALLOWED`). Undo
never deletes: after Priya's undo the log holds 12 `recorded` and 12
`withdrawn` events for those lots.

### The change workflow, verified end to end

1. Priya proposed the RSU basis fix from the `ZERO_BASIS_WITH_KNOWN_BASIS`
   finding:
   - three lots, N1 19,240 → 140, N3 18,480 → (620), N4 15,300 → 5,880;
   - tax effect −15,536 federal, −2,764 CA.

   It went to `pending_partner` and appeared as a filing blocker.
2. Priya and Daniel tried to approve it. The server refused both with
   `PARTNER_REQUIRED`, shown inline on the card. Helen approved it with a note.
   It became active and the blocker cleared.
3. Compare v2 → v3. For example:
   - `SchE.28B` was added at 8,400, from new evidence D37 (the Ridgeline K-1);
   - `F7203.1` stock basis went 8,200 → 2,300 (evidence D40);
   - `F1040.37` amount owed went 35,728 → 4,220.
4. Showed the scripted *standard deduction* alternative (engine: +12,306 federal)
   and ran an ad-hoc estimate, shown with its ESTIMATE label.
5. Priya bulk-verified 12 Form 8949 lots (`B-E24AEF`). Daniel's undo was
   refused. Priya undid it from Activity, and all 12 lots are unverified again.

Screenshots: `docs/screenshots/adjustment-pending-partner.jpg` and
`docs/screenshots/reviewer-approve-refused.jpg`. I checked the rest of the flow
against the rendered page text and the API responses.

Tests: `backend/tests/test_changes.py` (13 tests) covers:
- the partner threshold and its refusals;
- no self-approval;
- findings → adjustments with the finding's effect;
- stale-value rejection;
- saved-state replay;
- compare reasons;
- estimate labelling;
- digest exclusions;
- bulk partial refusal;
- undo role rules.

---

## 15. Filing & after

This part takes the return from the extension to the following year, and it all runs on
the same append-only store. `services/lifecycle.py` keeps its own projection,
folded from the log like the review layer. Every command checks its rules inside
the write lock. Agency answers come from the packet, never from my own
invention:
- the extension uses `what_if.extension`;
- e-file responses use `tax_agency_records.efile`;
- the notice is `tax_agency_records.notices` (Letter 566, D72);
- carryovers come from `prior_years.carryovers_into_2025` and each version's
  `carryovers_out`;
- planning uses `planning_reference_2026`;
- interest and penalty use `post_filing_rates`.

### Extension

**Record extension** is reviewer/partner only, and only once. It stores Form 4868
with 36,000 and FTB 3519 with 0, based on v2. I recompute the packet's rule
("balance due rounded up to the next 500") and show that it matches:
35,728 → 36,000, and CA's −9,131 → 0. The page repeats the packet's warning
that an extension to file is not an extension to pay.

### The pre-file gate

A single function, `gate()`, decides whether the return can go out. It blocks on:
- any open blocking note;
- reopened sign-offs and pending partner adjustments (the review layer's readiness);
- every **error** finding that is still open or only has an adjustment pending;
- a missing **reviewer** or **partner** sign-off on the return;
- every **due-diligence** item still required.

Due diligence comes from the firm rule (CTC, ODC, AOTC, EIC, HOH) and the return
itself. CTC (`F8812.4`) and ODC (`F8812.6`) are claimed. AOTC is computed but
phased out, so it's not applicable. Completing an item is a Form 8867 record:
five yes-answers plus what was asked, entered by a preparer-level role.

The gate also lists the firm's twelve `required_steps` with a status for each.
The server calls `gate()` again when the return is presented, so the UI can't
present a blocked return.

### Return-level sign-off

The gate's two sign-off rows are **return-level**: the reviewer and the partner
sign the return as a whole, not a line. It's the same `signoff.recorded` event
and the same rules as any sign-off:
- **Reviewer before partner.**
- **No self-review.** For the return, "prepared it" also includes anyone who
  proposed an adjustment that is in force or pending.
- **Reopens when the return changes.** The fingerprint covers every source value
  beneath the return *and* the adjusted line values in force. A correction
  reopens it through the existing evidence check. An adjustment that takes effect
  or is reversed reopens it with the changed lines listed.

The control is reachable from where the gate sends you. Each gate row's
*Sign off* link opens it on the Review page's Filing readiness card
(`/review#return-signoff`, focused on arrival), and it also appears inline in the
gate while either sign-off is outstanding.

Fixing this surfaced a latent bug: signing again after a reopen didn't clear the
reopened blocker. A reopened sign-off is now treated as answered once the same
level signs the same node again. That applies everywhere sign-offs reopen.
`tests/test_return_signoff.py` covers all of this.

### Client approval and Form 8879

1. **Present** (reviewer/partner, gate clear). This freezes the figures shown to
   the client and fingerprints the return's values and figures. The figures are
   the engine summary plus the effect of active adjustments: the income change
   is added to AGI (CA AGI only where the change is California-taxed), and tax
   and balance use `tax_effect_rates`. The basis is printed under every figures
   table.
2. **Each taxpayer approves and signs** on the client surface
   (`/api/client/filing/approve`). Staff are refused (`CLIENT_ONLY`). The client
   ticks the attestation and enters a five-digit self-select PIN; only a one-way
   hash is stored. If the return changes after presentation, signing is refused
   (`CHANGED`) and the firm must present again.
3. **The ERO signs.** This must be the firm's signing preparer
   (`firm_identity.paid_preparer_signing_returns` = Helen), and only after both
   taxpayers have signed (`CLIENT_FIRST`).

### E-file, the real reject, and the fix

**Transmit** is reviewer/partner only, and only with a current presentation, both
8879 signatures and the ERO signature. The agency's answer is decided by the data:
- Before transmitting, I check each dependent's TIN on the return against the SSA
  document in the file (`identity_document` belonging to that dependent).
- Theo's TIN on the return is `666-74-3309`, from the organizer. His Social
  Security card (D71, `ev-1080`) reads `666-74-3390`, so the federal submission
  gets the packet's recorded reject: `71530420261940012345`, **R0000-504-02**,
  "dependent 2". California gets its `STATE-HOLD`.

**The fix** corrects the TIN *from the evidence*: you point at `ev-1080`, the new
value is read from it, and the event records from → to, the document and the
reason. It needs a preparer-level role with sensitive-data clearance; Marcus is
refused (`CLEARANCE`) and only ever sees masked SSNs. Two consequences:
- A TIN isn't an 8879 amount, so the signatures stand.
- Resubmission gets the packet's acceptances: federal `71530420261950019871` and
  CA `71530420261950019872`.

### Freeze at filing

When both are accepted, a system `return.filed` event stores a snapshot:
- every line's value as filed (engine plus adjustments), and the figures;
- the adjustments in force and the identity used;
- the event sequence number at freezing, plus a hash of the snapshot.

A **store-level policy** that I added to `EventStore.append` then refuses
anything that would change the filed return, whichever service sends it. That
covers:
- adjustments;
- extraction corrections;
- verifications;
- sign-offs;
- TIN corrections;
- filing steps, including bulk actions and undo.

It returns `FROZEN` with "Changes go into an amendment". Notes, dispositions and
reading stay open. The filed page re-hashes the snapshot every time it's shown
("snapshot intact").

The page also shows an interest and failure-to-pay figure for a balance paid
after 2026-04-15. It's computed from `post_filing_rates` and the timeline's
payment date, and labelled an ESTIMATE because the IRS computes it (transcript
code 196/276). On the demo return it's zero, because the adjustments turned the
balance into a refund.

### Amendments

An amendment (`amend:<id>` version tag, the only one the freeze policy lets
through) records the filed snapshot hash it's based on. Each amended line holds,
in 1040-X terms:
- A, as filed;
- B, the net change;
- C, the correct amount;
- why, and who;
- its evidence refs;
- an estimated tax effect.

Lines can come from a finding's computed fix. Approval needs a partner who didn't
prepare it. The filed record is never touched: the demo shows the snapshot hash
unchanged and SchB.1.2 still 1,840 "as filed" after the amendment set it to 0.

### Letter 566

**Assemble response** builds a self-contained record from the filed return and
the workpaper. For each item under examination, it holds the relevant lines as
filed. Each line carries:
- every source value beneath it: document, issuer, page, position, text as
  printed, effective value and confidence (sensitive values are masked);
- each value's verifications;
- the line's own verifications, sign-offs, notes and adjustments;
- an enclosure list of the documents.

The record is stored in the event with a hash, so what was sent can be shown
later exactly. A partner marks it sent. **Gaps** are flagged before sending: in
the demo, 21 and 7 source values have no recorded verification.

For item 2 (Schedule C vs 1099-NEC 142,000 and 1099-K 12,400), the response
builds a bridge from the engine's own rule for the line ("books revenue plus Form
1099-K amounts not matched to a books deposit"), with the IRS figures parsed from
the letter text:

| | Amount |
|---|---|
| NEC per IRS | 142,000 |
| Other books revenue | + 9,300 |
| Unmatched 1099-K | + 12,400 |
| **Line 1 as filed** | **163,700** |

It also raises a question rather than a conclusion: the "unmatched" 1099-K equals
the whole 1099-K, so confirm none of it was already deposited into the books.

### Carry forward and 2026

Each carryover shows:
- into 2025, from the 2024 return (D06/D07);
- the amount used in 2025;
- out to 2026, from the filed version;
- its history across v1 → v2 → v3. For example, the minimum tax credit went
  3,722 → 3,700 → 3,871 and was *generated* in 2025.

California basis differences carry per asset. Next-year planning comes from
`planning_reference_2026`:
- federal safe harbor: 110% of the filed 2025 tax in four installments on the
  packet's dates;
- CA: 30/40/30, with the caveat that 2026 California tax will be far lower
  because only California-source income is taxed;
- the household's known 2026 changes.

**Open the 2026 file** writes the carryovers with their history and the planning
into a `carryforward.rolled` event.

### Docker (verified)

The stack runs with `docker compose up --build` from the project root: one
container, with the SQLite event store on the `workpaper-data` volume. I chose
not to add Postgres; a single SQLite file in WAL mode is enough for one firm
process, and the event store is plain SQLAlchemy Core if that changes. I
verified:
- `GET /api/health` returns ok with the packet hash;
- `/` and the deep link `/filing` serve the built UI;
- `/api/filing/gate` answers;
- after `docker compose restart`, an event written before the restart is still
  there, so the volume persists.

The walkthrough below ran against that container. The host port is
configurable (`HOST_PORT`, default 8000) in case 8000 is already in use.

### The filing workflow, verified end to end (container, fresh store)

1. **Gate with things open.** Daniel opened a blocking note. The gate showed 10
   items: the note, 5 open errors, 2 missing sign-offs and 2 due-diligence items.
   Presenting was refused with `GATE_BLOCKED`.
2. **Clearing it.**
   - Priya proposed the RSU fix; Helen approved it.
   - The FX fix applied without a partner.
   - Daniel accepted the 3 remaining errors with a note (one bulk action) and
     resolved the note.
   - Priya completed CTC and ODC due diligence.
   - Daniel and Helen signed off the return. The gate was clear.
3. **Approval + 8879.**
   - Daniel presented the return.
   - When the return changed after presentation, the presentation went stale:
     Ngozi's signature on it was refused (`CHANGED`), and Daniel presented again.
   - Helen's ERO signature before the clients was refused (`CLIENT_FIRST`).
   - Ngozi signed in the client portal UI and Erik signed.
   - Daniel's ERO attempt was refused (`ROLE`); Helen signed with EFIN 731504.
   - The 8879 amounts: federal AGI 398,094, tax 66,469, refund 11,273; CA tax
     16,119, refund 11,011.
4. **Reject → fix → accept.**
   - Priya couldn't transmit (`ROLE`). Daniel transmitted: R0000-504-02 plus the
     state hold.
   - Marcus's correction was refused (`CLEARANCE`). Priya corrected Theo's TIN
     from D71 in the UI.
   - Daniel resubmitted: both accepted, frozen at event #31, snapshot
     `be94d3d4f22b16fd`.
5. **Frozen.** An adjustment and a verification were both refused with `FROZEN`.
6. **Amendment AMD-075687.** SchB.1.2: 1,840 → 0 (net −1,840; ≈ −640 federal,
   −127 CA, labelled ESTIMATE). Priya's own approval was refused; Helen approved.
   The filed snapshot is unchanged.
7. **Letter 566.** Assembled (record hash shown). Priya's "mark sent" was
   refused; that's partner only.

I checked every screen from its rendered text and every refusal from the
server's response.

Tests: `backend/tests/test_lifecycle.py` (6 tests) runs the whole lifecycle on an
empty store: gate → 8879 → reject → fix → accept → freeze → amendment → notice →
carry-forward, plus the refusals.

**Typed end to end.** The lifecycle documents are strict Pydantic response models,
and the frontend types are generated from them (section 16).

---

## 16. Search, status, time and quality

These parts make the workpaper faster to use, or harder to get wrong.

### Global search

The base search covers references, documents, lines, values and client answers.
`search_workpaper` in `services/search.py` adds six more groups:
- **findings** → the Findings page filtered to that one finding, opened;
- **adjustments**;
- **agency notices**;
- **people** — household members, staff, client users;
- **activity** — every event except view-log entries and "seen" marks;
- **screens** — "8879" finds Filing, "1040-X" finds Amendments.

It's the same combobox as before: `/` or Ctrl/⌘K to focus, ↑/↓ to move, Enter
jumps, Esc closes.

The privacy rules carry over:
- People results show names and roles, never identifiers.
- Event search skips the `from`/`to` of identity corrections and the PIN hash, so
  nobody can find an SSN by typing it.
- Client users are refused.

It runs in about 30 ms server-side over the packet plus a 3,000-event window.

### Time vs budget

Staff log time against the firm's own buckets (`firm.budget_hours`: intake, the
seven areas, partner review). Each entry is a `time.logged` event, in quarter
hours, at most 16 per entry, with a note saying what the time was for. A wrong
entry is voided (`time.voided`), and only by the person who logged it. That's the
same append-only undo as everything else.

The Budget page shows, per bucket: budget, logged, remaining, a meter, who logged
it, and a status. The statuses are *not started*, *under*, *near* (85% or more)
and *over*. Over-budget buckets also appear on the status page.

**Assumption.** There was no time data in the packet, so nothing is seeded. Time
appears as people log it; the regression script logs 4 h to Business to show
"over".

### Status at a glance

`/status` (first in the nav) is derived live from the services that already
enforce the rules, with no state of its own. It shows:
- **Stage.** Preparing → awaiting client approval → authorized → transmitted (fix
  the reject) → filed. After filing it can be *amendment in progress*, *amendment
  approved*, or *agency notice open*.
- **Headline and next step.** Who does what next, with a link straight to it.
- **Outstanding.** Counted, linked, and coloured by severity: error findings,
  blocking notes, pending partner adjustments, due diligence, warnings,
  unexplained variances, missing signatures, open amendments and notices.
- **Owners**, from the event-sourced assignments plus the ERO.
- **Milestones** with who and when: extension, gate, presentation, signatures,
  ERO, reject, acceptance, amendment, notice, roll-forward.
- **Budget and deadlines.** The firm's deadlines plus the notice's response date,
  sorted.

### The filing types are generated

I first typed the lifecycle documents by hand in the frontend, which was the one
place front and back could drift. I closed it:
- Every lifecycle response is declared as a Pydantic model in
  `api/lifecycle_schemas.py`, attached as `response_model`.
- Every model has `extra="forbid"`, so a field the service returns but the model
  doesn't declare fails response validation, and the tests run the whole
  lifecycle.
- `frontend/src/api/lifecycle.ts` is now only aliases into the generated
  `schema.d.ts`.
- A test checks that the schemas are in OpenAPI and strict
  (`additionalProperties: false`).

**Gaps this surfaced, now fixed:**
- **Missing frontend fields.** The hand-written types lacked the extension view's
  `source`, each piece of evidence's `position` and `correction`, a line's
  `notes`, the full per-line tax effect on amendments (category, change, bound),
  carry-forward's `amendments`, and everything a roll-forward records.
- **Name collisions.** Three of my new model names (`Position`, `Owner`, `NoteIn`)
  collided with existing schemas. OpenAPI had silently renamed the *existing*
  ones, which would have broken the generated `Position` type the viewer uses.
  I renamed mine.
- **Untyped fields.** The status payload's `budget` and `deadlines` came out as
  untyped dicts and are now real models.
- **A stray field.** The strict time-entry model caught an `entry_id` I was
  leaking.

### Performance on the big views

| View | Rows | DOM rows rendered | Jump to the middle |
|---|---|---|---|
| Extracted values | 3,012 | ~31 | — |
| Return, Form 8949 | 303 | ~45 | ~50 ms |
| Area page, investments | 366 | ~42 (newly virtualized) | ~50 ms |
| Document landing (e.g. D31) | long lists | virtualized | — |

The last two were the remaining unvirtualized long lists. `Table` gained a
`maxHeight` prop, so a virtual table can sit inside a normal page instead of a
fill-height card.

Server timings, measured against `127.0.0.1` (not the `localhost` name, which on
some systems adds an IPv6 fallback delay to every call):
- search: ~30 ms;
- all 3,012 values: ~120 ms (1.4 MB);
- the v3 lines: ~30 ms;
- compare v2→v3: ~5 ms;
- status: ~6 ms.


### Accessibility and states

- **Focus on navigation.** On every route change (not on filter or drawer changes)
  focus moves to the main region and the tab title becomes the page heading, so
  keyboard and screen-reader users land on the new screen. Checked in the
  browser: focus on `#main`, title "Return status · Miraflores".
- **ARIA.** New progress and budget bars are `role="meter"` with values. The
  lifecycle stepper uses `aria-current="step"`. Search result kinds have icons
  *and* text.
- **Icon-only buttons.** An audit found none without an accessible name.
- **States.** Every page has a loading skeleton, an error state with retry where
  it can be retried, and an empty state.
- **One refusal wording.** Server refusals now read "Refused by the server: …"
  everywhere. Before, there were three wordings.

### Design consistency

The new screens use only the existing tokens and primitives (Card, Badge, Table,
Callout, PageHeader, stepper). A token check runs over every new stylesheet; all
tokens resolve, and the WCAG contrast check still passes.

### Cold-start regression

`backend/scripts/regression.py` is a standard-library script that drives the
whole product over HTTP against a running app, with **26 checks**:
- **Packet and serving:** packet counts, `resolve_ref`, the SPA deep link.
- **Tracing.**
- **Review layer:** verify, sign, a correction that reopens, masking, the client
  refusal.
- **Checks:** health, checks including the M18 lot, variance.
- **Change:** partner gate, compare, ENGINE vs ESTIMATE, bulk and undo rules.
- **Filing & after:** extension, gate, 8879 order, the reject → fix → accept,
  freeze, amendment, the Letter 566 bridge, carry-forward.
- **Search, budget, status.**

I ran it twice, both from a fresh event store:
1. **npm path.** `npm run dev` with `EVENTS_DB` pointed at a new file: 26/26.
2. **Docker path.** `docker compose down -v` (volume deleted),
   `docker compose build --no-cache`, then `up`: 26/26. A restart showed the
   state persisted.

The shipped event store is empty. pytest has **138 tests**.

### Still rough, or deferred (honest list)

- **Amendment filing.** The amendment has no e-file or 8879 cycle of its own;
  status says "file … outside this build" once it's partner-approved.
- **Figures after adjustments.** The engine can't be rerun, so post-adjustment
  totals use `tax_effect_rates`. They're labelled with their basis everywhere,
  but they're linear estimates.
- **Agency responses are replayed.** E-file responses come from the packet's
  record: a mismatched dependent TIN gets the recorded reject, anything else the
  recorded acceptance. It isn't a real transmitter.
- **No time data in the packet.** Budgets start empty. There's no timer and no
  billing rates.
- **The values page loads everything.** It fetches all 3,012 values (1.4 MB) up
  front, then virtualizes. Fine here; a much larger file would want paging.
- **The digest polls.** Live push (server-sent events) isn't built; the bell
  refetches every 15 s.
- **Single process.** One SQLite file with WAL. Several processes or hosts would
  want Postgres; the event store is plain SQLAlchemy Core and the triggers are the
  only SQLite-specific part.
- **Few screenshots.** `docs/screenshots` holds two; I verified the other
  screens from rendered text, DOM measurements and API responses.
- **No AI inside the product.** An "explain this number" assistant over the
  evidence graph would fit naturally, but I put the effort into the workpaper
  itself, so every number on screen traces to the packet.
- **Viewer panel while the trace drawer is open.** On mid-width screens the
  document viewer's side panel and the trace drawer share space. On wide screens
  the drawer docks. Collapsing the viewer's panel while the drawer is open is
  still open.
- **Port 8000 in use.** If another service holds it, set `HOST_PORT`, for example
  `HOST_PORT=8080 docker compose up --build`.

---

## 17. How I used AI tools

I built this with Claude Code, an AI coding agent, in small increments that I
checked running before moving on. I set the stack, the architecture, the firm
rules to enforce and the quality bar: Linear / Stripe / Mercury-grade, an 8pt
grid, one accent, semantic status, WCAG AA. Before any feature code, I had it
verify that the packet loads and the counts match. The agent wrote the code and
tests, ran them, and drove the app in a browser to check the flows end to end.

What that caught, beyond the unit tests:
- **Driving the real UI.** Table and calc-tree keyboard focus drift, the evidence
  panel scrolling the selection away, the trace drawer hiding the viewer's panel,
  focus stealing, and refetches under a client identity (section 13).
- **Checking data before trusting a first result.**
  - The first landing pass called 22 pages of D31 "unread". Reading them showed
    21 are filler; only page 32 was skipped, and it holds the missing $250 sale.
  - The 8879 figures adjusted tax but not AGI. Fixing that made a presentation go
    stale, which is exactly the safeguard the flow needs.
  - The Letter 566 reconciliation first summed the P&L on top of the 1099s. It
    was rebuilt from the engine's own rule for the line.
- **Checking refusals at the source.** Every refusal was checked against the
  server's response, not just the UI: partner-required, no self-approval, undo by
  someone other than the verifier, clearance, freeze.
- **Strict schemas as a checker.** Making every lifecycle response model forbid
  extra keys turned drift into failing tests. That surfaced missing frontend
  fields, three name collisions, and a stray field in new code.
- **Measuring instead of asserting.** The HTTP regression script runs from a fresh
  store on both the npm and Docker paths. Performance claims come from measured
  DOM row counts and response times.

The agent made no product decisions about tax treatment. Every number on screen
comes from the packet, or from a rule that is labelled with its basis.

---

## 18. Assumptions log

- `v3` is the current return (`readme.where_now_is`); configurable.
- `prior_preparer_depreciation_schedule` is an alias for
  `py:/prior_preparer_workpaper/depreciation_schedule`.
- An unqualified line key resolves against the current version, falling back to
  the latest version that contains it. The fallback is labelled.
- "Low confidence" means below 80% for now. That's a display threshold; it will
  move into the firm standards so an administrator can change it.
- The packet's `position` boxes are only used to place overlays, never as
  evidence (per `readme.no_page_images`).
- "Sensitive data" means SSNs, IP PINs, and bank account and routing numbers.
  Names, DOBs, phones and emails stay visible to uncleared staff, because they're
  needed to do the work. The rule lives in `services/redact.py`.
- Client users (`cu-01`, `cu-02`) see their own household's identifiers
  unmasked, since they supplied them. They get no firm permissions.
- **Duplicate:** same document type, and at least 90% of the fields both
  documents read are identical, and the other document lands. It's a
  conservative rule: two genuinely different W-2s from one employer would differ
  in their amounts.
- **Unread:** a page the pipeline names in `extraction.reason`. A page with no
  fields is not unread unless the document is partial and names no pages.
- **Support only:** used by the engine, but no line cites any of its values. I
  don't guess *why* a document was used (identity, reconciliation). I show what
  else in the file mentions it.
- **Preparers of a node** include anyone who did preparer work *beneath* it, so
  verifying wages bars you from reviewing AGI. It's strict, but that's what "work
  they prepared" means when numbers roll up.
- **Blocking notes** can only be cleared by a reviewer or partner who didn't
  prepare the work. That's my reading of "open review notes block filing"
  combined with the no-self-review rule.
- **The view log** records both unmasked views (the firm's rule) and masked
  access by uncleared staff (stricter than the rule), coalesced within 30 seconds.
- **Variance:** a change from a prior value of 0 counts as over 10% (an unbounded change). 2024 California figures come from a resident CA540; a 540NR line is compared only with the CA540 line whose label matches.
- **Area of a line:** a short ordered rule table by form and line (e.g. Schedule E lines 27+ are pass-throughs, the rest rentals). Return totals (lines 9, 11, 15, 24 …) are not an area.
- **Tax-effect sign convention:** positive = more tax or more owed. Payment findings change the balance due 1:1 and the tax not at all.
- **Adjustment vs correction:** a correction fixes what we *read*; an adjustment
  changes what the *return* says. Both are events and neither overwrites the packet.
- **Partner threshold:** "tax effect over $1,000" means |federal| > 1,000 or
  |CA| > 1,000 (each jurisdiction separately, not the sum), measured with
  `tax_effect_rates`. The number is parsed from the firm rule in the packet.
- **Saved states** capture the workpaper (adjustments) at a sequence number.
  Engine versions are immutable, so they are compared directly.
- **Digest** excludes your own events, view-log entries and bookkeeping events
  (`user.seen`, bulk markers, assignments).
- **Undo of a bulk** reverses only items still in effect. Items someone else
  already withdrew are skipped, and items the undoer may not reverse are
  reported back.
- **Figures presented for approval** are the engine summary plus active
  adjustments. Income changes go into AGI, CA AGI only where the change is
  California-taxed, and tax and balance use `tax_effect_rates`. The engine can't
  be rerun, so these are labelled with their basis.
- **The e-file response** is chosen by the data: a dependent TIN on the return
  that doesn't match the SSA document in the file gets the packet's recorded
  reject, otherwise its recorded acceptance. The response timestamps are the
  packet's.
- **Signers** are the firm's client users (both spouses, MFJ). The ERO is
  `firm_identity.paid_preparer_signing_returns`.
- **Frozen** means anything that changes the filed return is refused. Notes,
  finding dispositions and reading stay open, because post-filing work (like a
  notice) needs them.
- **Notice line mapping:** Letter 566 item 1 → SchA.11/12/14 and the two Form 8283
  lines; item 2 → SchC.1. A short table in `lifecycle.py`.
- **Summary figure → line:** the first line on the main form (F1040 / F540NR)
  with exactly that value. California's negative balance due has no matching
  line, so it isn't linked rather than guessed.

## 19. If I had more time

- Amendment e-file (`amendment.filed`) with its own 8879 cycle, reusing the filing steps.
- Server-sent events for the digest and status, replacing polling.
- A paged values endpoint for files much larger than 3,012 values.
- E-sign PINs through a real signature provider, and a printable Form 8879 PDF.
- Run ad-hoc what-ifs through a real recompute (the engine isn't in the packet), so estimates could be confirmed instead of only labelled.
- Word-level diffs for long text reasons in the compare view, and a "since my saved state" shortcut on every page.
- Area assignment and re-assignment as events from the area page, with notifications.

- A "path to the total" breadcrumb in the drawer, e.g. 1a → 1z → 9 → 11 → 15 →
  … → 24, as a one-line summary above the up tree.
- Value-level diffs in the trace between versions: which source changed when a
  line changed from v2 to v3.

- A dark theme. The tokens are role-based (`--bg`, `--text-primary`, …), so it's
  a second token block, not a rewrite.
- Column sorting and resizing in `Table`, and a density toggle (compact /
  comfortable) saved per user.

- Render the page surface at true PDF fidelity once real files exist. The
  contract already allows it.
- Fuzzy (edit-distance) matching in the locator, to say "printed as 74-3829156,
  read as 74-3829516: two digits transposed" instead of just "not on page".
- Persist the locator results and expose them as a typed evidence edge
  (`ev → printed span`) in the graph API.
