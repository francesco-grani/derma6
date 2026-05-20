# Coffee Brewing Guide

## Overview

A conversational brewing assistant for home coffee enthusiasts. Covers every major brewing method (V60, Aeropress, French Press, Moka Pot, espresso, cold brew) and helps users diagnose extraction problems, find the right recipe for their beans and equipment, and understand the science behind why variables matter. The troubleshooting flow is the core differentiator: rather than giving a fixed recipe, the agent asks about the symptom (too sour, too bitter, too weak) and walks the user through an extraction diagnosis. Targeted at the growing home barista community who want to understand their coffee rather than just follow a recipe app.

---

## RAG Knowledge Base

- **Brewing method guides:** V60, Aeropress, French Press, Moka Pot, espresso, cold brew, Chemex — each with full parameters, technique breakdowns, and common variations
- **Bean origin profiles:** Ethiopia, Colombia, Kenya, Brazil, Guatemala, Yemen, Indonesia — flavour notes, recommended roast levels, best brewing methods per origin
- **Roast level guide:** light/medium/dark and how they affect solubility, recommended grind size, extraction behaviour, target ratios
- **Water chemistry basics:** TDS, hardness, and why it matters for extraction; ideal water profiles for coffee
- **Extraction science:** the coffee compass (sour = underextracted, bitter = overextracted), how grind size, temperature, time, and ratio interact
- **Troubleshooting decision tree:** full symptom → cause → fix mapping for every common brewing problem
- **Barista glossary:** bloom, bypass, channelling, puck prep, preinfusion, EY (extraction yield), TDS

---

## Tool Calls

| Tool | Inputs | Outputs |
|---|---|---|
| **Brew ratio calculator** | Coffee weight, ratio (e.g. 1:15), or target cup size | Water weight needed; or reverse: coffee weight for a given cup size |
| **Grind size advisor** | Brewing method, bean roast level | Recommended grind range (coarse / medium-coarse / medium / fine / extra-fine) with rationale |
| **Extraction time advisor** | Brewing method, grind size, dose | Target time range for that combination |
| **Water temperature guide** | Roast level | Recommended brewing temperature (lighter = hotter, typically 92–96°C; darker = cooler, 88–92°C) |
| **Flavour troubleshooter** | Symptom description (too sour / bitter / weak / strong / flat) | Diagnosis (likely cause) + one specific adjustment to try first |

---

## Technical Feasibility

### What makes it strong

Zero external API dependency. Tools are pure math or simple logic. The domain is narrow enough to build a complete knowledge base in a few days. The troubleshooting flow genuinely benefits from RAG — diagnosing "my V60 tastes sour" requires retrieving extraction theory, the specific method's variables, and the symptom-cause mapping simultaneously. Well-documented, freely available source material from Barista Hustle, James Hoffmann, and Coffee ad Astra.

### How it would work technically

The agent opens with a brief onboarding: what brewing method do you use, what grinder do you have? This context is stored in session state and used to pre-filter recommendations. The troubleshooter is the primary flow: user describes a symptom, the tool fetches a diagnosis, the RAG layer provides the theory, the agent explains the fix conversationally.

### Drawbacks

1. **The domain is subjective** — coffee taste is personal. The agent gives calibrated advice based on general principles but users may push back because their favourite YouTuber said something different. Hard to be authoritative.
2. **Espresso is a rabbit hole** — if you include espresso, complexity multiplies enormously (pressure profiling, puck prep, machine variables, portafilter baskets, pre-infusion). Either exclude it or cap scope at "espresso basics."
3. **RAG may be underused** — most brewing questions are answered by a single recipe lookup. The RAG adds most value in the troubleshooting and "why does this work" explanations — that's where retrieval genuinely helps.
4. **No personalisation without memory** — the agent can't learn your specific grinder, local water, or machine. It gives general advice that a seasoned home barista may find too basic.
5. **Crowded space** — many brew timer apps and YouTube channels already solve this. Hard to justify as a portfolio piece without the troubleshooting layer being genuinely good.

### Workarounds

| Problem | Workaround |
|---|---|
| Subjectivity | Frame all advice as "a good starting point" — always invite user to adjust and report back |
| Espresso complexity | Explicitly scope it out or cap at 3 espresso-specific parameters |
| Low RAG utility | Make the troubleshooting decision tree the core of the KB — that's where retrieval genuinely earns its place |
| No personalisation | Add onboarding questions (brewing method, grinder type) and store in session state |

### Verdict

Highly achievable, zero API dependency, pleasant to demo. The risk is that it feels thin as a portfolio piece — the domain is narrow and the tools are simple. Mitigated by making the troubleshooting flow genuinely deep and including the "science behind it" explanations in the RAG layer. Works best if you're a coffee person yourself. Long-term product potential is limited — the space is crowded and the RAG advantage over a well-made brew timer app is modest.

---

## Competitors & Existing Tools

| Competitor | What it does | Useful for |
|---|---|---|
| **Barista Hustle** (baristahustle.com) | Professional coffee education, extraction science, brewing guides | Their free articles are exceptionally well-written — primary KB source material, especially for extraction theory |
| **James Hoffmann** (YouTube + blog) | Covers every brewing method in depth, highly authoritative | Most trusted voice in home coffee — your RAG KB should align with his recommendations where possible |
| **Brew by Ratio / Acaia app** | Recipe calculators, ratio timers, step-by-step brew guides | Shows what the calculator/timer UX looks like; your Streamlit tools replicate this in chat form |
| **Coffee ad Astra** (blog, Jonathan Gagné) | Science-heavy coffee extraction analysis, physics of brewing | Good source for the "why does this work" layer — explains extraction mechanics clearly and rigorously |
| **Fellow's Stagg app** | Smart kettle companion with recipe guides and temperature control | Shows how dedicated hardware companies approach the same problem — useful UX reference |

---

## Free Data & Content Boosts

- **Barista Hustle** — freely readable brewing method guides and extraction theory articles. Best primary KB source.
- **James Hoffmann's blog** — public articles on specific brewing methods with precise parameters.
- **Coffee ad Astra** — detailed extraction science articles, freely readable.
- **SCA (Specialty Coffee Association)** — publishes the Coffee Taster's Flavor Wheel and extraction guidelines; freely downloadable.

---

## Differentiation

RAG adds value specifically in the troubleshooting layer: "my V60 tastes sour and I've already tried a finer grind" requires retrieving extraction theory + V60-specific variables + the adjustment hierarchy. A static FAQ can't handle this combination. However, most simple brewing questions (recipe, ratio, temperature) are answered by a single document lookup — RAG is overkill for these. The tool is strongest when the agent is used as a diagnostic partner, not a recipe lookup. The long-term product gap is modest because the existing ecosystem (apps + YouTube) already solves most of what users need.

---

## Scoring

### School Project Score

| Criterion | Score /5 | Rationale |
|---|---|---|
| API simplicity | 5 | No external API needed |
| KB buildability | 5 | Well-documented domain, excellent free sources |
| Demo wow factor | 3 | Functional and useful; not visually spectacular |
| Domain-agnostic | 3 | Basic coffee familiarity is enough |
| 2-week achievability | 5 | Very fast to build; scope is well-defined |
| Uniqueness | 2 | Many brew apps exist; conversational angle is incremental |
| **School Total** | **23 / 30** | |

### Product Potential Score

| Criterion | Score /5 | Rationale |
|---|---|---|
| Market size | 3 | Specialty coffee growing market; millions of home baristas |
| Monetization clarity | 3 | Equipment affiliate (high-ticket items like grinders); coffee subscription |
| Long-term defensibility | 1 | RAG advantage over a good static app is modest; YouTube is hard to beat |
| **Product Total** | **7 / 15** | |

### Combined Score: **30 / 45** — Rank 3 of 8
