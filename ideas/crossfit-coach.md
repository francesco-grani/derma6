# CrossFit & Hero Benchmark Coach

## Overview

A training assistant specialised in CrossFit methodology, centred on the benchmark WODs ("The Girls": Fran, Grace, Helen…) and Hero WODs (Murph, DT, Badger…). Helps athletes track performance, understand scaling, and plan training cycles. Targeted at solo CrossFit athletes and home gym owners who don't have a dedicated coach. The Hero WODs carry emotional resonance (named after fallen soldiers and first responders), which gives the knowledge base a storytelling layer that purely informational fitness apps lack.

---

## RAG Knowledge Base

- **Benchmark WOD database:** full list of "The Girls" and other canonical benchmarks — rep schemes, standards, intended stimulus, world-record context, expected time domains by skill level
- **Hero WOD database:** full list of Hero WODs with the backstory of each person honoured, workout structure, Rx standards, scaling guidance
- **Movement library:** technique cues, common faults, scaling options by fitness level for every major CrossFit movement (kipping pull-up, double-under, squat clean, snatch, muscle-up, handstand walk, etc.)
- **Programming methodology:** GPP (general physical preparedness) principles, time domain theory, energy system training, periodisation basics
- **Scaling philosophy:** what "scaling" means in CrossFit, how to preserve stimulus while reducing load/volume/complexity
- **Nutrition for high-intensity athletes:** fuelling around MetCons, recovery nutrition, hydration, common mistakes
- **Common injuries and prehab:** shoulder, lower back, knee — causes, prehab protocols, return-to-sport timelines
- **CrossFit Open history:** past Open workouts, standards, and typical scoring benchmarks

---

## Tool Calls

| Tool | Inputs | Outputs |
|---|---|---|
| **1RM & percentage calculator** | 1RM weight, unit (kg/lb) | Full percentage table from 50% to 100% in 5% increments |
| **WOD percentile scorer** | WOD name, user's score/time | Approximate skill-level bracket (beginner / intermediate / advanced / elite) vs. community norms |
| **Benchmark WOD selector** | Modality filter (barbell / gymnastics / monostructural / mixed), time domain, equipment available | Filtered list of matching WODs with descriptions |
| **Scaling suggester** | Movement name, current ability description | 2–3 scaled versions of the movement with load/rep adjustments and stimulus rationale |
| **Weekly volume tracker** | Sessions per week, movements trained, loads | Weekly load summary, flag if week-on-week increase exceeds 10% safe ramp rate |

---

## Technical Feasibility

### What makes it strong

The domain is unusually well-documented for a niche topic. Every benchmark WOD, every Hero WOD, every movement standard is publicly written down — CrossFit published it all. The RAG knowledge base practically builds itself. Tools are pure math — no external API dependencies at all. The Hero WODs carry emotional weight in demos. The scaling suggester is the most technically interesting tool: it requires retrieving movement-specific knowledge and applying coaching reasoning, which demonstrates RAG + tool use working together naturally.

### How it would work technically

The agent asks for the user's current fitness level and equipment availability at the start of the conversation, stores this in session state, and uses it to contextualise all subsequent answers. WOD lookups retrieve from the knowledge base. Calculator tools run locally. The Streamlit UI can show a session "profile" panel alongside the chat showing the user's benchmark PRs.

### Drawbacks

1. **No live community benchmark API** — Beyond The Whiteboard and SugarWOD are the main platforms; both are paid with no public API. Any percentile ranking will come from hardcoded community norm tables, not live data.
2. **Scaling requires coaching judgment** — the right scale depends on the intended stimulus. An AI can give technically correct options but may miss the point of the workout, which a real coach would catch.
3. **Technique is visual** — CrossFit movement technique is very hard to convey in text alone. A chatbot cannot replace video for kipping mechanics or snatch turnover.
4. **Injury risk** — if someone follows a poorly calibrated scaling suggestion and gets hurt, that's a real problem. Strong disclaimers and "consult a coach" gates are required.
5. **Programming is deeply individual** — generating a training plan requires knowing background, weaknesses, schedule, and goals. Generic AI programming can be counterproductive.
6. **Niche market** — the evaluator may not know CrossFit well enough to appreciate domain depth.

### Workarounds

| Problem | Workaround |
|---|---|
| No benchmark API | Manually curate community norm ranges by skill tier (e.g., "Fran: beginner >10min, intermediate 5–10min, advanced 3–5min, elite <3min") as static JSON |
| Scaling judgment | Always present 2–3 scaling options with stimulus rationale; never give a single authoritative answer |
| Visual technique gap | Return curated YouTube links as citations in responses |
| Injury risk | Hard disclaimer on every programming or technique output; recommend consulting a CrossFit-certified coach |

### Verdict

The most technically achievable of all ideas — no OAuth, no tricky APIs, no scraping. Everything is either custom math or a well-documented static knowledge base. The benchmark data approximation is the main limitation, but fully defensible for a school project. Strong choice if you have genuine CrossFit knowledge yourself, because domain expertise will make the knowledge base significantly better. The emotional layer of Hero WODs makes demos more engaging than a dry fitness calculator would be.

---

## Competitors & Existing Tools

| Competitor | What it does | Useful for |
|---|---|---|
| **Beyond The Whiteboard (BTWB)** | Community benchmark tracking, percentile scoring, workout logging | Benchmark norm data — their blog posts publish aggregated community stats (Fran times by level, etc.) |
| **SugarWOD** | Gym workout tracking, scaling suggestions, coach notes | Inspiration for the scaling suggestion UX and how to present WOD results |
| **WodWell** (wodwell.com) | Free public database of thousands of WODs with descriptions, scaling options, movement standards | Direct data boost — freely accessible, well-structured WOD database you can adapt for your RAG KB |
| **Wodify** | Gym management platform with movement libraries and programming tools | Inspiration for movement taxonomy and how to structure technique guides |
| **TrainHeroic** | Programming platform used by professional CrossFit coaches and boxes | Shows the market for coach-side programming tools; your tool targets the athlete side |

---

## Free Data & Content Boosts

- **WodWell.com** — free public WOD database, well-structured, covers benchmarks and Heroes with scaling options. Best single KB source for this idea.
- **CrossFit's official website** — all benchmark and Hero WOD standards are published openly
- **CrossFit Level 1 Training Guide** — freely available PDF covering methodology, movement standards, and programming principles
- **Open Gym Premium blog** — publicly available articles on CrossFit programming theory

---

## Differentiation

RAG earns its place because CrossFit questions are rarely simple lookups. "Should I scale Murph?" requires retrieving the WOD structure, the user's fitness context, and the scaling philosophy simultaneously. BTWB does tracking better but is gym-centric, paywalled, and not conversational. A free AI coaching agent that explains the *why* behind scaling decisions is genuinely underserved. The Hero WOD backstory layer adds a dimension no existing app has.

---

## Scoring

### School Project Score

| Criterion | Score /5 | Rationale |
|---|---|---|
| API simplicity | 5 | No external API needed at all |
| KB buildability | 5 | All WODs and movement standards are publicly documented |
| Demo wow factor | 3 | Functional and useful; not visually spectacular without domain knowledge |
| Domain-agnostic | 1 | Deep CrossFit knowledge needed to build a good knowledge base |
| 2-week achievability | 4 | Comfortably achievable; scope is clear and bounded |
| Uniqueness | 3 | Niche but not novel; fitness chatbots are common |
| **School Total** | **21 / 30** | |

### Product Potential Score

| Criterion | Score /5 | Rationale |
|---|---|---|
| Market size | 2 | ~4M active CrossFit athletes globally; passionate but small |
| Monetization clarity | 3 | Subscription or gym licensing; proven in adjacent tools |
| Long-term defensibility | 3 | AI coaching explanation layer is new; BTWB could replicate it |
| **Product Total** | **8 / 15** | |

### Combined Score: **29 / 45** — Rank 4 of 8
