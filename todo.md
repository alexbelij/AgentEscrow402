# Console UX overhaul — todo (from Alexey's 2026-07-04 message)

## Global (all console pages)
- [ ] explanation block must come AFTER the page title, not before, and must not duplicate the text under the title
- [ ] title row + text below it should span full width on one line (not ~50% as now)
- [ ] check font sizes, contrast ratio, keyboard navigation across console (accessibility pass) — item 12

## Navigation / layout
- [ ] Nav currently scrolls both vertically and horizontally — bug. Replace with classic dashboard left sidebar:
      collapsible to icon-only rail (icon + tooltip on hover), full mode = icon + label, no tooltip.
      Rethink page grouping — maybe merge some pages / add nesting (sub-menus).
- [ ] /console currently mixes real console sections, demo tools, and dev docs — separate/decompose into distinct
      groups/sections (we already discussed this decomposition).
- [ ] Content area is constrained/narrow while nav takes fixed width oddly — make everything use full width (item under nav point 1).
- [ ] Under sidebar, full-width "Hosted demo signer" block (point 1, 2nd list).

## Overview page (/console/overview)
- [ ] Total Volume — reduce font size
- [ ] Contract target — should link to explorer
- [ ] Other stats — link to explorer or relevant console section where applicable
- [ ] Missing useful metric widgets — overview should show full network/project state: nice animated
      charts/graphs, realtime logs/activity feed
- [ ] Unify block font sizes/styles (currently inconsistent & too large)

## Escrows (/console/escrows)
- [ ] confirm real data (not fake/demo passed as real)
- [ ] Rework modal — hash column wraps to 3 lines due to narrow width

## Agents (/console/agents)
- [ ] "Register agent" button should be to the right, after "Delegate..."
- [ ] Can we add real data alongside demo data?

## Contracts (/console/contracts)
- [ ] Reposition "Fresh escrow" (per Alexey — check exact placement issue)
- [ ] "Receiver" column — widen at the expense of "Amount (CSPR)" so full address fits

## Advanced Escrow (/console/advanced)
- [ ] Results currently render below the form — move to the right side; question excess empty space

## Arbitration (/console/arbitration)
- [ ] Results show both below and to the side — all results should render on the right only

## Agent Demo (/console/agent-demo)
- [ ] "Result" column — double width
- [ ] Steps: render in a single left column list (not 2-column like /sandbox)
- [ ] Completed step: green + animate move to end of list
- [ ] Next step: purple outline (design accent color), not red
- [ ] Reset: steps return to original style/position; "Current request & result" panel clears output

## Sandbox (/console/sandbox)
- [ ] Missing variable/type descriptions like proper API docs

## Demo signer / wallet connect UI
- [ ] "Demo signer" connect button doesn't switch to active/connected style — add style
- [ ] On connect: button text becomes demo wallet address (like real wallet-connect buttons do)
- [ ] Remove demo wallet address shown to the right of "Demo · not your key" badge; remove the badge
      entirely — button style itself communicates demo mode
- [ ] "Disconnect" + "Hosted demo signer" (with icon before label) shown only while demo wallet connected
- [ ] Add (i) info icon to the right of the label; move long explanatory text into a tooltip shown on
      click/tap; tooltip dismisses on click of (i) again or click-outside/tap-outside

## Process
- Work in blocks, report progress to Alexey per block (heavy scope — 1:1 DM, no other channels).
- Verify against CI-parity checks (frontend: tsc --noEmit + npm run build) before each report.
