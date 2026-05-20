# German Property Agent (Wohnungskauf-Assistent)

## Overview

A step-by-step AI advisor guiding someone through buying an *Eigentumswohnung* (condominium flat) in Germany. The German buying process is noticeably different from the UK or US — the Notar is central, purchase costs are high and variable by *Bundesland*, and apartment-specific law (WEG) adds a layer most buyers don't understand. Targeted at first-time buyers and expats who find the process opaque and jargon-heavy. The agent acts as a persistent advisor across the full journey: from "I have a budget" to "I have the keys."

---

## RAG Knowledge Base

- **End-to-end buying process:** offer → Reservierungsvereinbarung → financing → Notartermin → Kaufvertrag → Auflassung → Grundbucheintrag
- **WEG (Wohnungseigentumsgesetz):** how apartment ownership works in Germany, what the *Teilungserklärung* says, owner meeting (*Eigentümerversammlung*) minutes and red flags, *Hausgeld* breakdown
- **Purchase cost breakdown by Bundesland:** *Grunderwerbsteuer* ranges (3.5% Bayern to 6.5% Berlin/NRW/Brandenburg), *Notarkosten* (~1–2%), *Maklerprovision* (3.57% each side since the 2020 reform)
- **German mortgage mechanics:** *Annuitätendarlehen*, *Zinsbindung* periods (5/10/15yr fixed), *Tilgung* rates, *Beleihungswert* vs. purchase price, why banks require 20%+ *Eigenkapital*
- **KfW and BAFA subsidies:** energy-efficient renovation loans, BEG programmes, *Bundesförderung für effiziente Gebäude*
- **Energy certificates (Energieausweis):** Bedarfs- vs. Verbrauchsausweis, energy classes, GEG compliance and *Heizungsgesetz* implications for older buildings
- **Legal due diligence:** *Grundbuchauszug* interpretation, *Baulastenverzeichnis*, *Altlasten* (soil contamination), *Erbbaurecht* (heritable building right — Germany's leasehold equivalent)
- **Instandhaltungsrücklage:** how to assess if a building is underfunded, typical contribution benchmarks
- **German property glossary:** full A–Z of terms buyers encounter

---

## Tool Calls

| Tool | Inputs | Outputs |
|---|---|---|
| **Grunderwerbsteuer calculator** | Purchase price, Bundesland | Exact transfer tax amount with full 16-state rate table |
| **Full Nebenkosten calculator** | Price, Bundesland, Makler involvement (yes/no) | Total purchase costs broken down: SDLT + Notar + Makler + misc |
| **Mortgage affordability calculator** | Net income, Eigenkapital, desired Zinsbindung | Maximum loan amount, monthly Annuität, flag if Eigenkapital < 20% |
| **KfW loan eligibility checker** | Property build year, planned renovation type | Relevant KfW programmes, current indicative interest rates |
| **Hausgeld analyser** | Hausgeldabrechnung figures entered by user | Reasonable vs. suspicious breakdown, flag on low Instandhaltungsrücklage |

---

## Technical Feasibility

### What makes it strong

The German buying process has unusually high and opaque upfront costs — a €400k flat in Berlin can easily require €55–60k in *Nebenkosten* alone before the bank will touch it. Most buyers don't know this until deep in the process. The WEG layer (owner meeting minutes, reserve funds, *Teilungserklärung*) is almost completely undocumented in English and poorly understood even by German buyers — rich territory for a focused knowledge base. RAG genuinely earns its place because the questions are cross-cutting: a user asking about their total budget touches mortgage rules, tax rates, AND notary costs simultaneously.

### How it would work technically

The agent maintains state across the conversation — "you told me your budget is €350k and you're a first-time buyer, here's your stamp duty saving" — acting as a persistent advisor rather than a one-shot Q&A tool. Tools run in real time. The UI (Streamlit) presents a step-by-step process tracker alongside the chat.

### Drawbacks

1. **Property search APIs are paid** — ImmobilienScout24 and Immowelt are commercial-only. No free tier exists for programmatic search.
2. **Legal liability** — if someone follows incorrect advice on a €400k purchase, that's a real problem. Strong disclaimers required.
3. **KfW data changes frequently** — interest rates and programme conditions update regularly. Static knowledge base will become stale.
4. **Regional complexity** — each of 16 Bundesländer has different Grunderwerbsteuer and some have local quirks. Easy to get wrong.
5. **Domain requires accuracy** — unlike coffee or wine, being wrong here has real financial consequences for the user.

### Workarounds

| Problem | Workaround |
|---|---|
| No property search API | Omit live search; replace with a postcode → average price/sqm lookup using static publicly available data |
| Legal liability | Prominent disclaimers; frame all advice as educational, always recommend consulting a Notar |
| Stale KfW data | Note data freshness date in the UI; structure KfW content as easily updatable documents |
| Regional complexity | Build a validated rate table for all 16 states; test each calculation |

### Verdict

Strong candidate for a school-to-product trajectory. The domain is genuinely underserved in the conversational AI space. Main school-project risk is the property search gap and the accuracy burden. Mitigated by replacing live search with a static dataset and adding clear disclaimers. If you're based in Germany or have bought property there, your domain knowledge is a significant asset.

---

## Competitors & Existing Tools

| Competitor | What it does | Useful for |
|---|---|---|
| **Hypofriend** (hypofriend.com) | German mortgage advisor, explains Nebenkosten, affordability calculator | Inspiration for calculator UX and German-specific cost breakdowns; shows the monetization model (lead gen to brokers) |
| **Interhyp** | Germany's biggest mortgage broker with extensive public Ratgeber content | Their buyer guide section is a goldmine for knowledge base content — all freely readable |
| **McMakler** | German estate agency with buyer guides, glossary, process explainers | Written content to adapt for the RAG knowledge base |
| **Immowelt Ratgeber** | Publicly available articles on every step of the German buying process, WEG law, Nebenkosten | Direct KB source — well-structured, freely readable, covers almost every topic you need |
| **Baufi24** | Online mortgage comparison and brokerage with educational content | Good reference for the mortgage mechanics layer of the knowledge base |

---

## Free Data & Content Boosts

- **Interhyp Ratgeber** — freely readable buying guides covering the full German process, well-structured
- **Immowelt Ratgeber** — extensive freely readable articles, good coverage of WEG and Nebenkosten
- **KfW public website** — all programme descriptions and current rates are publicly available (no API, but structured enough to adapt)
- **Bundesländer official tax authority websites** — authoritative Grunderwerbsteuer rates per state

---

## Differentiation

RAG genuinely earns its place here. A user asking "can I afford this flat?" retrieves from mortgage mechanics, Nebenkosten rules, AND Bundesland-specific tax rates simultaneously — multi-document retrieval is exactly what the question requires. No existing tool combines conversational guidance, real-time calculations, and WEG/legal context in one interface. Hypofriend does the mortgage part; Immowelt does the search part; nobody does the full journey end-to-end with an AI layer.

The gap is real, the user pain is real (expats especially), and the conversational format adds genuine value over reading static articles.

---

## Scoring

### School Project Score

| Criterion | Score /5 | Rationale |
|---|---|---|
| API simplicity | 2 | Property search APIs are commercial-only; workarounds needed |
| KB buildability | 3 | Good free sources exist but requires careful curation and accuracy checking |
| Demo wow factor | 3 | Functional and useful but not visually spectacular |
| Domain-agnostic | 2 | Requires understanding of German property law and process |
| 2-week achievability | 3 | Achievable if property search is replaced with static data |
| Uniqueness | 3 | Specific to Germany, but property chatbots exist in other markets |
| **School Total** | **16 / 30** | |

### Product Potential Score

| Criterion | Score /5 | Rationale |
|---|---|---|
| Market size | 4 | Millions of buyers in Germany annually; large expat market |
| Monetization clarity | 4 | Lead gen to mortgage brokers is a proven model (Hypofriend) |
| Long-term defensibility | 4 | RAG stays relevant as content grows; integrations deepen the moat |
| **Product Total** | **12 / 15** | |

### Combined Score: **28 / 45** — Rank 5 of 8
