# Festival Stage → Berlin Club Mapper

## Overview

A tool that maps festival stages to Berlin club vibes based on the artists playing there. The core insight: a festival stage is essentially a temporary club, defined by its curated lineup. If you can profile the artists on a stage using audio features and genre data, and compare that profile against known Berlin clubs, you get a meaningful, culturally grounded mapping. Born from the observation that at Garbicz festival (a well-known Polish underground electronic festival), certain stages feel indistinguishable in vibe from specific Berlin clubs. The output: "Stage X sounds like Watergate on a Sunday afternoon" — a useful reference for both festival-goers and people trying to discover new clubs.

---

## RAG Knowledge Base

- **Berlin club identity profiles:** Berghain/Panorama Bar, Tresor, Watergate, Sisyphos, About Blank, OHM, Wilde Renate, KitKat, Gretchen — each as a rich document covering resident artists, typical BPM ranges, sub-genres, time-of-day energy, crowd character, history
- **Electronic music genre taxonomy:** the differences between industrial techno, dub techno, hard techno, melodic techno, deep house, acid house, ambient techno — distinctions Spotify cannot make but that define club identity
- **Curated "artists associated with Club X" lists:** ground-truth rosters for each club built from RA event listings and public knowledge
- **Festival stage character guides:** documented identity of Garbicz stages (and potentially Dekmantel, Fusion) based on historical lineups
- **Influential DJ sets and tracklists:** documented and annotated sets associated with each club, for stylistic reference
- **Mixing culture by club:** what Berghain selectors do differently from Watergate residents — tempo, texture, crowd interaction style

---

## Tool Calls

| Tool | Inputs | Outputs |
|---|---|---|
| **Spotify artist audio feature fetcher** | Artist name | Avg BPM, energy, danceability, valence across top tracks |
| **Last.fm genre tag fetcher** | Artist name | Genre tags ranked by listener count — better than Spotify for underground artists |
| **Stage profiler** | List of artists on a stage | Aggregated audio fingerprint: avg BPM range, energy distribution, dominant genre tags |
| **Club matcher** | Stage fingerprint | Ranked list of Berlin clubs by similarity, with explanation of what matched |
| **Setlist.fm lineup fetcher** | Festival name, year | Historical stage-by-artist lineup from past editions (free API) |

---

## Technical Feasibility

### What makes it strong

The core insight is sharp and original: nobody has built this. The mapping of "festival stage = temporary club" is a genuine conceptual leap that translates naturally into a RAG + tool use architecture. The output is culturally resonant for the target audience. The Setlist.fm API solves the lineup data problem for past editions without manual curation. Last.fm solves the underground artist data problem that Spotify can't.

### How it would work technically

The user selects a festival and stage (or inputs a custom artist list). The stage profiler tool fetches audio features for each artist via Spotify, fills gaps with Last.fm tags, and aggregates into a stage fingerprint. The club matcher retrieves club profiles from the RAG KB and computes similarity. Results are presented with explanations: "This stage matches Watergate because of the melodic house dominance and mid-range BPMs, similar to residents Move D and Dixon."

### Drawbacks

1. **Underground artists are invisible on Spotify** — Garbicz books artists like Zip, Move D, Prosumer who have almost nothing on Spotify. Audio feature fetching fails silently or returns wrong-artist data.
2. **Spotify's genre tagging is terrible for electronic music** — it calls everything "electronic" or at best "techno," unable to distinguish the sub-genres that define the whole concept.
3. **No festival lineup API exists** — Garbicz, Fusion, Dekmantel have no structured API. Setlist.fm helps for past editions; new lineups require manual input.
4. **Club identity is not just audio features** — Berghain is darkness, concrete, a specific crowd, a political history. The mapping captures the music profile but misses the texture.
5. **Stage vibe shifts through the day** — the noon slot and the 5am slot on the same stage are two different clubs. A single stage-level mapping oversimplifies.
6. **Ground truth is subjective** — "this stage sounds like Club X" is an opinion. Two people who know Berlin will disagree. Validation is hard.
7. **Knowledge base requires deep domain expertise** — building accurate club profiles requires someone who actually knows these clubs.

### Workarounds

| Problem | Workaround |
|---|---|
| Artists not on Spotify | Fall back to Last.fm tags; if both fail, look up artist manually in RAG KB |
| Bad Spotify genre data | Weight Last.fm tags heavily; build a curated genre→club affinity table in the KB |
| No lineup API | Use Setlist.fm for past editions; provide a manual artist-list input for current lineups |
| Day/night vibe shift | Slot the lineup by time block; map each block separately with timestamps |
| Subjective ground truth | Frame all mappings as "musical fingerprint match" not absolute club identity; add confidence score |

### Verdict

The most original idea in the entire shortlist — nobody has built this. Works best as a demo with one festival (Garbicz) and a curated dataset rather than a live, generalised tool. The architecture (RAG + Spotify tools + club profile matching) is solid and demonstrates everything the requirements ask for. The limitation to acknowledge upfront is that it's a musical fingerprint match, not a full club culture match. Strong choice if you have deep personal knowledge of the Berlin club scene and Garbicz — your expertise is the knowledge base.

---

## Competitors & Existing Tools

| Competitor | What it does | Useful for |
|---|---|---|
| **Resident Advisor (RA)** | Electronic music events, club reviews, artist profiles, documented tracklists | Best source for club identity profiles and artist-club associations; use as primary KB source |
| **Last.fm** | Artist genre tags, similar artists, listening history | Free API with richer genre tags for underground artists than Spotify — critical tool for this project |
| **Setlist.fm** | Publicly documented festival and concert setlists by stage | Free API — pull historical Garbicz lineups per stage, solving the manual curation problem for past editions |
| **Songkick** | Concert and festival event discovery, artist touring schedules | Shows the market for festival information aggregation; your tool goes deeper on the vibe layer |
| **Soundplate** | Genre tagging, DJ tools, playlist tools for electronic music | Reference for how others categorise electronic music — useful for building your genre taxonomy |

---

## Free Data & Content Boosts

- **Setlist.fm API** — free, returns historical festival lineups by stage. Best single data boost for this project. Solves the lineup curation problem for past Garbicz editions.
- **Last.fm API** — free, no key required for basic use. Richer genre tags for underground artists. Essential fallback when Spotify fails.
- **Resident Advisor** — freely readable club reviews and artist profiles. Best source for writing club identity documents for the RAG KB.
- **Spotify Web API** — free developer account, audio features endpoint works without OAuth for read-only track data.

---

## Differentiation

Completely novel — no tool exists that maps festival stages to urban nightlife equivalents. RA describes clubs; Songkick lists lineups; nobody connects them through a vibe/fingerprint comparison. The RAG layer is essential: club identity descriptions are rich, multi-dimensional documents that cannot be reduced to a simple lookup table. The multi-source tool approach (Spotify + Last.fm + Setlist.fm + RAG) is sophisticated and demonstrates real agentic behaviour. The concept is replicable once visible — the moat is being first and having the best club profile knowledge base.

---

## Scoring

### School Project Score

| Criterion | Score /5 | Rationale |
|---|---|---|
| API simplicity | 3 | Multiple free APIs (Spotify read-only, Last.fm, Setlist.fm) — no OAuth required for core features |
| KB buildability | 1 | Club profiles are subjective and require deep domain knowledge; most manual-intensive KB of all ideas |
| Demo wow factor | 5 | Unique concept, culturally resonant output, easy to explain to anyone who goes to festivals |
| Domain-agnostic | 1 | Requires deep knowledge of Berlin clubs AND the festival scene |
| 2-week achievability | 2 | Lineup curation and knowledge base construction are significant time sinks |
| Uniqueness | 5 | Nobody has built this |
| **School Total** | **17 / 30** | |

### Product Potential Score

| Criterion | Score /5 | Rationale |
|---|---|---|
| Market size | 1 | Electronic music festival-goers in Europe — passionate but small and niche |
| Monetization clarity | 2 | Festival ticket affiliate, club night promotion — indirect and uncertain |
| Long-term defensibility | 3 | Unique concept short-term; thin moat long-term once visible |
| **Product Total** | **6 / 15** | |

### Combined Score: **23 / 45** — Rank 8 of 8
