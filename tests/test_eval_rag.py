"""Unit tests for scripts/eval_rag.py (TB2).

Mocks BackendService.run so the script can be exercised without live LLM calls
or the Chroma vector store.
"""

from __future__ import annotations

import json
import pandas as pd
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scripts.eval_rag as eval_rag
from backend.schemas import BackendResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_DATASET = [
    {
        "question": "Is niacinamide safe with retinol?",
        "ground_truth_answer": "Yes, niacinamide and retinol are safe together.",
        "reference_contexts": ["Niacinamide Profile", "Retinol Profile"],
    },
    {
        "question": "What SPF should I use?",
        "ground_truth_answer": "Use at least SPF 30 daily.",
        "reference_contexts": ["SPF Actives Guide"],
    },
]


def _fake_service(answers: list[str] | None = None) -> MagicMock:
    """Return a mock BackendService whose run() cycles through given answers."""
    if answers is None:
        answers = ["Mocked answer."] * 20
    svc = MagicMock()
    svc.run.side_effect = [
        BackendResponse(message=a, citations=[], tool_results=[], error=False)
        for a in answers
    ]
    return svc


# ---------------------------------------------------------------------------
# load_eval_dataset
# ---------------------------------------------------------------------------

class TestLoadEvalDataset:
    def test_loads_real_dataset(self):
        data = eval_rag.load_eval_dataset()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "question" in data[0]
        assert "ground_truth_answer" in data[0]
        assert "reference_contexts" in data[0]

    def test_raises_if_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(eval_rag, "EVAL_DATASET_PATH", tmp_path / "no_such_file.json")
        with pytest.raises(FileNotFoundError):
            eval_rag.load_eval_dataset()


# ---------------------------------------------------------------------------
# run_evaluation
# ---------------------------------------------------------------------------

class TestRunEvaluation:
    def test_returns_four_parallel_lists(self):
        svc = _fake_service(["Answer A.", "Answer B."])
        qs, ans, ctx, gts = eval_rag.run_agent_evaluation(_FAKE_DATASET, svc)

        assert len(qs) == len(_FAKE_DATASET)
        assert len(ans) == len(_FAKE_DATASET)
        assert len(ctx) == len(_FAKE_DATASET)
        assert len(gts) == len(_FAKE_DATASET)

    def test_questions_match_dataset(self):
        svc = _fake_service()
        qs, _, _, _ = eval_rag.run_agent_evaluation(_FAKE_DATASET, svc)
        assert qs[0] == _FAKE_DATASET[0]["question"]
        assert qs[1] == _FAKE_DATASET[1]["question"]

    def test_ground_truths_match_dataset(self):
        svc = _fake_service()
        _, _, _, gts = eval_rag.run_agent_evaluation(_FAKE_DATASET, svc)
        assert gts[0] == _FAKE_DATASET[0]["ground_truth_answer"]

    def test_answers_come_from_service(self):
        svc = _fake_service(["Custom answer 1.", "Custom answer 2."])
        _, ans, _, _ = eval_rag.run_agent_evaluation(_FAKE_DATASET, svc)
        assert ans[0] == "Custom answer 1."
        assert ans[1] == "Custom answer 2."

    def test_service_called_once_per_entry(self):
        svc = _fake_service()
        eval_rag.run_agent_evaluation(_FAKE_DATASET, svc)
        assert svc.run.call_count == len(_FAKE_DATASET)

    def test_contexts_are_lists_of_strings(self):
        svc = _fake_service()
        _, _, ctx, _ = eval_rag.run_agent_evaluation(_FAKE_DATASET, svc)
        for c in ctx:
            assert isinstance(c, list)
            assert all(isinstance(s, str) for s in c)


# ---------------------------------------------------------------------------
# compute_ragas_metrics — smoke test with mocked ragas
# ---------------------------------------------------------------------------

class TestComputeRagasMetrics:
    def test_runs_to_completion_without_raising(self):
        """The function must complete without raising, even with trivial data."""
        fake_result = {"faithfulness": 0.8, "answer_relevancy": 0.9}

        # evaluate is imported lazily inside compute_ragas_metrics, so patch at source
        with patch("ragas.evaluate", return_value=fake_result) as mock_eval:
            result = eval_rag.compute_ragas_metrics(
                questions=["Q1", "Q2"],
                answers=["A1", "A2"],
                contexts=[["ctx1"], ["ctx2"]],
                ground_truths=["GT1", "GT2"],
            )
        mock_eval.assert_called_once()
        assert result == fake_result

    def test_returns_dict_like_object(self):
        fake_result = {"faithfulness": 0.75}
        with patch("ragas.evaluate", return_value=fake_result):
            result = eval_rag.compute_ragas_metrics(["Q"], ["A"], [["ctx"]], ["GT"])
        assert "faithfulness" in result


# ---------------------------------------------------------------------------
# main — integration smoke test
# ---------------------------------------------------------------------------

class TestMain:
    def test_main_runs_without_raising(self, tmp_path, monkeypatch):
        """main() must complete without raising when BackendService and ragas are mocked."""
        monkeypatch.setattr(eval_rag, "EVAL_RESULTS_AGENT_PATH", tmp_path / "eval_results_agent.json")
        monkeypatch.setattr(eval_rag, "EVAL_RESULTS_RETRIEVER_PATH", tmp_path / "eval_results_retriever.json")

        scores = {
            "faithfulness": 0.9,
            "answer_relevancy": 0.85,
            "context_precision": 0.8,
            "context_recall": 0.88,
        }
        fake_ragas_result = MagicMock()
        fake_ragas_result.to_pandas.return_value = pd.DataFrame([scores])

        svc = _fake_service(["Mocked answer."] * 20)

        with (
            patch("backend.agent.BackendService", return_value=svc),
            patch("ragas.evaluate", return_value=fake_ragas_result),
            patch("backend.logging_config.setup_logging"),
            patch("backend.logging_config.init_langsmith"),
            patch("scripts.index_kb.main"),
            patch("backend.db.profile_store.ProfileStore"),
        ):
            eval_rag.main()

        results_path = tmp_path / "eval_results_agent.json"
        assert results_path.exists()
        saved = json.loads(results_path.read_text())
        assert "faithfulness" in saved
        assert abs(saved["faithfulness"] - 0.9) < 1e-6
