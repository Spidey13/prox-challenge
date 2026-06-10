"""Pytest fixtures + path setup for the headless eval suite.

The agent (MiniLM + Chroma) is built once per session. ``sys.path`` is widened so
sibling modules (harness/graders/judge/report) and the repo root (agent/config)
import cleanly under pytest's prepend mode.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent          # tests/eval
_ROOT = _HERE.parent.parent                       # diagnostiq/
for p in (str(_HERE), str(_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

PRODUCT_ID = "trane_precedent"
GOLDEN_PATH = _HERE / "golden_set.json"


def load_cases() -> list[dict]:
    data = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    return data["cases"]


def pytest_configure(config):
    config.addinivalue_line("markers", "eval: Diagnostiq agent evaluation case")
    config.addinivalue_line("markers", "judge: case that invokes the LLM faithfulness judge")


@pytest.fixture(scope="session")
def agent():
    from config import config as cfg
    if not cfg.anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY not set — eval suite needs the live API")
    from agent import SupportAgent
    return SupportAgent()


@pytest.fixture(scope="session")
def judge_client(agent):
    # Reuse the agent's Anthropic client — no second connection.
    return agent._claude


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    import report
    if report.RESULTS:
        terminalreporter.write_line(report.render())
        # Persist trend history only for full runs — partial (-k) runs skew it.
        if len(report.RESULTS) >= max(1, len(load_cases()) // 2):
            report.save_history()
