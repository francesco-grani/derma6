# Project Ideas — Full Comparison

## Context

This document captures the full comparative analysis of 8 project ideas explored for an AI engineering school assignment. The requirements mandate: RAG implementation with embeddings and chunking, at least 3 tool calls, domain specialisation, LangChain with OpenRouter, and a Streamlit or Next.js UI. Ideas were evaluated from two perspectives: school project feasibility (2-week build) and product/portfolio potential (what happens if you keep developing it after the course).

---

## Scoring Rubric

All criteria scored **1–5**. Higher is always better for a school student building in two weeks. For product criteria, higher means more commercial potential.

### School Project Criteria

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **API simplicity** | No API needed | Free, simple REST | Free but rate-limited or needs account | OAuth or moderate complexity | Paid or unavailable |
| **KB buildability** | Well-documented, curated in days | Good sources, light manual work | Mixed sources, some manual curation | Sparse or contested sources | Must build from scratch or highly subjective |
| **Demo wow factor** | Produces a real tangible artefact | Visually impressive output | Functional and clear | Works but dry | Hard to show off |
| **Domain-agnostic** | Zero expertise needed | Basic familiarity enough | Some background helps | Significant expertise needed | Deep expert knowledge required |
| **2-week achievability** | Done in days, scope very clear | Comfortably achievable | Achievable if scoped well | Tight — one bad week kills it | Risky |
| **Uniqueness** | Nobody has built this | Rare, fresh angle | Common category, distinct enough | Seen before | Generic |

### Product Potential Criteria

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **Market size** | Very large (millions of potential users) | Large | Medium | Small | Niche |
| **Monetization clarity** | Proven model, clear path | Clear path, some uncertainty | Possible, indirect | Indirect, uncertain | No obvious path |
| **Long-term defensibility** | RAG/AI architecture creates lasting advantage | Strong moat | Moderate — competitors could replicate | Thin moat | Easy to replicate |

---

## School Project Scores

| | German Property | CrossFit | DJ Builder | Festival→Club | Coffee Guide | Wine Pairing | Historical | Skincare |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| API simplicity | 2 | 5 | 2 | 3 | 5 | 5 | 5 | 5 |
| KB buildability | 3 | 5 | 3 | 1 | 5 | 3 | 1 | 3 |
| Demo wow factor | 3 | 3 | 4 | 5 | 3 | 3 | 3 | 4 |
| Domain-agnostic | 2 | 1 | 1 | 1 | 3 | 3 | 3 | 3 |
| 2-week achievability | 3 | 4 | 3 | 2 | 5 | 5 | 3 | 4 |
| Uniqueness | 3 | 3 | 4 | 5 | 2 | 2 | 3 | 3 |
| **School Total /30** | **16** | **21** | **17** | **17** | **23** | **21** | **18** | **22** |

---

## Product Potential Scores

| | German Property | CrossFit | DJ Builder | Festival→Club | Coffee Guide | Wine Pairing | Historical | Skincare |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Market size | 4 | 2 | 3 | 1 | 3 | 4 | 3 | 5 |
| Monetization clarity | 4 | 3 | 2 | 2 | 3 | 4 | 2 | 5 |
| Long-term defensibility | 4 | 3 | 2 | 3 | 1 | 3 | 3 | 5 |
| **Product Total /15** | **12** | **8** | **7** | **6** | **7** | **11** | **8** | **15** |

---

## Combined Scores & Final Ranking

| Rank | Idea | School /30 | Product /15 | Combined /45 |
|---|---|:---:|:---:|:---:|
| 1 | Skincare Routine Builder | 22 | 15 | **37** |
| 2 | Wine Pairing Assistant | 21 | 11 | **32** |
| 3 | Coffee Brewing Guide | 23 | 7 | **30** |
| 4 | CrossFit Coach | 21 | 8 | **29** |
| 5 | German Property Agent | 16 | 12 | **28** |
| 6 | Historical Explorer | 18 | 8 | **26** |
| 7 | DJ Set Builder | 17 | 7 | **24** |
| 8 | Festival → Club Mapper | 17 | 6 | **23** |

---

## Does RAG Actually Earn Its Place?

A key question for any of these: does the RAG architecture add genuine value, or is it just a static FAQ with extra steps?

| Idea | RAG justified? | Why |
|---|---|---|
| German Property | Yes | Questions cross mortgage, tax, and legal documents simultaneously |
| CrossFit | Yes | Scaling suggestions require retrieving movement + programming + stimulus docs together |
| DJ Set Builder | Partially | Music theory KB is thin; most value comes from Spotify API tools, not retrieval |
| Festival→Club | Yes | Club identity matching requires retrieving multiple club profiles and genre taxonomy simultaneously |
| Coffee Guide | Weakly | Most questions are answered by a single recipe doc; troubleshooting is the only strong RAG case |
| Wine Pairing | Yes | Pairing questions combine grape profiles + regional context + pairing principles |
| Historical Explorer | Yes | Simultaneity queries require multi-geography retrieval — the strongest RAG case of all |
| Skincare Builder | Yes | Conflict checker retrieves two ingredient profiles + conflict rules simultaneously |

---

## Competitor Landscape Summary

| Idea | Market saturation | Biggest competitor | Your differentiation |
|---|---|---|---|
| German Property | Low (Germany-specific gap) | Hypofriend (mortgages only) | End-to-end journey, WEG layer, conversational |
| CrossFit | Medium | BTWB (paid, gym-centric) | Free, solo-athlete, explanation layer |
| DJ Set Builder | High | DJ.Studio | RAG explanation layer, Spotify integration |
| Festival→Club | None | RA (no mapping feature) | Entirely novel concept |
| Coffee Guide | High | James Hoffmann + brew apps | Conversational troubleshooting |
| Wine Pairing | High | Vivino | Educational "why" layer, not just "what" |
| Historical Explorer | Medium | Wikipedia | Simultaneity mapper, causality connections |
| Skincare Builder | Medium | Skincarisma (static form) | Conversational diagnostic flow |

---

## Key Insights

### Pick this if you want the easiest school project
**Coffee Brewing Guide** (school score: 23/30) — zero APIs, well-documented knowledge base, tools are pure math. Done comfortably in two weeks. Trade-off: weakest product potential of the group.

### Pick this if you want the best portfolio/product balance
**Skincare Routine Builder** (combined score: 37/45) — achievable in two weeks, genuinely useful tools, large market, clear monetization, and the RAG architecture is a real long-term advantage. Top pick overall.

### Pick this if you want the most impressive school demo
**Festival → Club Mapper** (demo wow: 5/5) — unique, culturally specific, immediately explainable to anyone. Trade-off: hardest knowledge base to build, lowest product score, requires deep domain knowledge.

### Pick this if you have specific domain expertise
- Do CrossFit → **CrossFit Coach** jumps ~3 points
- DJ seriously → **DJ Set Builder** jumps ~3 points
- Know Berlin clubs and Garbicz → **Festival Mapper** jumps ~4 points
- Based in Germany and know the property market → **German Property** jumps ~3 points

### Pick this if you want the strongest RAG demonstration for the evaluator
**Historical Explorer** — the simultaneity mapper is the clearest demonstration of why RAG beats a simple lookup. The multi-geography, multi-period retrieval problem is textbook RAG. Trade-off: knowledge base construction is the bottleneck; must be aggressively scoped.

### Best free data boosts by idea
| Idea | Best boost | Type |
|---|---|---|
| German Property | Interhyp Ratgeber + Immowelt guides | Free readable content |
| CrossFit | WodWell.com | Free public WOD database |
| DJ Set Builder | GitHub Camelot implementations | Open source code |
| Festival→Club | Setlist.fm API + Last.fm API | Free APIs |
| Coffee Guide | Barista Hustle articles | Free readable content |
| Wine Pairing | Wine Folly website | Free structured content |
| Historical Explorer | World History Encyclopedia API | **Free structured API — strongest boost overall** |
| Skincare Builder | Paula's Choice + INCI Decoder | Free readable content |
