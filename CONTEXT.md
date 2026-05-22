# Skincare Routine Builder

A conversational RAG assistant that helps male skincare beginners diagnose and optimise their skincare routine.

## Language

**Tool**:
A discrete Python function the LLM invokes with structured arguments, returning structured output. All five domain functions (conflict checker, routine sequencer, skin type advisor, introduction scheduler, SPF recommender) are Tools.
_Avoid_: tool call, function, action

**Knowledge Base**:
The curated set of skincare documents (ingredient profiles, conflict rules, routine guides) indexed for vector retrieval. Capped at 15–20 focused entries.
_Avoid_: KB, documents, index

## Relationships

- Each **Knowledge Base** document maps to one chunk — whole-document retrieval, no section splitting
- The **Knowledge Base** is backed by a persistent local ChromaDB instance (not rebuilt on every startup)
- A **User Profile** contains one or more **Routines**
- A **Tool** may query the **Knowledge Base** via retrieval, or call a **Conflict Table** directly
- The **Conflict Checker** Tool reads the **Conflict Table** deterministically — it never goes through vector retrieval
- The **Knowledge Base** is the sole authoritative source for ingredient science in the app

**Conflict Table**:
A structured JSON lookup (not a Knowledge Base document) enumerating all known ingredient conflict pairs with severity and mechanism. The authoritative source for the Conflict Checker Tool.
_Avoid_: conflict document, conflict knowledge base

**User Profile**:
The persisted record of a single user's skin type, current routine, and preferences. Identified by a plain username (no password). Survives across sessions. Stored in a backend layer, not in Streamlit session state.
_Avoid_: session state, user session, user data, user account

**Routine**:
A named, ordered list of Routine Steps a user applies at a particular time of day. A User Profile holds one or more Routines (e.g., "Morning", "Evening", "Travel").
_Avoid_: product list, regimen, skincare stack

**Routine Step**:
A single step in a Routine. In v1, holds an ingredient name only. Designed as a data structure (not a plain string) so a product name and ingredient metadata (pH, texture, time-of-day) can be added later without a schema migration.
_Avoid_: step, product, entry

**Onboarding Flow**:
The first-session experience for a new user. The LLM asks a fixed set of profile questions (skin type, concerns, shaving flag, medical flags) one at a time in conversational tone — structured data collection that feels like a chat, not a form. Always covers the same fields; phrasing varies.
_Avoid_: onboarding form, questionnaire, setup wizard

**Introduction Plan**:
A persisted, structured schedule in the Profile Store created by the Introduction Scheduler Tool. Tracks which actives to introduce when, milestone dates, and current status. Secondary feature — designed from the start but implemented after core Tools are working.
_Avoid_: intro plan, schedule, plan

**Routine Sequencer**:
The Tool that takes a Routine's Steps and returns them in canonical application order (cleanser → toner → serum → moisturiser → SPF). In v1, classification is fixed-rule. Metadata fields on Routine Step are reserved for a future pH/texture-aware upgrade.
_Avoid_: sequencer, order tool

**Profile Store**:
The SQLite database (single `.db` file) that persists all User Profiles. Also stores conversation history via LangChain's `SQLChatMessageHistory`.
_Avoid_: database, DB, storage layer

**Session**:
A single browser interaction from open to close. Session state (Streamlit `st.session_state`) holds in-flight conversation history only — everything worth keeping is written to the User Profile.
_Avoid_: session memory, chat state

**Conflict Checker**:
The Tool that takes two ingredient names and returns a deterministic conflict verdict (safe / use at different times / do not use together) by querying the Conflict Table directly.
_Avoid_: conflict tool, ingredient checker

**SPF Standard**:
All SPF recommendations follow EU/international guidelines (ISO 24444, SPF 50+ minimum, PA+++ for UVA). Stated once in the UI. Not configurable per user.
_Avoid_: SPF rating, sunscreen standard

**Citation**:
A bracketed source reference appended at the end of an agent response, listing the Knowledge Base documents retrieved for that answer (e.g., `[Retinol Profile, AHA Guide]`). Never inline.
_Avoid_: source, reference, footnote

**LLM**:
The language model powering the agent. Default: `openai/gpt-4o-mini` via OpenRouter. Configurable via environment variable to allow model swaps without code changes.
_Avoid_: model, AI, GPT

**Medical Flag**:
A skin condition (e.g., eczema, rosacea) recorded on the User Profile during the Onboarding Flow. When present, appends a dermatologist disclaimer to every Tool response via the system prompt. Does not block advice.
_Avoid_: health flag, condition, warning

## Flagged ambiguities

- "tool call" (assignment language) vs. "tool" (domain language) — resolved: use **Tool** throughout; the assignment meaning and our meaning are identical.
