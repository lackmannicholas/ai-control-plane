"""Orchestration state manager.

Reads and writes persistent JSON state for active epics in ``state/``.
All mutations are atomic (write-to-tmp then rename) to avoid partial writes.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _task_hash(spoke_repo: str, title: str) -> str:
    """Stable, short hash for a (spoke_repo, task_title) pair."""
    raw = f"{spoke_repo}:{title}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


@dataclass
class DispatchRecord:
    key: str
    spoke_repo: str
    issue_number: int | None = None
    status: str = "pending"  # pending | created | failed
    created_at: str | None = None
    retry_count: int = 0


@dataclass
class SpokeStatus:
    child_issue_number: int | None = None
    status: str = "pending"  # pending | in_progress | completed | failed
    pr_number: int | None = None
    retry_count: int = 0
    last_updated: str = field(default_factory=_now_iso)


@dataclass
class EpicSpec:
    acceptance_criteria: list[str] = field(default_factory=list)
    affected_services: list[str] = field(default_factory=list)
    data_model_changes: list[str] = field(default_factory=list)
    api_contract_changes: list[str] = field(default_factory=list)
    edge_cases: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)


@dataclass
class ExecutionPlan:
    contracts: list[dict[str, Any]] = field(default_factory=list)
    child_issues: list[dict[str, Any]] = field(default_factory=list)
    migration_flags: list[str] = field(default_factory=list)


@dataclass
class EpicState:
    epic_id: int
    repo: str
    title: str
    status: str = "refining"
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    spec: EpicSpec = field(default_factory=EpicSpec)
    execution_plan: ExecutionPlan = field(default_factory=ExecutionPlan)
    dispatch_records: list[DispatchRecord] = field(default_factory=list)
    spoke_statuses: dict[str, SpokeStatus] = field(default_factory=dict)


# Valid status transitions
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "refining": {"spec_ready", "failed"},
    "spec_ready": {"architect_planning", "refining", "failed"},
    "architect_planning": {"approved", "spec_ready", "failed"},
    "approved": {"dispatching", "architect_planning", "failed"},
    "dispatching": {"in_progress", "failed"},
    "in_progress": {"completed", "failed"},
    "completed": set(),
    "failed": {"refining", "architect_planning"},
}


class StateManager:
    """Manages persistent epic state stored under *state_dir*.

    Args:
        state_dir: Root directory for state files. Defaults to the canonical
                   ``state/`` directory at repository root.
    """

    def __init__(self, state_dir: str | Path | None = None) -> None:
        if state_dir is None:
            state_dir = Path(__file__).parents[2] / "state"
        self._state_dir = Path(state_dir)
        self._epics_dir = self._state_dir / "epic_states"
        self._dispatch_log = self._state_dir / "dispatch_log.jsonl"
        self._failure_log = self._state_dir / "failure_log.jsonl"
        self._epics_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_dict(state: EpicState) -> dict[str, Any]:
        d = asdict(state)
        d["spoke_statuses"] = {k: asdict(v) for k, v in state.spoke_statuses.items()}
        return d

    @staticmethod
    def _from_dict(data: dict[str, Any]) -> EpicState:
        data = dict(data)
        data["spec"] = EpicSpec(**data.get("spec", {}))
        data["execution_plan"] = ExecutionPlan(**data.get("execution_plan", {}))
        data["dispatch_records"] = [DispatchRecord(**r) for r in data.get("dispatch_records", [])]
        data["spoke_statuses"] = {k: SpokeStatus(**v) for k, v in data.get("spoke_statuses", {}).items()}
        return EpicState(**data)

    # ------------------------------------------------------------------
    # Atomic file I/O
    # ------------------------------------------------------------------

    def _path_for(self, epic_id: int) -> Path:
        return self._epics_dir / f"{epic_id}.json"

    def _write(self, state: EpicState) -> None:
        path = self._path_for(state.epic_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._to_dict(state), indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _append_log(self, log_path: Path, record: dict[str, Any]) -> None:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, epic_id: int) -> EpicState | None:
        """Return the state for *epic_id*, or ``None`` if not found."""
        path = self._path_for(epic_id)
        if not path.exists():
            return None
        return self._from_dict(json.loads(path.read_text(encoding="utf-8")))

    def create(self, epic_id: int, repo: str, title: str) -> EpicState:
        """Create and persist a new EpicState."""
        state = EpicState(epic_id=epic_id, repo=repo, title=title)
        self._write(state)
        return state

    def save(self, state: EpicState) -> None:
        """Persist *state* to disk."""
        state.updated_at = _now_iso()
        self._write(state)

    def transition(self, state: EpicState, new_status: str) -> None:
        """Transition *state* to *new_status*, raising ValueError if invalid."""
        allowed = _VALID_TRANSITIONS.get(state.status, set())
        if new_status not in allowed:
            raise ValueError(f"Cannot transition epic {state.epic_id} from " f"'{state.status}' to '{new_status}'. " f"Allowed: {allowed}")
        state.status = new_status
        self.save(state)

    def record_failure(
        self,
        epic_id: int,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Append a failure event to the failure log."""
        self._append_log(
            self._failure_log,
            {
                "epic_id": epic_id,
                "timestamp": _now_iso(),
                "message": message,
                "context": context or {},
            },
        )

    # ------------------------------------------------------------------
    # Idempotent dispatch
    # ------------------------------------------------------------------

    def dispatch_key(self, epic_id: int, spoke_repo: str, task_title: str) -> str:
        """Return a stable idempotency key for this dispatch operation."""
        h = _task_hash(spoke_repo, task_title)
        return f"{epic_id}:{spoke_repo}:{h}"

    def is_dispatched(self, state: EpicState, key: str) -> bool:
        """Return ``True`` if *key* has already been dispatched successfully."""
        return any(r.key == key and r.status == "created" for r in state.dispatch_records)

    def record_dispatch(
        self,
        state: EpicState,
        spoke_repo: str,
        task_title: str,
        issue_number: int,
    ) -> None:
        """Record a successful dispatch; append to dispatch log."""
        key = self.dispatch_key(state.epic_id, spoke_repo, task_title)
        record = DispatchRecord(
            key=key,
            spoke_repo=spoke_repo,
            issue_number=issue_number,
            status="created",
            created_at=_now_iso(),
        )
        # Remove any existing pending record for the same key
        state.dispatch_records = [r for r in state.dispatch_records if r.key != key]
        state.dispatch_records.append(record)
        self.save(state)
        self._append_log(
            self._dispatch_log,
            {
                "key": key,
                "epic_id": state.epic_id,
                "spoke_repo": spoke_repo,
                "issue_number": issue_number,
                "timestamp": _now_iso(),
            },
        )
