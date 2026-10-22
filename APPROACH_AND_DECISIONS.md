# Redesigning the Tax Workpaper — Approach & Key Decisions

**The case.** The Okafor-Lindqvist 2025 return: 74 documents, 3,012 extracted
values and three engine versions.

**What I built.** A working web workpaper. It runs with `npm run dev` or
`docker compose up --build`. The full first-person record, with every decision,
assumption and finding, is in
[implementation_explanation.md](implementation_explanation.md).

## Core idea

A workpaper has to answer four questions for any number on the return:
1. **Where did it come from?**
2. **What was done to it?**
3. **Who checked it?**
4. **What's still open?**

I built it as two layers:
- **An evidence graph**, read-only from the packet:
  - return line ⇄ input lines ⇄ extracted value ⇄ document, page and position;
  - every pointer goes through one resolver (`resolve_ref`), in both directions.
- **A review layer**, an append-only event log. It records verifications, review
  notes, sign-offs, corrections, adjustments, filing steps and time.

Everything you see is derived from those two things. The packet is never edited.

## Key decisions and tradeoffs

1. **Python + Pydantic v2 at the boundary.**
   - The whole packet is validated into strict models at load (`extra="forbid"`),
     so schema drift fails at startup, not in a screen.
   - It's the structured-output discipline I use on LLM pipelines.
   - The API responses are strict models too, and the frontend types are
     *generated* from them, so front and back can't drift.
2. **Evidence as a graph, traced both ways.**
   - Any number shows its sources with the exact field highlighted, plus its calc
     tree.
   - Any document shows where it landed: lands, superseded, duplicate, unread
     page, support-only.
   - It's modelled like a GraphRAG knowledge base. The trace contract is
     `{document_id, page, position}`, so a real PDF can drop in later.
3. **An append-only event store.** SQLite in WAL mode, with triggers that abort
   UPDATE and DELETE.
   - Undo is a *reversing* event, under the same rules as the original action.
   - Sign-offs fingerprint the evidence beneath them, so a later correction
     reopens them automatically.
   - The tradeoff: projections are folded in memory. Simple and fast at this
     scale, and the store is plain SQLAlchemy Core if it needs Postgres later.
4. **The server enforces every rule; the UI only explains.**
   - The firm's rules are checked inside the write lock, and refusals come back as
     the rule's own text:
     - no self-review;
     - blocking notes block filing;
     - adjustments over $1,000 need a partner;
     - masking plus a view log for uncleared staff;
     - clients see only the client surface.
   - The UI reaches the same rules through the API, so it can't bypass them.
5. **Errors are caught by a check suite, not a list.**
   - 17 reconcilers, detectors and independent recomputations run like a
     regression or eval suite.
   - Each finding carries evidence, its tax effect via the packet's
     `tax_effect_rates`, and whether the engine's own diagnostics caught it.
   - Mechanical findings carry a computed fix that becomes an adjustment.
6. **Change without losing history.**
   - Adjustments overlay the engine's values; the original is preserved.
   - You can compare any two states (v1/v2/v3, or saved workpaper states) with a
     reason per line.
   - What-ifs are labelled ENGINE (the packet's five scripted alternatives) or
     ESTIMATE (rate-based, with a disclaimer from the server).
7. **The lifecycle is data-driven and freezes at filing.**
   - A pre-file gate checks open notes, error findings, sign-offs and due
     diligence.
   - The 8879 is bound to a fingerprint of the presented figures: if the return
     changes, the signatures go stale.
   - The packet's real e-file reject comes up because the return's dependent TIN
     doesn't match the SSA card in the file.
   - On acceptance the filed snapshot freezes. A store-level policy refuses
     changes; amendments layer on top.
8. **Honest numbers.** The engine can't be rerun, so I never present a recompute I
   didn't do. Post-adjustment figures say how they were derived.

## Errors found, and how they surface

| Error | How it surfaces |
|---|---|
| **Broker 1099-B 71,965 vs lots 71,715** | The 250 is lot M18, on an unread page 32 of D31 (a missing 60 loss). The reverse trace shows the page; a reconciler quantifies it. |
| **RSU lots taxed at zero basis** | 47,620 of gain overstated; basis is in D11 and the comp is in W-2 box 14. A partner-gated fix. |
| **Estimated payments overstated** | Federal 1,000 and CA 3,500 against the IRS and FTB records. The engine missed both. |
| **SEK interest converted at the 2024 rate** | An FX detector. |
| **Schedule B interest counted twice** | 1,840 listed twice; a computed fix. |
| **Two misreads at high confidence** | A transposed childcare-provider EIN read at 0.97, and a handwritten donation read at 0.41. A text locator compares every read to the printed page. |
| **Superseded and duplicate documents** | D30 → D31 corrected; D10 is a second photo of D09, counted once. |
| **Basis problems** | S-corp distributions exceed basis by 21,215; Ridgeline outside basis isn't tracked; Coinhaven lot C6 has no basis. |
| **Client answers vs the documents** | "No" sales against 282 brokerage sales; "some crypto" against 12 disposals. |
| **Outside filings and due diligence** | 1099-NECs, FBAR, Form 8867. |
| **Theo's TIN typo from the organizer** | The cause of the R0000-504-02 reject. It's fixed *from the evidence* (D71) and resubmitted. |
| **Schedule C vs 1099-K** | The Letter 566 bridge raises a possible double count as a question to confirm. |

## How I used AI tools

I built it with Claude Code (an AI coding agent) in small, verified increments:
- I set the architecture, the rules and the quality bar, and checked each increment running before moving on.
- The agent wrote code and tests, and drove the app in a browser to check flows.
- The final regression (26 end-to-end checks plus 138 tests) ran from a fresh
  store on both the npm and Docker paths.

*There's no AI inside the product. Every number traces to the packet.*
