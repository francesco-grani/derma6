"""RAGAs evaluation script for the Derma6 RAG pipeline.

Two evaluation modes:

  Agent mode (default):
    Calls BackendService end-to-end. The agent decides whether to use tools.
    Measures overall system quality but may skip retrieval for questions
    the LLM already knows from training data.

  Retriever mode (--retriever):
    Bypasses the agent. For each question the retriever is called directly,
    then the LLM is prompted with the retrieved chunks as context.
    Guarantees retrieval happens on every question — a clean measure of
    RAG pipeline quality independent of agent tool-calling behaviour.

Usage:
    python scripts/eval_rag.py              # agent mode
    python scripts/eval_rag.py --retriever  # retriever mode

Results are saved to:
  data/eval_results_agent.json
  data/eval_results_retriever.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EVAL_DATASET_PATH = ROOT / "eval" / "eval_dataset.json"
EVAL_RESULTS_AGENT_PATH = ROOT / "data" / "eval_results_agent.json"
EVAL_RESULTS_RETRIEVER_PATH = ROOT / "data" / "eval_results_retriever.json"
KB_ROOT = ROOT / "knowledge_base"
TEST_USERNAME = "ragas_eval_bot"

# Map source names (as they appear in eval_dataset.json) to KB file paths
_KB_SOURCE_MAP: dict[str, Path] = {
    "AHA Guide": KB_ROOT / "ingredients" / "aha_guide.md",
    "BHA Guide": KB_ROOT / "ingredients" / "bha_guide.md",
    "Beginner 3-Step Routine for Men": KB_ROOT / "mens" / "beginner_3step_routine.md",
    "Benzoyl Peroxide Profile": KB_ROOT / "ingredients" / "benzoyl_peroxide.md",
    "Ingredient Irritancy Reference": KB_ROOT / "guides" / "ingredient_irritancy_reference.md",
    "Introduction Schedule Framework": KB_ROOT / "guides" / "introduction_schedule_framework.md",
    "Niacinamide Profile": KB_ROOT / "ingredients" / "niacinamide.md",
    "Razor Burn and Post-Shave Barrier Repair": KB_ROOT / "mens" / "razor_burn_and_post_shave.md",
    "Retinol Profile": KB_ROOT / "ingredients" / "retinol.md",
    "Routine Sequencing Rules": KB_ROOT / "guides" / "routine_sequencing_rules.md",
    "SPF Actives Guide": KB_ROOT / "ingredients" / "spf_actives.md",
    "Shaving Physiology": KB_ROOT / "mens" / "shaving_physiology.md",
    "Skin Concerns Overview": KB_ROOT / "guides" / "skin_concerns_overview.md",
    "Skin Type Classification Guide": KB_ROOT / "guides" / "skin_type_classification.md",
    "Vitamin C Profile": KB_ROOT / "ingredients" / "vitamin_c.md",
    "Azelaic Acid Profile": KB_ROOT / "ingredients" / "azelaic_acid.md",
    "Ceramides Guide": KB_ROOT / "ingredients" / "ceramides.md",
    "Hyaluronic Acid Profile": KB_ROOT / "ingredients" / "hyaluronic_acid.md",
    "Peptides Guide": KB_ROOT / "ingredients" / "peptides.md",
}


def _load_kb_text(source_names: list[str]) -> list[str]:
    """Return the text of each KB document referenced by source_names."""
    texts: list[str] = []
    for name in source_names:
        path = _KB_SOURCE_MAP.get(name)
        if path and path.exists():
            texts.append(path.read_text(encoding="utf-8"))
        else:
            texts.append(name)  # fallback: just the source name
    return texts


def load_eval_dataset() -> list[dict]:
    if not EVAL_DATASET_PATH.exists():
        raise FileNotFoundError(f"Eval dataset not found: {EVAL_DATASET_PATH}")
    with open(EVAL_DATASET_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Agent mode
# ---------------------------------------------------------------------------

def run_agent_evaluation(dataset: list[dict], service) -> tuple[list, list, list, list]:
    """Call BackendService end-to-end for each question.

    The agent decides whether to invoke kb_search. Contexts passed to RAGAS
    are the reference KB documents (not what the agent actually retrieved),
    so faithfulness measures whether the answer aligns with the authoritative
    source regardless of whether the agent used it.
    """
    from backend.schemas import BackendRequest

    questions: list[str] = []
    answers: list[str] = []
    contexts: list[list[str]] = []
    ground_truths: list[str] = []

    for i, entry in enumerate(dataset, 1):
        q = entry["question"]
        gt = entry["ground_truth_answer"]
        ref_contexts = entry.get("reference_contexts", [])
        ctx_texts = _load_kb_text(ref_contexts)

        print(f"  [{i}/{len(dataset)}] {q[:70]}")
        request = BackendRequest(username=TEST_USERNAME, message=q)
        response = service.run(request)

        questions.append(q)
        answers.append(response.message)
        contexts.append(ctx_texts)
        ground_truths.append(gt)

    return questions, answers, contexts, ground_truths


# ---------------------------------------------------------------------------
# Retriever mode
# ---------------------------------------------------------------------------

def run_retriever_evaluation(dataset: list[dict]) -> tuple[list, list, list, list]:
    """Bypass the agent: query the retriever directly, then call the LLM.

    For each question:
      1. Retrieve top-k chunks from ChromaDB.
      2. Prompt the LLM with the retrieved chunks as context.
      3. Pass the *retrieved* chunks (not the reference KB docs) to RAGAS
         as contexts — this is what RAGAS was designed to evaluate.

    This guarantees retrieval happens on every question and gives a clean
    measure of pipeline quality independent of agent tool-calling behaviour.
    """
    from langchain_openai import ChatOpenAI

    from backend.config import settings
    from backend.rag.retriever import Retriever

    retriever = Retriever()
    llm = ChatOpenAI(
        model=settings.llm_model,
        openai_api_key=settings.openrouter_api_key,
        openai_api_base=settings.openrouter_base_url,
        temperature=0.3,
    )

    system = (
        "You are a skincare assistant. Answer the question using ONLY the provided "
        "context. If the context does not contain enough information, say so briefly."
    )

    questions: list[str] = []
    answers: list[str] = []
    contexts: list[list[str]] = []
    ground_truths: list[str] = []

    for i, entry in enumerate(dataset, 1):
        q = entry["question"]
        gt = entry["ground_truth_answer"]

        print(f"  [{i}/{len(dataset)}] {q[:70]}")

        docs = retriever.query(q)
        retrieved_chunks = [d.content for d in docs]
        context_block = "\n\n---\n\n".join(retrieved_chunks) if retrieved_chunks else "No relevant context found."

        from langchain_core.messages import HumanMessage, SystemMessage
        response = llm.invoke([
            SystemMessage(content=system),
            HumanMessage(content=f"Context:\n{context_block}\n\nQuestion: {q}"),
        ])
        answer = response.content if hasattr(response, "content") else str(response)

        questions.append(q)
        answers.append(answer)
        contexts.append(retrieved_chunks if retrieved_chunks else [context_block])
        ground_truths.append(gt)

    return questions, answers, contexts, ground_truths


# ---------------------------------------------------------------------------
# RAGAS metrics
# ---------------------------------------------------------------------------

def _build_ragas_llm_and_embeddings():
    """Return (ragas_llm, ragas_embeddings) wired to the project's OpenRouter key."""
    from openai import OpenAI
    from ragas.embeddings.base import LangchainEmbeddingsWrapper
    from ragas.llms.base import llm_factory

    from backend.config import settings

    try:
        from langchain_openai import OpenAIEmbeddings as LCEmbeddings
    except ImportError:
        from langchain_community.embeddings import OpenAIEmbeddings as LCEmbeddings  # type: ignore[no-redef]

    client = OpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
    )
    llm = llm_factory(settings.llm_model, provider="openai", client=client, max_tokens=4096)
    lc_emb = LCEmbeddings(
        openai_api_key=settings.openrouter_api_key,
        openai_api_base=settings.openrouter_base_url,
        model="text-embedding-3-small",
    )
    emb = LangchainEmbeddingsWrapper(lc_emb)
    return llm, emb


def compute_ragas_metrics(
    questions: list[str],
    answers: list[str],
    contexts: list[list[str]],
    ground_truths: list[str],
):
    """Build a HuggingFace Dataset and run ragas evaluate."""
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics._answer_relevance import answer_relevancy
    from ragas.metrics._context_precision import context_precision
    from ragas.metrics._context_recall import context_recall
    from ragas.metrics._faithfulness import faithfulness

    llm, emb = _build_ragas_llm_and_embeddings()

    for m in [faithfulness, context_precision, context_recall]:
        m.llm = llm
    answer_relevancy.llm = llm
    answer_relevancy.embeddings = emb

    hf_dataset = Dataset.from_dict(
        {
            "question": questions,
            "answer": answers,
            "contexts": contexts,
            "ground_truth": ground_truths,
        }
    )

    return evaluate(
        dataset=hf_dataset,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        raise_exceptions=False,
        show_progress=True,
    )


def _print_and_save(result, output_path: Path) -> dict[str, float]:
    df = result.to_pandas()
    metric_cols = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    scores: dict[str, float] = {}
    for col in metric_cols:
        val = float(df[col].mean()) if col in df.columns else float("nan")
        scores[col] = val
        print(f"  {col:<25} {val:.4f}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(scores, f, indent=2)
    print(f"\nSaved to {output_path}")
    return scores


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    retriever_mode = "--retriever" in sys.argv

    print("=== RAGAs Evaluation — Derma6 ===")
    print(f"Mode: {'retriever (direct)' if retriever_mode else 'agent (end-to-end)'}\n")

    from backend.logging_config import init_langsmith, setup_logging
    setup_logging()
    init_langsmith()

    from scripts.index_kb import main as _index_kb
    _index_kb()
    print("Knowledge base indexed.\n")

    dataset = load_eval_dataset()
    print(f"Loaded {len(dataset)} eval examples from {EVAL_DATASET_PATH}\n")

    if retriever_mode:
        print("Querying retriever directly for each question …")
        questions, answers, contexts, ground_truths = run_retriever_evaluation(dataset)
        output_path = EVAL_RESULTS_RETRIEVER_PATH
    else:
        from backend.agent import BackendService
        from backend.db.profile_store import ProfileStore

        store = ProfileStore()
        store.get_or_create_user(TEST_USERNAME)
        store.update_skin_type(TEST_USERNAME, "normal")
        store.update_skin_concerns(TEST_USERNAME, ["general skincare"])
        store.update_has_shaving_routine(TEST_USERNAME, False)
        print(f"Eval profile seeded for '{TEST_USERNAME}' (onboarding bypassed)\n")

        service = BackendService()
        print("Running BackendService on each question …")
        questions, answers, contexts, ground_truths = run_agent_evaluation(dataset, service)
        output_path = EVAL_RESULTS_AGENT_PATH

    print("\nComputing RAGAs metrics …")
    result = compute_ragas_metrics(questions, answers, contexts, ground_truths)

    print("\n=== Results ===")
    _print_and_save(result, output_path)


if __name__ == "__main__":
    main()
