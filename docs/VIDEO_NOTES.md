# Video walkthrough: about 4 minutes

## Setup

1. Start from a fresh store: `docker compose down -v`, then
   `HOST_PORT=8080 docker compose up --build`.
2. Open http://localhost:8080.
3. Use the role switcher (top right) to change roles. Start as **Priya Raman
   (preparer)**.
4. Keep the browser at about 1440px wide, so the trace drawer docks beside the
   page.

## 0:00 — The "wow": a number back to its source (60 s)

1. **Return → click `F1040.1a` (wages, 212,400).** The trace drawer opens.
   > "Every number answers 'where did this come from'."
2. **Click the D08 source chip.** The W-2 opens on the right page with Box 1
   highlighted.
   > "The exact field on the exact page, using the `{document, page, position}`
   > contract a real PDF can drop into."
3. **Back in the drawer, open the calc tree,** up to AGI and total tax.
   > "And what was done to it, down and up the graph."
4. **Documents → D10.** It shows "Duplicate of D09 — counted once".
   > "Documents trace the other way too: where each one landed."

## 0:60 — A reconciler catches a planted error (45 s)

1. **Checks & findings → "Meridian Brokerage: 250.00 of sales missing".**
   > "The broker summary is 71,965 but the lots add to 71,715. The check found
   > the 250: lot M18 on page 32 of the corrected 1099, which was never read."
2. Point at the **tax effect** and the **"engine agrees / engine missed"** badge.
3. **Open "3 lots taxed at zero basis".**
   > "47,620 of gain overstated. The basis is in D11. The check computes the fix."

## 1:45 — Rules the server enforces (45 s)

1. On the RSU finding, click **Propose adjustment**. It goes to *awaiting partner
   sign-off*, and the top bar shows a filing blocker.
2. Switch to **Daniel (reviewer)** → Adjustments → **Approve**.
   > "Refused by the server: over $1,000 needs a partner."
3. Switch to **Helen (partner)** → Approve with a note. The Return page shows the
   engine value struck through next to the adjusted value.
4. *(Optional, 10 s)* Switch to **Marcus**. SSNs are masked, and the view is
   logged in Activity.

## 2:30 — Filing, the real reject, the freeze (60 s)

1. **Status.**
   > "One glance: the stage, what blocks the next step, who owns it."
2. Click **Filing**. The pre-file gate lists what's open. Clear it fast in the
   background beforehand:
   - accept the remaining errors (bulk select on Findings);
   - complete the Form 8867 boxes;
   - as Daniel, then Helen, use **Sign off on the return** in the gate (or the gate row's
     *Sign off* link, which opens the control on Review) — reviewer first, then partner.
3. Present the return. Switch to **Ngozi (client)**, tick the box and enter a
   PIN, then do the same as **Erik**. Back to **Helen** → **Sign as ERO**.
4. As **Daniel**, click **Transmit**: **R0000-504-02, dependent 2 TIN mismatch.**
   > "That's the packet's real reject. The return carries Theo's SSN from the
   > organizer, which doesn't match his Social Security card in the file."
5. As **Priya**, click **Correct Theo's TIN from D71**. Then as **Daniel**,
   **Resubmit**: accepted, and the **Filed · frozen** chip appears.
   > "The filed return is now immutable."

## 3:30 — After filing (30 s)

1. **Amendments → open one → "from finding": the duplicate interest line.**
   > "As filed, net change, correct, and why. The filed snapshot hash is
   > unchanged."
2. **Notices → Letter 566 → Assemble.**
   > "A self-contained record: the lines as filed, every source with document
   > and page, the verifications, the gaps, and a Schedule C bridge that ties to
   > 163,700."

## 4:00 — Close (10 s)

Show **Ctrl+K**, type "theo", then press Enter on the person result.

> "Search reaches everything. Everything is an event, rules live on the server,
> and every number traces to the packet."

## If time is short

Keep 0:00 (the trace), 1:00 (M18) and the reject → fix → frozen beat. Everything
else is optional.
