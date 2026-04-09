"""Tests for the PRD Refiner Agent."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agents.prd_refiner.agent import (
    BOT_COMMENT_MARKER,
    LABEL_REFINING,
    LABEL_SPEC_READY,
    PRDRefinerAgent,
)
from agents.shared.llm.interface import LLMInterface
from agents.shared.platform.interface import PlatformInterface
from agents.shared.registry import Registry
from agents.shared.state import StateManager
from tests.conftest import make_issue


@pytest.fixture()
def mock_platform():
    return MagicMock(spec=PlatformInterface)


@pytest.fixture()
def mock_llm():
    return MagicMock(spec=LLMInterface)


@pytest.fixture()
def mock_registry():
    reg = MagicMock(spec=Registry)
    reg.all_services.return_value = []
    reg.build_context_summary.return_value = "No services registered."
    return reg


@pytest.fixture()
def mock_state_manager():
    return MagicMock(spec=StateManager)


@pytest.fixture()
def agent(mock_platform, mock_llm, mock_registry, mock_state_manager) -> PRDRefinerAgent:
    return PRDRefinerAgent(
        platform=mock_platform,
        llm=mock_llm,
        registry=mock_registry,
        state_manager=mock_state_manager,
        repo="org/ai-control-plane",
    )


class TestHandleEpicLabeled:
    def test_adds_refining_label_when_absent(
        self, agent, mock_platform, mock_llm, mock_state_manager
    ):
        issue = make_issue(number=1, labels=["epic"])
        mock_platform.read_issue.return_value = issue
        mock_state_manager.load.return_value = None
        mock_state_manager.create.return_value = MagicMock(status="refining")
        mock_llm.complete.return_value = "Here is my initial analysis."

        agent.handle_epic_labeled(1)

        mock_platform.add_label.assert_called_with("org/ai-control-plane", 1, LABEL_REFINING)

    def test_posts_bot_comment(self, agent, mock_platform, mock_llm, mock_state_manager):
        issue = make_issue(number=1, labels=["epic", "refining"])
        mock_platform.read_issue.return_value = issue
        mock_state_manager.load.return_value = MagicMock(status="refining")
        mock_llm.complete.return_value = "Initial questions from bot."

        agent.handle_epic_labeled(1)

        mock_platform.post_comment.assert_called_once()
        comment_body = mock_platform.post_comment.call_args.args[2]
        assert BOT_COMMENT_MARKER in comment_body
        assert "Initial questions from bot." in comment_body

    def test_creates_new_state_when_missing(
        self, agent, mock_platform, mock_llm, mock_state_manager
    ):
        issue = make_issue(number=5, labels=["epic"])
        mock_platform.read_issue.return_value = issue
        mock_state_manager.load.return_value = None
        mock_state_manager.create.return_value = MagicMock(status="refining")
        mock_llm.complete.return_value = "question"

        agent.handle_epic_labeled(5)

        mock_state_manager.create.assert_called_once_with(5, "org/ai-control-plane", issue.title)


class TestHandlePmComment:
    def test_skips_issue_without_refining_label(self, agent, mock_platform, mock_state_manager):
        issue = make_issue(number=2, labels=["epic"])
        mock_platform.read_issue.return_value = issue

        agent.handle_pm_comment(2)

        mock_platform.post_comment.assert_not_called()

    def test_asks_followup_question_when_spec_incomplete(
        self, agent, mock_platform, mock_llm, mock_state_manager
    ):
        issue = make_issue(
            number=3,
            labels=["epic", "refining"],
            comments=[{"author": "pm", "body": "We need async processing."}],
        )
        mock_platform.read_issue.return_value = issue
        mock_state_manager.load.return_value = MagicMock(status="refining")
        mock_llm.complete.return_value = "What is the expected batch size?"

        agent.handle_pm_comment(3)

        mock_platform.post_comment.assert_called_once()
        assert "spec-ready" not in [
            c.args[2] for c in mock_platform.add_label.call_args_list if len(c.args) > 2
        ]

    def test_finalises_spec_when_llm_returns_json(
        self, agent, mock_platform, mock_llm, mock_state_manager
    ):
        issue = make_issue(number=4, labels=["epic", "refining"], comments=[])
        mock_platform.read_issue.return_value = issue
        state_mock = MagicMock(status="refining")
        state_mock.spec = MagicMock()
        mock_state_manager.load.return_value = state_mock

        spec_json = {
            "status": "complete",
            "spec": {
                "acceptance_criteria": ["AC1"],
                "affected_services": ["svc-a"],
                "data_model_changes": [],
                "api_contract_changes": [],
                "edge_cases": [],
                "open_questions": [],
            },
            "summary": "All clear.",
        }
        mock_llm.complete.return_value = (
            f"Here is the complete spec:\n\n```json\n{json.dumps(spec_json)}\n```"
        )

        agent.handle_pm_comment(4)

        # Should remove refining and add spec-ready
        mock_platform.remove_label.assert_called_with("org/ai-control-plane", 4, LABEL_REFINING)
        mock_platform.add_label.assert_called_with("org/ai-control-plane", 4, LABEL_SPEC_READY)
        mock_state_manager.transition.assert_called_with(state_mock, "spec_ready")
