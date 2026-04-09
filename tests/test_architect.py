"""Tests for the Architect Agent."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agents.architect.agent import (
    BOT_COMMENT_MARKER,
    LABEL_ARCHITECT_PLANNING,
    ArchitectAgent,
)
from agents.shared.llm.interface import LLMInterface
from agents.shared.platform.interface import PlatformInterface
from agents.shared.registry import Registry
from agents.shared.state import EpicSpec, EpicState, ExecutionPlan, StateManager
from tests.conftest import make_issue


def _make_state(epic_id: int = 1, status: str = "spec_ready") -> EpicState:
    state = EpicState(epic_id=epic_id, repo="org/hub", title="Epic")
    state.status = status
    state.spec = EpicSpec(affected_services=["svc-a"])
    state.execution_plan = ExecutionPlan()
    return state


@pytest.fixture()
def mock_platform():
    p = MagicMock(spec=PlatformInterface)
    return p


@pytest.fixture()
def mock_llm():
    return MagicMock(spec=LLMInterface)


@pytest.fixture()
def mock_registry():
    reg = MagicMock(spec=Registry)
    reg.all_services.return_value = []
    reg.build_context_summary.return_value = "svc-a: api service"
    return reg


@pytest.fixture()
def mock_state_manager():
    return MagicMock(spec=StateManager)


@pytest.fixture()
def agent(mock_platform, mock_llm, mock_registry, mock_state_manager) -> ArchitectAgent:
    return ArchitectAgent(
        platform=mock_platform,
        llm=mock_llm,
        registry=mock_registry,
        state_manager=mock_state_manager,
        repo="org/hub",
    )


def _plan_response(child_issues=None, contracts=None, migration_flags=None) -> str:
    plan = {
        "execution_plan": {
            "summary": "Test plan",
            "contracts": contracts or [],
            "child_issues": child_issues or [],
            "migration_flags": migration_flags or [],
        }
    }
    return f"Here is the plan:\n\n```json\n{json.dumps(plan)}\n```"


class TestHandleArchitectReady:
    def test_adds_architect_planning_label(
        self, agent, mock_platform, mock_llm, mock_state_manager
    ):
        issue = make_issue(number=1, labels=["architect-ready"])
        mock_platform.read_issue.return_value = issue
        state = _make_state(epic_id=1)
        mock_state_manager.load.return_value = state
        mock_llm.complete.return_value = _plan_response()

        agent.handle_architect_ready(1)

        mock_platform.add_label.assert_called_with("org/hub", 1, LABEL_ARCHITECT_PLANNING)

    def test_posts_execution_plan_comment(self, agent, mock_platform, mock_llm, mock_state_manager):
        issue = make_issue(number=1, labels=["architect-ready"])
        mock_platform.read_issue.return_value = issue
        state = _make_state(epic_id=1)
        mock_state_manager.load.return_value = state
        mock_llm.complete.return_value = _plan_response()

        agent.handle_architect_ready(1)

        mock_platform.post_comment.assert_called_once()
        comment = mock_platform.post_comment.call_args.args[2]
        assert BOT_COMMENT_MARKER in comment

    def test_aborts_when_no_state(self, agent, mock_platform, mock_llm, mock_state_manager):
        issue = make_issue(number=99, labels=["architect-ready"])
        mock_platform.read_issue.return_value = issue
        mock_state_manager.load.return_value = None

        agent.handle_architect_ready(99)

        mock_platform.post_comment.assert_not_called()


class TestHandleApprovedForDispatch:
    def test_dispatches_child_issues(self, agent, mock_platform, mock_llm, mock_state_manager):
        issue = make_issue(number=2, labels=["approved-for-dispatch"])
        mock_platform.read_issue.return_value = issue
        state = _make_state(epic_id=2, status="architect_planning")
        state.execution_plan.child_issues = [
            {
                "spoke_repo": "org/svc-a",
                "title": "Add bulk renewal endpoint",
                "body": "Body text",
                "labels": ["arch-task"],
            }
        ]
        mock_state_manager.load.return_value = state
        mock_state_manager.dispatch_key.return_value = "2:org/svc-a:abcdef"
        mock_state_manager.is_dispatched.return_value = False
        created_issue = make_issue(number=45, title="Add bulk renewal endpoint")
        mock_platform.create_issue.return_value = created_issue

        agent.handle_approved_for_dispatch(2)

        mock_platform.create_issue.assert_called_once_with(
            "org/svc-a",
            "Add bulk renewal endpoint",
            "Body text",
            ["arch-task"],
        )
        mock_state_manager.record_dispatch.assert_called_once()

    def test_skips_already_dispatched_issues(
        self, agent, mock_platform, mock_llm, mock_state_manager
    ):
        issue = make_issue(number=3, labels=["approved-for-dispatch"])
        mock_platform.read_issue.return_value = issue
        state = _make_state(epic_id=3, status="architect_planning")
        state.execution_plan.child_issues = [
            {"spoke_repo": "org/svc-a", "title": "Task", "body": "", "labels": []}
        ]
        mock_state_manager.load.return_value = state
        mock_state_manager.dispatch_key.return_value = "key-already-done"
        mock_state_manager.is_dispatched.return_value = True

        agent.handle_approved_for_dispatch(3)

        mock_platform.create_issue.assert_not_called()


class TestExtractPlan:
    def test_extracts_plan_from_json_block(self):
        response = _plan_response(
            child_issues=[{"spoke_repo": "org/x", "title": "Do X", "body": "", "labels": []}]
        )
        plan = ArchitectAgent._extract_plan(response)
        assert len(plan["child_issues"]) == 1

    def test_returns_empty_plan_when_no_json(self):
        plan = ArchitectAgent._extract_plan("No JSON here, just text.")
        assert plan["child_issues"] == []
        assert plan["contracts"] == []
