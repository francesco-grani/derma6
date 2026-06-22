"""Root conftest.py — loaded by pytest for every run regardless of which directory is targeted.

Registers custom CLI options and collection hooks that must be available globally.
"""

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-eval",
        action="store_true",
        default=False,
        help="Run deepeval LLM quality evaluations (requires live OPENROUTER_API_KEY)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if not config.getoption("--run-eval"):
        skip_eval = pytest.mark.skip(reason="pass --run-eval to run deepeval tests")
        for item in items:
            if "eval" in item.keywords:
                item.add_marker(skip_eval)
