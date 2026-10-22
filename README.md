# Miraflores Workpaper

A web-native tax workpaper for the Okafor-Lindqvist 2025 return. It loads the
pipeline's data packet (`okafor_lindqvist_2025_packet.json`, read-only) and turns
it into an evidence graph you can trace, verify, review, change, file and defend.

**Stack:** FastAPI + Pydantic v2 (Python 3.11+) · React + TypeScript + Vite ·
SQLite append-only event store.

See [APPROACH_AND_DECISIONS.md](APPROACH_AND_DECISIONS.md) for the short version,
[implementation_explanation.md](implementation_explanation.md) for what is built and why, and
[docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md) for tokens and UI primitives.

## Run it with Docker (recommended)

From the project root:

```bash
docker compose up --build
```

Then open the mapped port, `http://localhost:8000` by default. Start at **Status**
(`/status`). The `Dockerfile` builds the UI and serves UI + API from one container.

- **Another host port:** set `HOST_PORT`, e.g. `HOST_PORT=8080 docker compose up --build`,
  then open that port.
- **Persistence:** the event store lives on the `workpaper-data` volume and survives
  restarts. `docker compose down -v` resets it to an empty store.
- **Container hosts** (Render, Railway, Fly.io): point a web service at the `Dockerfile`. The
  container respects `$PORT`, and no environment variables are required.

## Run it with Python + Node

Prerequisites: **Python 3.11+** and **Node 18+** on PATH. From the project root:

```bash
npm run dev
```

Then open `http://localhost:5173`. The API runs on port 8000, with interactive docs at `/docs`.
`Ctrl+C` stops both. The first run sets itself up: it creates `backend/.venv`, installs the
Python requirements and installs the frontend packages.

| Command | What it does |
|---|---|
| `npm run dev` | API with auto-reload (:8000) + UI with hot reload (:5173) |
| `npm start` | Builds the UI, then serves UI + API from one FastAPI process on :8000 |
| `npm test` | Backend tests (pytest), packet sanity check, frontend typecheck, WCAG contrast check |
| `npm run gen:api` | Regenerates the TypeScript API types from the FastAPI OpenAPI schema |
| `python backend/scripts/regression.py <base-url>` | End-to-end regression over HTTP (26 checks across every area). It writes events, so run it against a **fresh** store |

To run the sanity check on its own, use `backend/scripts/sanity_check.py` with the venv's
Python. It loads the packet through the real loader and asserts 74 documents, 3,012 extracted
values and 3 return versions.

**Start over:** stop the app and delete `data/workpaper.sqlite`. The app recreates an empty
store and re-seeds the starting assignments on the next start.

## Layout

```
backend/            FastAPI app
  app/models/       Pydantic v2 models for the whole packet (strict; schema-drift guard)
  app/services/     loader, resolve_ref, text locator, trace, review layer, checks, changes,
                    versions, lifecycle (filing → amendment → notice → carry-forward), search,
                    time/budget, status
  app/api/          routes + strict API response schemas
  scripts/          sanity_check.py, export_openapi.py, regression.py
  tests/            pytest suite
frontend/           React + TypeScript + Vite
  src/api/          typed client (types generated from OpenAPI)
  src/ui/           design system: tokens + primitives (Button, Card, Table, Badge, Panel, …)
  src/components/   app shell, role switcher, global search, trace drawer, review panel, findings
  src/pages/        status, return health, return, documents, viewer, values, findings, variance,
                    adjustments, compare, what-ifs, filing, amendments, notices, carry-forward,
                    review, activity, time & budget, client portal
data/               staged read-only packet copy + workpaper.sqlite event store (git-ignored)
scripts/run.mjs     the one-command runner for the Python + Node path
```

## Using it

- **Acting as** (top right): switch between firm staff and client users. Marcus Bell (`st-04`) has no
  sensitive-data clearance, so the server masks SSNs, IP PINs and account numbers for him and logs his views.
- **Status** (`/status`): the lifecycle stage, what blocks the next step, owners, milestones, budget
  and deadlines.
- **Search** (`/` or Ctrl/⌘K): any reference (`ev-0035`, `D31`, `F1040.11`), or words across documents,
  lines, values, client answers, findings, adjustments, notices, people, activity and screens.
- **Trace any number:** click a line anywhere. The drawer shows its evidence (each source opens the document
  with the field highlighted), how it was built, and where it goes. Documents show where they landed.
- **Return-level sign-off:** the reviewer and partner sign the return as a whole from **Review → Sign off on the
  return**, or inline in the pre-file gate. A later correction or adjustment reopens it; signing again answers it.
- **Review:** verify, leave notes (*Blocks filing*), and sign off as preparer / reviewer / partner. The server
  enforces the firm's rules. Correcting an extracted value reopens every sign-off that covered it.
- **Return health and Checks & findings:** eight areas, 17 computed checks, variance vs 2024. Each finding
  carries evidence, tax effect and, where mechanical, a computed fix.
- **Change:** adjustments (over $1,000 needs a partner), version compare with a reason per line, what-ifs
  (engine results vs labelled estimates), and bulk actions with undo.
- **Filing & after:**
  - extension;
  - pre-file gate and due diligence;
  - client approval + Form 8879 on the client portal, then the ERO signature;
  - e-file, including the packet's real reject and its fix;
  - freeze at filing;
  - amendments on top of the filed return;
  - the Letter 566 response record;
  - carry-forward and 2026 planning.
- **Time & budget:** log time against the firm's budget by area.
- **Activity** is the audit trail: every action is an append-only event. Client users (Ngozi, Erik) get the
  client portal only.

## Configuration

Everything has a working default. See [.env.example](.env.example):
`PACKET_PATH`, `DATA_DIR`, `CURRENT_VERSION`, `API_PORT`.
