# Historical Event Explorer

## Overview

An AI-powered history tool that answers cross-cutting historical questions — particularly the kind that require connecting events across geographies and time periods simultaneously. The standout feature is the "simultaneity mapper": given any historical event, it surfaces what was happening in other parts of the world at the same moment. "What was happening in Mali when the Black Death spread through Europe?" is exactly the kind of question that RAG handles better than Wikipedia (which requires opening multiple tabs). Targeted at history enthusiasts, students, and educators who want to explore connections and causality rather than just look up isolated facts.

---

## RAG Knowledge Base

- **Event documents:** one document per major historical event — cause, key figures, timeline, consequences, contemporary context (each with structured metadata: start_year, end_year, region)
- **Period overviews:** Ancient, Classical, Medieval, Early Modern, Industrial Revolution, 20th Century — each as a high-level document with defining characteristics
- **Region documents:** what was happening in East Asia, Sub-Saharan Africa, the Americas, Europe, the Middle East, South Asia during key periods — essential for answering simultaneity queries
- **Biographical profiles:** key historical figures with dates, roles, locations, and cross-references to events
- **Historiographical notes:** where historians disagree, how interpretations have changed, what evidence is contested
- **Causality chains:** documented cause-and-effect relationships between events (e.g. how WWI led to WWII, how the printing press connected to the Reformation)

---

## Tool Calls

| Tool | Inputs | Outputs |
|---|---|---|
| **Timeline builder** | Start year, end year, optional region filter | All events from the knowledge base in that range, sorted chronologically |
| **Simultaneity mapper** | Event name or year | What was happening in other regions of the world at the same time — the core novel tool |
| **Date calculator** | Two events or dates | Time elapsed between them, what century each falls in, how many generations apart |
| **Figure lookup** | Historical person name | Active period, location, associated events, brief biographical summary |
| **Era classifier** | Year | Historical period name, its defining characteristics, major powers of the time |

---

## Technical Feasibility

### What makes it strong

The simultaneity mapper is a genuinely clever tool that demonstrates RAG's value better than most other ideas. The query "what else was happening in 1347?" requires retrieving from multiple geographic region documents simultaneously — exactly the multi-document retrieval problem RAG is designed for. The World History Encyclopedia's free API provides structured, peer-reviewed historical content that can be ingested directly. The causality and simultaneity angles are intellectually fresh — Wikipedia doesn't do this.

### How it would work technically

The knowledge base uses structured metadata (start_year, end_year, region) in every document. The simultaneity tool queries the vector store filtered by date range, then filters by region to exclude the query's own geography. The timeline builder sorts results chronologically. The UI can render results as an actual visual timeline (Streamlit's st.timeline or a custom component), which makes the demo visually distinctive.

### Drawbacks

1. **Knowledge base construction is the whole project** — unlike coffee or wine, there's no single well-structured source to adapt. Building a knowledge base wide enough to be interesting AND deep enough to be useful is the main time investment.
2. **Geographic and cultural bias** — English-language sources over-represent European history. Questions about 14th-century Mali or Song Dynasty China will get worse answers than those about medieval France.
3. **Simultaneity requires good metadata** — for the tool to work, every document needs reliable date metadata from the start. This can't be retrofitted easily.
4. **Contested history is politically sensitive** — colonialism, the Crusades, 20th-century conflicts have genuinely different interpretations depending on perspective. The agent needs to handle disagreement without taking sides.
5. **Factual accuracy has higher stakes** — historical facts sound authoritative. If the RAG retrieves incorrect information, users may not catch it. More care needed than coffee or wine.
6. **EdTech sales cycle is slow** — if this goes product, selling to schools is a long, painful process.

### Workarounds

| Problem | Workaround |
|---|---|
| KB construction burden | Constrain to one era or region — e.g. "20th century Europe" or "Ancient Mediterranean" — depth beats breadth |
| Geographic bias | Name the scope explicitly in the UI so users know what's covered |
| Simultaneity metadata | Use YAML front-matter in every KB document: start_year, end_year, region — parse this for the tool |
| Contested history | Present multiple interpretations where they exist; add a standard "historians disagree on this" disclaimer |
| Accuracy risk | Include source citations (World History Encyclopedia article names) in every RAG response |

### Verdict

Intellectually interesting but the knowledge base construction is the bottleneck. The simultaneity mapper is genuinely novel and demonstrates RAG's value clearly to an evaluator. The fix for the scope problem is simple: pick one era, one region, go deep. "Ancient Mediterranean civilisations" or "20th century Europe" as a bounded scope makes this very achievable. The World History Encyclopedia API is the strongest single data boost of any idea in this list. Product potential is real but the EdTech sales cycle is slow and consumer monetization is hard against free Wikipedia.

---

## Competitors & Existing Tools

| Competitor | What it does | Useful for |
|---|---|---|
| **World History Encyclopedia** (worldhistory.org) | Peer-reviewed historical articles, free and openly licensed | Direct data boost — free API returns structured historical articles; primary KB source for this idea |
| **Histography** (histography.io) | Interactive timeline of historical events pulled from Wikipedia | Shows what a good historical timeline UI looks like; reference for the timeline builder tool output |
| **ChronoZoom** | Big history timeline, interactive and zoomable across cosmic to human scales | Demonstrates the "simultaneity" concept visually — good UX reference for the simultaneity mapper |
| **Khan Academy History** | Free structured history curriculum organised by period and region | Good for understanding how to scope and sequence historical periods; reference for KB organisation |
| **Britannica** | Comprehensive encyclopaedia with historical articles | Shows the depth expectation for historical content; your tool differentiates on the connection/causality layer |

---

## Free Data & Content Boosts

- **World History Encyclopedia API** — free for non-commercial/educational use. Returns structured, peer-reviewed articles. The strongest single data boost of all eight ideas. Direct pipeline into your RAG KB.
- **Wikipedia API** — freely available for bulk content retrieval; lower editorial quality than World History Encyclopedia but vastly broader coverage.
- **Project Gutenberg** — primary historical sources (texts from before 1928) freely available; good for adding depth to key period documents.

---

## Differentiation

RAG genuinely earns its place here — more than almost any other idea. The simultaneity mapper and causality explorer require retrieving from multiple geographically diverse documents simultaneously, which is exactly what vector similarity search is built for. Wikipedia handles individual events well but fails at cross-cutting queries. The "what was happening simultaneously in three different continents" query is a real gap. Constrained to a well-chosen scope, this is a genuinely interesting project. The risk is building too broad a KB and having it shallow everywhere.

---

## Scoring

### School Project Score

| Criterion | Score /5 | Rationale |
|---|---|---|
| API simplicity | 5 | World History Encyclopedia API is free; no OAuth required |
| KB buildability | 1 | Manual curation required; must be carefully scoped or becomes unmanageable |
| Demo wow factor | 3 | Simultaneity mapper is clever but not visually spectacular without a good UI |
| Domain-agnostic | 3 | Basic historical knowledge enough if scope is well-chosen |
| 2-week achievability | 3 | Achievable only if scope is aggressively constrained from day one |
| Uniqueness | 3 | Simultaneity angle is novel; general history chatbots are common |
| **School Total** | **18 / 30** | |

### Product Potential Score

| Criterion | Score /5 | Rationale |
|---|---|---|
| Market size | 3 | Students, educators, enthusiasts — broad but diffuse |
| Monetization clarity | 2 | EdTech subscription possible but slow sales cycle; consumer version hard against Wikipedia |
| Long-term defensibility | 3 | Simultaneity and causality tools are genuinely novel and hard to replicate with a static DB |
| **Product Total** | **8 / 15** | |

### Combined Score: **26 / 45** — Rank 6 of 8
