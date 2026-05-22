"""RAGAs evaluation script for the Skincare Routine Builder RAG pipeline.

Usage:
    python scripts/eval_rag.py

Loads data/eval_dataset.json, calls BackendService on each question,
maps reference_contexts to KB document text, then computes RAGAs metrics:
  faithfulness, answer_relevancy, context_precision, context_recall.

Prints a results table to stdout and saves data/eval_results.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EVAL_DATASET_PATH = ROOT / "eval" / "eval_dataset.json"
EVAL_RESULTS_PATH = ROOT / "data" / "eval_results.json"
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


def run_evaluation(dataset: list[dict], service) -> tuple[list, list, list, list]:
    """Call BackendService for each question; return parallel lists for ragas."""
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
    # max_tokens=4096 avoids truncation on long contexts (default 1024 is too small)
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

    # Wire the OpenRouter LLM into each metric singleton
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


def main() -> None:
    print("=== RAGAs Evaluation — Skincare Routine Builder ===\n")

    dataset = load_eval_dataset()
    print(f"Loaded {len(dataset)} eval examples from {EVAL_DATASET_PATH}\n")

    from backend.agent import BackendService

    service = BackendService()
    print("Running BackendService on each question …")
    questions, answers, contexts, ground_truths = run_evaluation(dataset, service)

    print("\nComputing RAGAs metrics …")
    result = compute_ragas_metrics(questions, answers, contexts, ground_truths)

    print("\n=== Results ===")
    df = result.to_pandas()
    metric_cols = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    scores: dict[str, float] = {}
    for col in metric_cols:
        if col in df.columns:
            val = float(df[col].mean())
        else:
            val = float("nan")
        scores[col] = val
        print(f"  {col:<25} {val:.4f}")

    EVAL_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(EVAL_RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(scores, f, indent=2)
    print(f"\nFull results saved to {EVAL_RESULTS_PATH}")


if __name__ == "__main__":
    main()
