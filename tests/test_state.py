"""Tests for the state manager."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.shared.state import (
    StateManager,
)


@pytest.fixture()
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    (d / "epic_states").mkdir()
    (d / "dispatch_log.jsonl").touch()
    (d / "failure_log.jsonl").touch()
    return d


@pytest.fixture()
def manager(state_dir: Path) -> StateManager:
    return StateManager(state_dir=state_dir)


class TestStateManagerCreate:
    def test_creates_json_file(self, manager: StateManager, state_dir: Path):
        manager.create(42, "org/repo", "My epic")
        path = state_dir / "epic_states" / "42.json"
        assert path.exists()

    def test_initial_status_is_refining(self, manager: StateManager):
        state = manager.create(1, "org/repo", "Epic")
        assert state.status == "refining"

    def test_load_returns_created_state(self, manager: StateManager):
        manager.create(7, "org/repo", "Epic 7")
        loaded = manager.load(7)
        assert loaded is not None
        assert loaded.epic_id == 7
        assert loaded.title == "Epic 7"

    def test_load_nonexistent_returns_none(self, manager: StateManager):
        assert manager.load(999) is None


class TestStateManagerTransition:
    def test_valid_transition(self, manager: StateManager):
        state = manager.create(1, "org/repo", "Epic")
        manager.transition(state, "spec_ready")
        assert state.status == "spec_ready"

    def test_invalid_transition_raises(self, manager: StateManager):
        state = manager.create(1, "org/repo", "Epic")
        with pytest.raises(ValueError, match="Cannot transition"):
            manager.transition(state, "in_progress")

    def test_transition_persists_to_disk(self, manager: StateManager, state_dir: Path):
        state = manager.create(2, "org/repo", "Epic 2")
        manager.transition(state, "spec_ready")
        loaded = manager.load(2)
        assert loaded is not None
        assert loaded.status == "spec_ready"


class TestStateManagerDispatch:
    def test_dispatch_key_is_stable(self, manager: StateManager):
        k1 = manager.dispatch_key(1, "org/svc", "Implement X")
        k2 = manager.dispatch_key(1, "org/svc", "Implement X")
        assert k1 == k2

    def test_dispatch_key_differs_for_different_tasks(self, manager: StateManager):
        k1 = manager.dispatch_key(1, "org/svc", "Task A")
        k2 = manager.dispatch_key(1, "org/svc", "Task B")
        assert k1 != k2

    def test_is_dispatched_false_before_record(self, manager: StateManager):
        state = manager.create(3, "org/repo", "Epic 3")
        key = manager.dispatch_key(3, "org/svc", "Task")
        assert not manager.is_dispatched(state, key)

    def test_is_dispatched_true_after_record(self, manager: StateManager):
        state = manager.create(3, "org/repo", "Epic 3")
        manager.record_dispatch(state, "org/svc", "Task", issue_number=10)
        key = manager.dispatch_key(3, "org/svc", "Task")
        assert manager.is_dispatched(state, key)

    def test_record_dispatch_appends_to_dispatch_log(self, manager: StateManager, state_dir: Path):
        state = manager.create(4, "org/repo", "Epic 4")
        manager.record_dispatch(state, "org/svc", "Task", issue_number=99)
        log_lines = (state_dir / "dispatch_log.jsonl").read_text().strip().split("\n")
        assert len(log_lines) == 1
        record = json.loads(log_lines[0])
        assert record["issue_number"] == 99
        assert record["spoke_repo"] == "org/svc"

    def test_idempotent_dispatch_does_not_duplicate(self, manager: StateManager):
        state = manager.create(5, "org/repo", "Epic 5")
        manager.record_dispatch(state, "org/svc", "Task", issue_number=11)
        manager.record_dispatch(state, "org/svc", "Task", issue_number=11)
        key = manager.dispatch_key(5, "org/svc", "Task")
        matching = [r for r in state.dispatch_records if r.key == key]
        assert len(matching) == 1


class TestStateManagerFailureLog:
    def test_record_failure_appends_to_log(self, manager: StateManager, state_dir: Path):
        manager.create(6, "org/repo", "Epic 6")
        manager.record_failure(6, "Something went wrong", {"detail": "timeout"})
        lines = (state_dir / "failure_log.jsonl").read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["epic_id"] == 6
        assert entry["message"] == "Something went wrong"
        assert entry["context"]["detail"] == "timeout"
