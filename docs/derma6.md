# Derma6

## Overview

A conversational skincare assistant that helps users build, diagnose, and optimise their skincare routine. The core differentiator from existing tools like Skincarisma (which uses static forms) is the conversational diagnostic flow: "my skin has been breaking out since I added a new product — what's causing it?" requires multi-document retrieval across ingredient profiles, conflict rules, and skin type guides simultaneously. Targeted at the large, research-oriented skincare community (Reddit's r/SkincareAddiction, TikTok skincare enthusiasts) who want to understand their routine rather than just buy products.

---

## Positioning Decision: Beginner-First, Men as Primary User

**Decision:** The tool is designed with male beginners as the primary user persona — not gender-locked, but all tone, onboarding, routine complexity, and knowledge base framing are calibrated for someone who is new to skincare and male.

**Why this creates differentiation:** Skincarisma, INCI Decoder, and Paula's Choice are all implicitly female-coded in tone, concern framing, and product examples. A tool that opens with "do you shave your face?" and talks about razor burn, post-shave barrier repair, and ingrown hairs is a genuinely different product.

**Why not gender-locked:** Positioning as "beginner-first" is more defensible in a portfolio context and leaves room to grow. The underlying ingredient science and tool logic are the same for any user — the specialisation is in concerns, tone, and routine framing.

### What this changes in the knowledge base

- **Add men-specific concern documents:** razor burn, post-shave skin barrier repair, ingrown hairs, how shaving frequency affects skin hydration
- **Add men's physiology basics:** thicker dermis, higher sebum production (oilier skin on average), how daily shaving mechanically exfoliates and disrupts the barrier
- **Add a "beginner's starting point" document:** minimal 3-step routine (cleanser → moisturiser → SPF) as the default entry point — add steps only when justified
- **Keep all generic ingredient profiles:** retinol, niacinamide, AHAs, BHAs etc. — the chemistry is identical, only concern framing and examples change
- **Additional men-specific sources:** r/malegrooming wiki, Geologie blog, Tiege Hanley educational content — in addition to Paula's Choice and INCI Decoder

### What this changes in tone and UI

- System prompt persona: "friendly, direct, no jargon" — explicitly not clinical, not lad-magazine
- Onboarding branching: "do you shave your face?" triggers the shaving-specific knowledge path
- Routine complexity: always start with 3 steps, gate complexity behind explicit user request
- SPF recommender: add "lightweight/invisible finish" as a default filter (common male preference and barrier to SPF adoption)

### Scope boundary

- **In scope:** post-shave routine, razor burn treatment, how to sequence actives around shaving, ingrown hair prevention
- **Out of scope:** beard care products in depth — that is a separate domain and would double the KB scope
- Shaving layer capped at **2–3 focused documents** to avoid scope creep within the two-week build

---

## RAG Knowledge Base

- **Ingredient profiles:** retinol, niacinamide, vitamin C (L-ascorbic acid), AHAs (glycolic acid, lactic acid), BHAs (salicylic acid), hyaluronic acid, peptides, ceramides, benzoyl peroxide, SPF actives, azelaic acid — for each: mechanism, skin types suited, frequency of use, pH requirements, conflicts
- **Conflict rules:** canonical do-not-mix pairs and their rationale — retinol + AHAs/BHAs (sensitivity), benzoyl peroxide + retinol (degradation), direct vitamin C + niacinamide (contested — flag as such), high-pH toner before low-pH vitamin C
- **Skin type guide:** oily, dry, combination, sensitive, acneic, dehydrated — how each responds to different actives, common mistakes per skin type
- **Routine sequencing rules:** canonical application order (cleanser → toner → serum → moisturiser → SPF), the logic behind it (thinnest to thickest, pH considerations, wait times between actives)
- **Common mistakes guide:** over-exfoliation signs and consequences, skipping SPF, introducing too many actives simultaneously, not patch testing
- **Introduction schedule framework:** how to safely add new actives — one at a time, patch test protocol, 2-week assessment periods
- **Skin concern guides:** acne, hyperpigmentation, fine lines, redness, dehydration — which ingredients address each concern and in what order to prioritise

---

## Tool Calls

| Tool | Inputs | Outputs |
|---|---|---|
| **Ingredient conflict checker** | Two ingredient names | Safe / use at different times of day / do not use together — with mechanism explanation |
| **Routine sequencer** | List of products/ingredients the user currently uses | Correct application order with reasoning for each step |
| **Skin type advisor** | Symptom description (tight after washing / shiny by midday / flaky / reactive / etc.) | Skin type classification with confidence level and recommended next steps |
| **Introduction scheduler** | List of new actives the user wants to add | 6–8 week plan: what to add when, how long to assess each, patch test instructions |
| **SPF recommender** | Skin type, primary skin concern, texture preference (fluid / cream / invisible) | SPF formulation type recommendation with key ingredients to look for |

---

## Evaluation

RAGAs evaluation is run against a 15-question golden dataset (`eval/eval_dataset.json`). Two evaluation modes are supported:

### Agent mode (default)

Calls `BackendService` end-to-end. The agent decides whether to invoke `kb_search` for each question. Measures overall system quality but may skip retrieval for questions the LLM already knows from training data — the agent then answers from parametric knowledge, which is intentional behaviour (see ADR-0003).

```bash
uv run python scripts/eval_rag.py
```

### Retriever mode

Bypasses the agent entirely. For each question the retriever is called directly and the LLM is constrained to answer using only the retrieved chunks. This is a clean measure of RAG pipeline quality independent of agent tool-calling behaviour — it forces retrieval on every question and surfaces true precision/recall gaps.

```bash
uv run python scripts/eval_rag.py --retriever
```

### Results

| Metric | Agent mode | Retriever mode |
| --- | --- | --- |
| Faithfulness | 0.88 | 0.86 |
| Answer relevancy | 0.81 | 0.71 |
| Context precision | 1.00 | 0.86 |
| Context recall | 0.98 | 0.69 |

**Reading the results:**

- Agent mode scores higher on answer relevancy because the LLM supplements retrieval gaps with training knowledge, producing more complete answers.
- Retriever mode exposes the true pipeline: context precision 0.86 and recall 0.69 indicate that 2 of 15 questions (AHA/BHA comparison and razor bumps) fell below the minimum score threshold (0.30) and received no retrieved context. These are candidates for KB expansion or threshold tuning.
- Faithfulness is consistently high (0.86–0.88) across both modes, confirming answers stay grounded in source material regardless of how retrieval is invoked.

Results are saved to `data/eval_results_agent.json` and `data/eval_results_retriever.json`.

---

## Technical Feasibility

### What makes it strong

The conflict checker and introduction scheduler are the strongest tools of any idea in this list — both are genuinely useful and non-trivially answered by a Google search. RAG earns its place because the conflict checker requires retrieving information about two or more ingredients simultaneously and reasoning about their interaction — a true multi-document retrieval problem. The knowledge base is manageable if focused on the top 15–20 actives. The skincare community produces an enormous volume of real user questions (Reddit, INCI Decoder comments) that can directly inform knowledge base priorities.

### How it would work technically

The agent opens with a skin type assessment (either the advisor tool or a simple questionnaire). The user's skin type and current routine are stored in session state. All subsequent recommendations are filtered through this context. The conflict checker operates as a standalone tool callable mid-conversation. The sequencer takes the user's current product list and returns an ordered routine. The introduction scheduler generates a timestamped plan the user can follow.

### Drawbacks

1. **The science is contested in places** — the vitamin C + niacinamide conflict was debated for years and is now largely debunked, but authoritative-sounding sources still say both things. The knowledge base must acknowledge uncertainty rather than pick a side incorrectly.
2. **Skin is individual and medical** — someone with rosacea, eczema, or active acne needs different advice. If the agent gives confident advice that worsens a skin condition, that's a real harm. Strong disclaimers required.
3. **No product-level recommendations** — without a product database (none are free and comprehensive), the agent recommends at the ingredient/formulation level, not specific products. This is actually more educational but users often want specific product names.
4. **Conflict checker needs structured KB design** — a prose document about retinol won't reliably surface the conflict with AHAs when the user asks about glycolic acid. Conflicts need to be stored as a structured lookup table, not just prose.
5. **SPF varies by region** — recommendations differ between European, American, and Asian dermatology standards. Must pick one standard and state it clearly.

### Workarounds

| Problem | Workaround |
|---|---|
| Contested science | Flag contested claims explicitly: "evidence is mixed on this — most dermatologists now consider it safe, but some users report issues" |
| Medical edge cases | Add skin condition filter at the start — if user flags eczema/rosacea/etc., always recommend a dermatologist |
| No product database | Frame all recommendations as ingredient criteria — "look for a vitamin C serum at pH 3.5 or below with 10–20% L-ascorbic acid" |
| Conflict checker retrieval | Store conflicts as a structured JSON lookup table used directly by the tool function, not retrieved from prose chunks |
| SPF regional variation | Pick one standard (EU/WHO) and state it clearly in the UI |

### Verdict

The highest-scoring idea overall on the combined metric. The conflict checker and introduction scheduler are genuinely useful tools that demonstrate clear value over existing apps. The knowledge base is achievable in two weeks if scoped to the top 15–20 actives. The conversational diagnostic flow ("my skin is reacting, what in my routine is causing it?") is the gap that Skincarisma's form-based approach cannot fill. Large market, clear monetization path (beauty affiliate is high-converting), and the RAG architecture is a genuine long-term advantage as the product scales to handle novel product combinations.

---

## Competitors & Existing Tools

| Competitor | What it does | Useful for |
|---|---|---|
| **INCI Decoder** (incidecoder.com) | Ingredient profiles, safety ratings, what-it-does summaries for any ingredient | Direct data boost — ingredient summaries are well-written and structured; use as primary KB source |
| **Skincarisma** | Routine builder, ingredient conflict checker, skin type profiling via static form | Closest direct competitor — study their conflict checker and routine sequencer UX carefully; your differentiation is the conversational layer |
| **Paula's Choice Ingredient Dictionary** | Free ingredient-by-ingredient analysis, evidence-based ratings, conflict notes | Excellent KB source — each page covers function, evidence, conflicts, and skin type suitability clearly |
| **CosDNA** | Ingredient analysis with community acne/irritant flagging and scoring | Good for the conflict/irritant layer of your KB; community-validated data on real-world reactions |
| **Yuka** | Product scanner with ingredient safety rating (food and cosmetics) | Shows a different angle on the same problem — ingredient safety for mass market; useful UX reference |

---

## Free Data & Content Boosts

- **Paula's Choice Ingredient Dictionary** — freely readable. Each ingredient page is almost perfectly structured for a RAG document: mechanism, evidence, conflicts, skin type suitability. Best primary KB source.
- **INCI Decoder** — freely browsable ingredient summaries. Good complement to Paula's Choice for breadth.
- **Reddit r/SkincareAddiction wiki** — community-validated FAQs and routine guides; great for understanding real user questions and common mistakes.
- **CosDNA** — ingredient conflict and irritant data based on community reporting; freely browsable.

---

## Differentiation

RAG genuinely earns its place. The conflict checker requires multi-document retrieval — checking retinol against AHA requires retrieving both ingredient profiles and the conflict rule document simultaneously. The conversational diagnostic flow ("I added this product two weeks ago and now I'm breaking out") cannot be handled by a static form — it requires maintaining conversation context, retrieving relevant ingredient profiles, and reasoning about their interactions. Skincarisma and INCI Decoder are databases; this is a reasoning agent. The gap is real and large enough to build a business in.

---

## Scoring

### School Project Score

| Criterion | Score /5 | Rationale |
|---|---|---|
| API simplicity | 5 | No external API needed |
| KB buildability | 3 | Good sources exist; requires curation of 15–20 actives plus conflict rules |
| Demo wow factor | 4 | Conflict checker and intro scheduler are impressive and immediately useful |
| Domain-agnostic | 3 | Basic skincare familiarity enough; no deep expertise required |
| 2-week achievability | 4 | Achievable; conflict JSON structure needs early design attention |
| Uniqueness | 3 | Skincare apps exist; conversational diagnostic angle is genuinely new |
| **School Total** | **22 / 30** | |

### Product Potential Score

| Criterion | Score /5 | Rationale |
|---|---|---|
| Market size | 5 | Very large — skincare is a multi-billion dollar category dominated by research-oriented 18–35 year olds |
| Monetization clarity | 5 | Product affiliate (high-converting in beauty), subscription, brand partnerships |
| Long-term defensibility | 5 | Conversational diagnostic approach requires RAG to do well; scales to novel product combinations a static DB can't handle |
| **Product Total** | **15 / 15** | |

### Combined Score: **37 / 45** — Rank 1 of 8
