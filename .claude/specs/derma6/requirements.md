# Requirements Document

## Introduction

Derma6 is a conversational RAG chatbot designed to help male skincare beginners diagnose and optimise their skincare routines. The system provides personalised advice through a chat interface backed by a curated knowledge base of 15–20 domain documents. It exposes five specialised domain Tools (Conflict Checker, Routine Sequencer, Skin Type Advisor, Introduction Scheduler, SPF Recommender), persists user profiles and chat history in SQLite, and stores vector embeddings in a persistent local ChromaDB instance. The frontend is built with Streamlit and communicates with a fully decoupled Python backend. All LLM calls are routed through OpenRouter using the openai/gpt-4o-mini model via a LangChain-compatible interface.

---

## Requirements

### Requirement 1 — Backend / Frontend Decoupling

**User Story:** As a developer, I want the Python backend and Streamlit frontend to be fully decoupled, so that the frontend can be replaced (e.g. migrated to FastHTML) without touching business logic.

#### Acceptance Criteria

1. WHEN the Streamlit frontend sends a user message THEN the system SHALL route the request to the backend through a well-defined internal API or service boundary, not by calling LangChain components directly from Streamlit.
2. WHERE business logic, LLM orchestration, tool invocation, and RAG retrieval are implemented THEN the system SHALL place them exclusively in the backend layer, with no business logic residing in the Streamlit layer.
3. WHEN the backend processes a request THEN the system SHALL return a structured response object containing the assistant message, a list of cited source documents, and any tool results, so that the frontend only performs rendering.
4. IF the frontend layer is replaced THEN the system SHALL continue to function correctly because the backend exposes a stable internal interface independent of the presentation layer.

---

### Requirement 2 — User Identity and Authentication

**User Story:** As a male skincare beginner, I want to identify myself with a plain username, so that my profile and chat history are saved without needing a password.

#### Acceptance Criteria

1. WHEN a user provides a username on the welcome screen THEN the system SHALL create or retrieve the corresponding user profile from the Profile Store without requiring a password.
2. IF a username already exists in the Profile Store THEN the system SHALL load the existing profile and chat history for that user.
3. IF a username does not exist in the Profile Store THEN the system SHALL create a new user record and trigger the Onboarding Flow.
4. WHEN a username is submitted THEN the system SHALL validate that it is a non-empty string and SHALL reject usernames containing only whitespace.
5. WHERE user identification is implemented THEN the system SHALL NOT store passwords, tokens, or any authentication credentials.

---

### Requirement 3 — User Profile and Profile Store

**User Story:** As a user, I want my skin type, concerns, and routines to be saved persistently, so that the chatbot remembers me across sessions.

#### Acceptance Criteria

1. WHEN a user profile is created or updated THEN the system SHALL persist the following fields in the Profile Store: `skin_type`, `skin_concerns` (list), `has_shaving_routine` (boolean), `medical_flags` (list), and zero or more named Routines.
2. WHEN the system stores a Routine THEN each Routine SHALL contain an ordered list of Routine Steps, where each Step is a data structure with at minimum an `ingredient` field and a nullable `product_name` field.
3. WHEN a user updates their skin type or concerns THEN the system SHALL overwrite the corresponding fields in the Profile Store and confirm the update in the chat response.
4. WHILE a user session is active THEN the system SHALL make the current user profile available to all domain Tools and the LLM orchestration layer.
5. IF a profile field is not yet collected THEN the system SHALL treat it as null and SHALL NOT crash or return an error when accessing that field.
6. WHERE the Profile Store is implemented THEN the system SHALL use SQLite as the storage engine.

---

### Requirement 4 — Chat History Persistence

**User Story:** As a user, I want my conversation history to be saved, so that the chatbot can reference prior messages within and across sessions.

#### Acceptance Criteria

1. WHEN a user sends a message THEN the system SHALL append both the user message and the assistant response to the chat history in SQLite using LangChain `SQLChatMessageHistory`.
2. WHEN a user returns to the application THEN the system SHALL load the existing chat history for that username and present it in the Streamlit chat window.
3. WHEN the LLM generates a response THEN the system SHALL include a recent window of chat history as context, so that the assistant maintains conversational coherence.
4. IF the chat history for a user is empty THEN the system SHALL start a new conversation without error.

---

### Requirement 5 — Onboarding Flow

**User Story:** As a new user, I want the chatbot to ask me about my skin through natural conversation, so that it can build my profile before giving advice.

#### Acceptance Criteria

1. WHEN a new user is detected THEN the system SHALL initiate the Onboarding Flow by asking the user a fixed set of profile questions conversationally.
2. WHEN the Onboarding Flow is active THEN the system SHALL collect, at minimum, the following fields: skin type, primary skin concerns, whether the user has a shaving routine, and any relevant medical flags.
3. WHEN collecting profile information during onboarding THEN the system SHALL use the LLM to vary the phrasing of questions naturally while keeping the set of fields constant across all users.
4. WHEN the user provides an answer to an onboarding question THEN the system SHALL persist the extracted value to the Profile Store before asking the next question.
5. IF the user skips or declines to answer an onboarding question THEN the system SHALL mark the field as null and proceed to the next question without blocking.
6. WHEN all onboarding questions have been answered or skipped THEN the system SHALL confirm that the profile is set up and transition to the regular chat mode.

---

### Requirement 6 — Knowledge Base

**User Story:** As a developer, I want a curated, scoped knowledge base, so that the RAG system retrieves accurate and domain-relevant skincare information.

#### Acceptance Criteria

1. WHEN the knowledge base is populated THEN the system SHALL contain between 15 and 20 whole-document chunks covering the following topics: ingredient profiles (retinol, niacinamide, vitamin C, AHAs, BHAs, hyaluronic acid, peptides, ceramides, benzoyl peroxide, azelaic acid, SPF actives), ingredient conflict rules, skin type classification guide, routine sequencing rules, common skincare mistakes guide, skin concern guides, and men-specific documents (razor burn, post-shave barrier repair, shaving physiology, beginner 3-step routine).
2. WHEN a knowledge base document is ingested THEN the system SHALL embed it using a LangChain-compatible embedding model and store the resulting vector in the persistent local ChromaDB instance.
3. WHEN the ChromaDB instance is initialised THEN the system SHALL load embeddings from the persistent storage directory, so that re-ingestion on every startup is not required.
4. IF the ChromaDB collection is empty at startup THEN the system SHALL ingest all knowledge base documents and persist the embeddings before serving any requests.
5. WHERE knowledge base documents are stored THEN the system SHALL retain document metadata (title, topic category) alongside each vector so that the retriever can return source names for citation.

---

### Requirement 7 — RAG Retrieval

**User Story:** As a user, I want the chatbot's answers to be grounded in the knowledge base, so that I receive accurate skincare information rather than generic LLM output.

#### Acceptance Criteria

1. WHEN the LLM needs domain knowledge to answer a user query THEN the system SHALL retrieve the top-k most semantically relevant documents from ChromaDB using vector similarity search.
2. WHEN retrieved documents are passed to the LLM THEN the system SHALL include the document content in the prompt context so that the LLM can ground its response.
3. WHEN a response is generated using retrieved documents THEN the system SHALL include square-bracket citations at the end of the response listing the source document titles (e.g. `[Retinol Profile, AHA Guide]`).
4. IF no relevant documents are retrieved above a minimum similarity threshold THEN the system SHALL instruct the LLM to acknowledge the gap rather than hallucinate an answer.
5. WHERE RAG is implemented THEN the system SHALL use LangChain retrieval components integrated with the ChromaDB vector store.

---

### Requirement 8 — Tool: Conflict Checker

**User Story:** As a user, I want to know whether two skincare ingredients are safe to combine, so that I avoid harmful interactions.

#### Acceptance Criteria

1. WHEN a user asks whether two ingredients can be combined THEN the system SHALL invoke the Conflict Checker Tool.
2. WHEN the Conflict Checker is invoked with two ingredient names THEN the system SHALL look up the pair in a deterministic JSON lookup table and SHALL return one of three verdicts: `safe`, `use-at-different-times`, or `do-not-use`.
3. WHERE the Conflict Checker is implemented THEN the system SHALL use a static JSON lookup table and SHALL NOT perform a RAG retrieval for this tool, ensuring fully deterministic results.
4. WHEN the Conflict Checker returns a verdict THEN the system SHALL include a brief explanation of the reason alongside the verdict in the chat response.
5. IF an ingredient name is not present in the lookup table THEN the system SHALL return an explicit "unknown ingredient" result and SHALL NOT silently default to a `safe` verdict.
6. WHEN the Conflict Checker Tool is called THEN the system SHALL log the input ingredient pair and the returned verdict.

---

### Requirement 9 — Tool: Routine Sequencer

**User Story:** As a user, I want to know the correct order in which to apply my skincare products, so that each product works as intended.

#### Acceptance Criteria

1. WHEN a user asks how to order their skincare products or ingredients THEN the system SHALL invoke the Routine Sequencer Tool.
2. WHEN the Routine Sequencer is invoked THEN the system SHALL apply the fixed canonical step order: cleanser → toner → serum → moisturiser → SPF, and place user-provided products or ingredients into the appropriate positions.
3. WHERE the Routine Sequencer v1 is implemented THEN the system SHALL use the fixed canonical order only and SHALL NOT incorporate pH-awareness or texture-based ordering (those are deferred to v2).
4. WHEN the Routine Sequencer produces an ordered list THEN the system SHALL return the ordered steps to the user in a clearly formatted response.
5. WHEN a product or ingredient cannot be classified into a canonical step THEN the system SHALL flag it explicitly in the response rather than silently omitting it.

---

### Requirement 10 — Tool: Skin Type Advisor

**User Story:** As a user, I want the chatbot to classify my skin type from my description, so that I receive advice tailored to my specific skin.

#### Acceptance Criteria

1. WHEN a user describes their skin characteristics or asks for skin type guidance THEN the system SHALL invoke the Skin Type Advisor Tool.
2. WHEN the Skin Type Advisor is invoked THEN the system SHALL perform a RAG retrieval against the skin type guide document(s) and use the retrieved content to classify the user into one of the following types: oily, dry, combination, sensitive, dehydrated, acneic.
3. WHEN a skin type classification is produced THEN the system SHALL persist the result to the `skin_type` field in the user's Profile Store record.
4. WHEN the Skin Type Advisor returns a classification THEN the system SHALL include an explanation of the distinguishing characteristics that led to that classification.
5. IF insufficient information is available to classify the skin type THEN the system SHALL ask clarifying questions rather than returning a speculative classification.

---

### Requirement 11 — Tool: SPF Recommender

**User Story:** As a user, I want SPF recommendations that meet international safety standards, so that I am protected from UV damage.

#### Acceptance Criteria

1. WHEN a user asks for SPF or sunscreen recommendations THEN the system SHALL invoke the SPF Recommender Tool.
2. WHEN the SPF Recommender is invoked THEN the system SHALL perform a RAG retrieval against the SPF actives and related documents.
3. WHEN the SPF Recommender returns a recommendation THEN the system SHALL only recommend products or formulations meeting the EU/international standard of SPF 50+ and PA+++ or higher.
4. IF the user requests a lower SPF level (e.g. SPF 30) THEN the system SHALL explain why SPF 50+ is the recommended standard and SHALL NOT endorse a lower protection level.
5. WHEN the SPF Recommender generates a response THEN the system SHALL include citations to the relevant knowledge base documents (e.g. `[SPF Actives Guide]`).

---

### Requirement 12 — Tool: Introduction Scheduler (Secondary Feature)

**User Story:** As a user, I want a week-by-week plan for safely introducing new actives, so that I do not overwhelm my skin barrier.

#### Acceptance Criteria

1. WHEN a user asks how to introduce one or more new skincare actives THEN the system SHALL invoke the Introduction Scheduler Tool.
2. WHEN the Introduction Scheduler is invoked THEN the system SHALL generate a 6–8 week phased introduction plan that sequences new actives safely, respecting known conflict rules.
3. WHEN an Introduction Plan is generated THEN the system SHALL persist the plan to the Profile Store associated with the current user.
4. WHEN a persisted Introduction Plan exists for a user THEN the system SHALL be able to retrieve and display that plan on request.
5. IF generating the plan would require combining two ingredients flagged as `do-not-use` by the Conflict Checker THEN the system SHALL surface a warning and SHALL NOT include that combination in the plan.

---

### Requirement 13 — Medical Flags and Dermatologist Disclaimer

**User Story:** As a user with a skin condition or medical concern, I want to be informed when professional advice is recommended, so that I use the chatbot safely.

#### Acceptance Criteria

1. WHEN the user mentions a skin condition or concern that is recorded as a medical flag in their profile THEN the system SHALL append a soft dermatologist disclaimer to the response.
2. WHEN the system appends a disclaimer THEN the disclaimer SHALL advise the user to consult a qualified dermatologist for their specific condition and SHALL NOT constitute a hard block preventing the response from being delivered.
3. WHERE medical flags are stored THEN the system SHALL persist them in the `medical_flags` list field of the Profile Store.
4. IF the user provides information during onboarding or conversation that indicates a potential medical flag THEN the system SHALL ask a clarifying question and, upon confirmation, record the flag in the Profile Store.
5. WHEN a medical flag is active THEN the system SHALL NOT refuse to respond; it SHALL provide the best available skincare information and append the disclaimer.

---

### Requirement 14 — Citations

**User Story:** As a user, I want to see which knowledge base sources informed the chatbot's response, so that I can trust and verify the advice.

#### Acceptance Criteria

1. WHEN the LLM generates a response using retrieved documents THEN the system SHALL append a citation block at the end of the response using square-bracket notation listing source document titles (e.g. `[Retinol Profile, AHA Guide]`).
2. WHEN the Streamlit UI displays a response THEN the system SHALL render the citation block in a visually distinct section (e.g. "Sources" expander or footer) so that users can identify which documents were used.
3. IF a response is generated without any RAG retrieval (e.g. small talk or a deterministic tool response) THEN the system SHALL omit the citation block rather than displaying an empty citation.
4. WHERE citations are generated THEN the system SHALL use the document title metadata stored alongside each ChromaDB vector to populate the citation list.

---

### Requirement 15 — LLM Integration

**User Story:** As a developer, I want all LLM calls routed through OpenRouter using a LangChain-compatible interface, so that the model can be swapped without rewriting orchestration logic.

#### Acceptance Criteria

1. WHEN the system makes an LLM call THEN it SHALL use the `openai/gpt-4o-mini` model via the OpenRouter API endpoint configured as an OpenAI-compatible provider in LangChain.
2. WHERE LLM calls are implemented THEN the system SHALL use LangChain's chat model abstraction so that switching to a different model or provider requires only a configuration change.
3. WHEN the OpenRouter API key is required THEN the system SHALL read it from an environment variable and SHALL NOT hardcode credentials in source files.
4. WHEN the system constructs a prompt for the LLM THEN it SHALL include the system prompt defining the assistant's domain, persona, and tool usage instructions.

---

### Requirement 16 — Tool Invocation (Minimum Three Tools)

**User Story:** As a developer, I want at least three domain tools to be callable by the LLM, so that the assignment requirement for tool use is satisfied and users receive specialised, structured responses.

#### Acceptance Criteria

1. WHEN the LLM determines that a user query requires specialised domain processing THEN the system SHALL make the appropriate tool available for invocation via LangChain's tool-calling interface.
2. WHERE tools are registered THEN the system SHALL register at minimum the Conflict Checker, Routine Sequencer, and Skin Type Advisor tools, satisfying the assignment requirement of at least three tool calls.
3. WHEN a tool is invoked THEN the system SHALL pass the tool's structured output back to the LLM so that the LLM can incorporate the result into a coherent natural-language response.
4. WHEN a tool call is made THEN the system SHALL log the tool name, input parameters, and output result for observability.

---

### Requirement 17 — Input Validation

**User Story:** As a developer, I want all user inputs to be validated before processing, so that the system handles unexpected or malicious inputs gracefully.

#### Acceptance Criteria

1. WHEN a user message is received THEN the system SHALL validate that the input is a non-empty string before passing it to the LLM or any tool.
2. WHEN a tool receives parameters from the LLM THEN the tool SHALL validate that required parameters are present and of the expected type before executing.
3. IF a user message exceeds a configurable maximum token or character limit THEN the system SHALL truncate or reject the input and inform the user with a clear error message.
4. IF tool parameters fail validation THEN the system SHALL return a structured error response to the LLM rather than raising an unhandled exception.
5. WHERE input validation is implemented THEN the system SHALL sanitise inputs to prevent prompt injection by limiting the content passed to system prompt slots.

---

### Requirement 18 — Error Handling

**User Story:** As a user, I want the chatbot to recover gracefully from errors, so that a failure in one component does not crash the entire session.

#### Acceptance Criteria

1. WHEN an LLM API call fails due to a network error or API error THEN the system SHALL catch the exception, log the error, and return a user-friendly error message without exposing stack traces.
2. WHEN a tool raises an unhandled exception THEN the system SHALL catch the exception, log the error with the tool name and input, and return a graceful fallback message to the user.
3. WHEN a ChromaDB retrieval fails THEN the system SHALL log the error and respond to the user without RAG context, explicitly noting that the knowledge base is temporarily unavailable.
4. WHEN a Profile Store read or write fails THEN the system SHALL log the error and continue the session using the in-memory state, informing the user that their data may not be saved.
5. IF an unexpected error occurs at the backend boundary THEN the system SHALL return a structured error object to the frontend rather than raising an unhandled exception, so that the Streamlit layer can display a safe error message.

---

### Requirement 19 — Logging and Monitoring

**User Story:** As a developer, I want structured logging throughout the system, so that I can observe behaviour, debug issues, and monitor tool usage.

#### Acceptance Criteria

1. WHEN the application starts THEN the system SHALL initialise a logger that writes structured log entries (timestamp, level, component, message) to a file or stdout.
2. WHEN an LLM call is made THEN the system SHALL log the model name, prompt token count, and completion token count at DEBUG level.
3. WHEN a tool is invoked THEN the system SHALL log the tool name, input parameters, and the returned output at INFO level.
4. WHEN an error occurs THEN the system SHALL log the full exception details including stack trace at ERROR level.
5. WHEN a RAG retrieval is performed THEN the system SHALL log the query, the number of documents retrieved, and the document titles at DEBUG level.
6. WHERE logging is implemented THEN the system SHALL use Python's standard `logging` module or a compatible structured logging library, and SHALL NOT use bare `print` statements for observability.

---

### Requirement 20 — Rate Limiting

**User Story:** As a developer, I want to limit how frequently users can send messages, so that the system is protected from abuse and excessive API costs.

#### Acceptance Criteria

1. WHEN a user sends a message THEN the system SHALL check whether that user has exceeded the configured request rate limit (requests per minute or per hour) before forwarding the message to the backend.
2. IF a user exceeds the rate limit THEN the system SHALL return a rate-limit error message to the user and SHALL NOT forward the request to the LLM or any tool.
3. WHEN rate limiting is applied THEN the system SHALL implement it at the backend layer so that it is enforced regardless of the frontend used.
4. WHERE the rate limit thresholds are defined THEN the system SHALL read them from a configuration file or environment variables so they can be adjusted without code changes.

---

### Requirement 21 — Streamlit UI

**User Story:** As a user, I want a clean chat interface in my browser, so that I can have a natural conversation with the skincare assistant.

#### Acceptance Criteria

1. WHEN the Streamlit application loads THEN the system SHALL display a username input field and a submit button before entering the chat view.
2. WHEN the user is authenticated THEN the system SHALL display the full conversation history in a scrollable chat window using Streamlit's `st.chat_message` components.
3. WHEN the assistant returns a response THEN the Streamlit UI SHALL display the assistant message and, if citations are present, SHALL render the cited source document titles in a visually distinct section (e.g. an expandable "Sources" panel).
4. WHEN a tool is invoked during a response THEN the Streamlit UI SHALL display the tool name and a summary of its output in a visually distinct section (e.g. a "Tool Results" expander), satisfying the assignment requirement to show tool results.
5. WHILE the backend is processing a user message THEN the Streamlit UI SHALL display a loading indicator so that the user knows the system is working.
6. IF the backend returns an error THEN the Streamlit UI SHALL display a user-friendly error message and SHALL NOT expose internal error details.

---

### Requirement 22 — Non-Functional: Performance

**User Story:** As a user, I want responses to arrive within a reasonable time, so that the conversation feels responsive.

#### Acceptance Criteria

1. WHEN a user sends a message THEN the system SHALL return the first token of the assistant response (or display a loading indicator) within 3 seconds under normal operating conditions.
2. WHEN ChromaDB is initialised on startup THEN the system SHALL load the persistent vector store and be ready to serve requests within 10 seconds, assuming the embedding index already exists.

---

### Requirement 23 — Non-Functional: Configuration and Secrets Management

**User Story:** As a developer, I want all credentials and configurable parameters stored outside source code, so that the application is secure and portable across environments.

#### Acceptance Criteria

1. WHERE API keys (OpenRouter), database paths, ChromaDB directory, rate limit thresholds, and model names are used THEN the system SHALL read these values from environment variables or a `.env` file that is excluded from version control.
2. WHEN the application starts THEN the system SHALL validate that all required environment variables are present and SHALL fail fast with a clear error message if any are missing.
3. WHERE a `.env` file is used THEN the system SHALL include a `.env.example` file listing all required variables with placeholder values, committed to version control.

---

### Requirement 24 — Non-Functional: Domain Specialisation

**User Story:** As a user, I want the assistant to stay focused on skincare topics, so that it does not give off-topic advice.

#### Acceptance Criteria

1. WHEN a user asks a question outside the skincare domain THEN the system SHALL politely decline to answer and redirect the user to skincare-related topics.
2. WHERE the system prompt is defined THEN it SHALL explicitly constrain the assistant to skincare, routine building, ingredient advice, and men's grooming topics.
3. WHEN the assistant responds THEN it SHALL use terminology and framing appropriate for male skincare beginners, avoiding jargon where simpler language suffices.

---

### Requirement 25 — Non-Functional: Monorepo Project Structure

**User Story:** As a developer, I want the backend and frontend to be separated into distinct packages within the same repository, so that the frontend can be swapped for a different one without modifying any backend code.

#### Acceptance Criteria

1. WHERE the repository is organised THEN the system SHALL separate the backend and the frontend into distinct top-level packages within the same repository, such that each package has its own isolated dependency boundary.
2. WHERE the backend package is implemented THEN it SHALL contain zero imports from any frontend or presentation framework, so that it remains presentation-agnostic.
3. WHEN the frontend package is replaced or removed THEN the system SHALL continue to function at the backend level without any changes to backend code.
4. IF a different frontend implementation is mounted against the backend THEN the system SHALL serve it correctly through the same internal interface defined in Requirement 1, without modifications to the backend package.
5. WHERE the two packages share code or utilities THEN the system SHALL expose them through the backend's internal interface rather than through direct cross-package imports, maintaining the one-way dependency direction from frontend to backend.

---

### Requirement 26 — Non-Functional: Error Monitoring

**User Story:** As a developer, I want unhandled exceptions to be automatically reported to an external error monitoring service, so that I can detect and investigate production issues without manually trawling logs.

#### Acceptance Criteria

1. WHEN the application starts THEN the system SHALL attempt to initialise error monitoring by reading a DSN value from environment variables.
2. IF the DSN environment variable is set THEN the system SHALL activate error monitoring so that all unhandled exceptions are automatically captured and reported to the monitoring service.
3. IF the DSN environment variable is not set THEN the system SHALL log a warning, skip error monitoring initialisation, and continue starting up normally, so that the application runs without error monitoring in local development.
4. WHEN an unhandled exception propagates to the top-level boundary THEN the system SHALL report it to the monitoring service before returning a response or terminating, without requiring explicit per-exception instrumentation in each component.
5. WHERE error monitoring initialisation is performed THEN the system SHALL do so once at startup and SHALL NOT re-initialise on every request.
