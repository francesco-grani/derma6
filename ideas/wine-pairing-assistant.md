# Wine Pairing Assistant

## Overview

An educational wine pairing assistant that helps users understand *why* certain wines work with certain foods — not just what to buy. The core differentiator from existing tools like Vivino is the explanation layer: Vivino tells you what to choose; this tool tells you the principles behind the choice and builds wine literacy over time. Works in both directions: food-to-wine ("I'm making pasta carbonara, what wine?") and wine-to-food ("I have an open bottle of Barolo, what should I cook?"). Targeted at curious wine drinkers who want to move beyond guessing and develop their own palate.

---

## RAG Knowledge Base

- **Food pairing principles:** the core rules — weight matching, acid cuts richness, tannins vs. fat, regional pairing logic ("what grows together goes together"), sweetness in wine vs. sweetness in food
- **Grape variety profiles:** Cabernet Sauvignon, Pinot Noir, Chardonnay, Riesling, Sangiovese, Nebbiolo, Tempranillo, Grenache, Syrah, Sauvignon Blanc — flavour profile, body, acidity, tannin level, classic pairings for each
- **Region guides:** Bordeaux, Burgundy, Tuscany, Rioja, Mosel, Barossa Valley, Marlborough, Piedmont — what they produce and the regional food traditions that shaped the pairings
- **Wine style taxonomy:** still/sparkling/fortified/orange, old world/new world, natural wine basics, how to read a label
- **Common pairing mistakes:** what not to pair (high tannin with fish, very sweet wine with savoury food, high-alcohol wine with spicy food) and why each fails
- **Price tier reference:** rough quality and style expectations by price bracket, without specific brand recommendations

---

## Tool Calls

| Tool | Inputs | Outputs |
|---|---|---|
| **Food-to-wine matcher** | Dish description or cuisine type | Ranked wine style recommendations (e.g. "dry Riesling from Alsace") with explanation of why each works |
| **Wine-to-food matcher** | Wine style or grape variety | Food pairing suggestions with explanation of the matching principle |
| **Flavour profile lookup** | Grape variety or region | Full tasting note profile: body, acidity, tannin, alcohol, typical aromas, classic serving temperature |
| **Pairing conflict checker** | Food + wine combination | Safe / works / avoid — with explanation of what clashes and why |
| **Occasion suggester** | Context (dinner party / picnic / gift / celebration / date night) | Wine style + price tier recommendation with explanation |

---

## Technical Feasibility

### What makes it strong

Wine pairing has a well-established body of knowledge with clear rules that translate directly into RAG content. The tool works elegantly in both directions (food→wine, wine→food). No external APIs needed at all — the knowledge base is the entire product. The educational angle is genuinely different from Vivino, which focuses on discovery and purchasing. RAG earns its place because pairing questions frequently require combining grape variety profiles, regional context, and pairing principles from multiple documents simultaneously.

### How it would work technically

The agent opens with a light preference calibration ("do you tend to prefer red or white, dry or sweet, old world or new world?") stored in session state. All tool calls query the knowledge base to generate principled recommendations. The UI can show the "pairing principle" used for each recommendation as a citation, satisfying the requirements' source citation optional task naturally.

### Drawbacks

1. **No live pricing or availability** — the agent can recommend "a medium-bodied Burgundy-style Pinot Noir around €20" but can't tell the user if that exists locally or what it costs. No free product database exists (Vivino has no public API; Wine-Searcher is paid).
2. **Regional wine law is a rabbit hole** — appellations (Chianti Classico DOCG, Premier Cru vs. Grand Cru in Burgundy, Rioja classifications) can consume weeks. Needs deliberate scope limiting.
3. **Personal taste overrides rules** — someone who hates tannins should never drink Barolo regardless of pairing rules. The agent gives technically correct advice that may be wrong for a specific palate.
4. **Tone risk** — wine has a reputation for gatekeeping and snobbery. If the agent's language is too formal or technical, users disengage.
5. **Natural wine is contested** — natural, biodynamic, and orange wine are popular but the science is debated. Either engage carefully or explicitly scope them out.

### Workarounds

| Problem | Workaround |
|---|---|
| No product database | Recommend wine styles and characteristics, not specific bottles or brands |
| Appellation depth | Include one overview per major region; go deep on only 4–5 key regions |
| Personal taste | Add "I don't like X" as a session filter (e.g. "avoid high tannin") |
| Snobbery perception | Write all prompts with explicit "friendly sommelier, not gatekeeper" persona instruction |
| Natural wine | Add a short KB section flagged as "evolving area — evidence is mixed" |

### Verdict

Very achievable, genuinely useful, no API dependencies. The tools work elegantly in both directions. The main risk is scope creep into regional wine law — avoidable with deliberate KB scoping. The educational angle is a real differentiation from Vivino (which dominates the "what to buy" space but doesn't explain why). Strong choice for school with real product legs in the "wine education" category. The market is large enough that even a niche of it is commercially interesting.

---

## Competitors & Existing Tools

| Competitor | What it does | Useful for |
|---|---|---|
| **Wine Folly** (winefolly.com) | Visual wine education, pairing guides, grape variety profiles | Best free KB source — their grape variety and region pages are almost perfectly structured for RAG documents |
| **Vivino** | Wine discovery, user reviews, pairing suggestions, purchase links | Direct competitor for the pairing feature — shows what the UX expectation is; your differentiation is the "why" |
| **Hello Vino** | Simple food-to-wine pairing app | Closest to what you'd build — study their pairing logic as a benchmark; your tool adds the explanation layer |
| **CellarTracker** | Wine database with community tasting notes, food pairing tags, vintage ratings | Large freely browsable wine database — useful for building grape variety flavour profiles |
| **Decanter** (decanter.com) | Editorial wine recommendations, region guides, food pairing articles | High-quality freely readable articles; good source for region guides and pairing principles in the KB |

---

## Free Data & Content Boosts

- **Wine Folly website** — grape variety profiles, region guides, and pairing rules. Almost perfectly structured for RAG knowledge base documents. Best single source for this idea.
- **Decanter.com** — freely readable region guides and food pairing articles; high editorial quality.
- **CellarTracker** — browsable tasting notes and vintage data; useful for flavour profile calibration.
- **Wine Scholar Guild** — publishes some free educational content on major wine regions.

---

## Differentiation

RAG earns its place here. A user asking "what wine goes with my mushroom risotto?" requires retrieving umami pairing rules, the weight-matching principle, and specific grape varieties that work with earthy flavours — multi-document retrieval working as intended. The educational layer (explaining *why* a pairing works) is the genuine gap: Vivino is a discovery and purchase tool, not a learning tool. The agent's explanations build wine literacy over time in a way no existing app does. Long-term, this positions the product in the wine education category rather than the wine recommendation category — a less crowded and more defensible space.

---

## Scoring

### School Project Score

| Criterion | Score /5 | Rationale |
|---|---|---|
| API simplicity | 5 | No external API needed |
| KB buildability | 3 | Good sources exist; requires curation but not expert knowledge |
| Demo wow factor | 3 | Functional and useful; not visually spectacular |
| Domain-agnostic | 3 | Basic wine familiarity enough; no deep expertise required |
| 2-week achievability | 5 | Very achievable; well-defined scope |
| Uniqueness | 2 | Wine pairing apps exist; educational angle is incremental not revolutionary |
| **School Total** | **21 / 30** | |

### Product Potential Score

| Criterion | Score /5 | Rationale |
|---|---|---|
| Market size | 4 | Large — global wine market; educated consumers willing to pay |
| Monetization clarity | 4 | Wine retailer affiliate, subscription for advanced features, sommelier tool licensing |
| Long-term defensibility | 3 | Educational angle is defensible; Vivino could add explanations but hasn't |
| **Product Total** | **11 / 15** | |

### Combined Score: **32 / 45** — Rank 2 of 8
