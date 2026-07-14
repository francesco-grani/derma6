# Idea sketch: product finder (retail + secondhand)

Status: exploratory, not scoped or approved. Lives on `explore/product-finder` until it's worth running through the spec workflow.

## What

A manually-triggered lookup: user clicks a button next to a product Derma6 has recommended, a panel opens showing a search-in-progress animation, then a mixed grid of real listings to buy — both retail (new) and secondhand — with price and a link out to the source.

## Trigger points (structured product data only — no free-text parsing)

Both existing sources already carry products as structured fields, not prose, so no new entity-extraction work is needed to know a button should appear:

1. **Routines page** — `step.product_name` / `step.budget_product` (`frontend/src/pages/RoutinesPage.tsx`). v1 target.
2. **Routine-diff proposal in chat (HITL-A)** — `InterruptCard.tsx`'s `PreviewRoutineStep { ingredient, suggested }` payload, shown before the user approves a proposed routine. Natural v1.5 extension since it's the same shape as (1), just pre-approval.

Explicitly deferred: buttons on freeform chat prose (the assistant just mentioning a product name mid-sentence). That has no structured tag today — would need the backend to annotate mentions in the stream, which is real new scope, not a UI change.

## Sources

- **Secondhand — Vinted**: no official API, but a stable-ish unofficial JSON endpoint (`/api/v2/catalog/items`) that wrappers like `pyVinted` already cover. Kleinanzeigen needs HTML scraping with no solid wrapper available — deferred past v1.
- **Retail**: rather than adding a new paid shopping API, reuse the web-search integration the RAG pipeline already has (`backend/rag/pipeline/nodes/fallback.py`, Tavily-preferred/DuckDuckGo-fallback, `TAVILY_API_KEY` already in `backend/config.py`). Scope the query to retailer domains. Caveat: a generic web search doesn't guarantee a structured price field the way a shopping API would — price extraction from snippets is best-effort (regex over the result text), and some retailers won't parse cleanly. If that proves too noisy, revisit with a proper (paid) shopping API later — not a v1 blocker either way since results degrade to "no price shown, link only."

Both lookups run in parallel per request; a listing missing a clean price still gets shown with a "view listing" link rather than being dropped.

## Flow: floating, anchored to the trigger — not a sidebar

Chose floating over a ChatGPT-style docked sidebar: it keeps the routine/chat context visible behind it and reads as a direct response to *that* button, not a navigation into a new screen. The tradeoff is it's more work to get right — an anchored popover only feels "cooler" than a sidebar if the positioning and motion are solid; done sloppily (wrong-edge overflow, no collision handling, jarring load-to-content swap) it reads worse than a plain sidebar would.

Implementation path: the frontend already has `@base-ui/react` as its headless primitive (see `dialog.tsx` wrapping `@base-ui/react/dialog`) but no Popover wrapper yet — Base UI ships a `Popover` primitive in the same family, so this is a new `frontend/src/components/ui/popover.tsx` following the existing wrapper pattern, not a new dependency. Base UI's Popover gives anchor positioning + collision/flip handling for free, which is the part that's easy to get wrong hand-rolling it.

1. Button ("Find this product") next to a routine step, or on the pre-approval diff card — this is the Popover anchor.
2. `ProductFinderPopover.tsx` opens anchored to that button: scale+fade in from the trigger (mirror the `data-[state=open]`/`duration-*` transition convention already used in `dialog.tsx`), no full-screen backdrop dim — it should feel light, not modal.
3. The *same* floating surface shows a searching animation first, then morphs into results in place (no separate loading modal that gets swapped for a different UI) while the backend runs the Vinted lookup and the scoped retail web search concurrently.
4. Results render as a mixed card grid inside the popover (existing `Card` + `Badge` from `frontend/src/components/ui`): each card tagged **New** or **Used**, plus price (if found), source/marketplace, thumbnail, "view listing" link-out. No in-app purchase — always opens the source site in a new tab.
5. Empty/partial results are a normal state, not an error — either source can silently return nothing.
6. Dismiss on outside click / Escape (Base UI Popover default). On small screens, cap the popover width and let Base UI's collision detection flip/shift it rather than letting it run off-screen — this is the detail that most determines whether it feels "cool" vs broken on mobile.

## Backend shape

- `backend/tools/product_finder.py` — not wired into the LangGraph agent (this is a lookup, not something needing conversational reasoning); exposed as its own route, e.g. `GET /api/products/find?name=...&brand=...`.
- Short-TTL cache per query (SQLite or in-memory) to avoid re-hitting Vinted/Tavily on repeat clicks.
- One attempt per source, no retry loop; failures log and return an empty list for that source.

## Explicitly out of scope for v1

- Kleinanzeigen support
- Free-text product-mention tagging in chat
- Price-drop alerts / background polling
- In-app checkout of any kind

## Future: city-level "superlocal" sourcing

Today onboarding collects only the user's **country**, and source discovery treats the
stored location as a country (`_DISCOVERY_SYSTEM_PROMPT` in
`backend/tools/product_source_discovery.py`). That's deliberate for v1 — country is enough
to pick the right retailer/marketplace domains and Vinted locale.

A later version could optionally capture the user's **city** on top of the country to give
*superlocal* results — nearby pickup-only secondhand listings, city-specific pharmacies/drugstores,
local delivery availability. This would mean:

- Onboarding: an optional follow-up after the country is confirmed ("Which city? — optional,
  for more local results"), stored separately so country stays the required field.
- A structured location (country + optional city) instead of the single free-text string, or a
  second `city` column, rather than overloading the one `location` field.
- Source discovery: pass the city through to the prompt/query when present, falling back to
  country-only when it's absent.

Not now — flagged here so the country-only decision is a conscious v1 scope choice, not a dead end.
