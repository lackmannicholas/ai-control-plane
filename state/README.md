# State Directory

This directory stores persistent orchestration state for active epics.
It is the source of truth for all agent operations; GitHub issue labels and
comments are derived views of this state, not the state itself.

## Directory Layout

```
state/
  epic_states/
    <epic_issue_number>.json    # One file per active epic
  dispatch_log.jsonl            # Append-only log of all dispatch operations
  failure_log.jsonl             # Append-only log of all failure events
```

## Epic State Schema

Each `epic_states/<issue_number>.json` file follows this structure:

```json
{
  "epic_id": 42,
  "repo": "lackmannicholas/ai-control-plane",
  "title": "Bulk lease renewals",
  "status": "refining | spec_ready | architect_planning | approved | dispatching | in_progress | completed | failed",
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z",
  "spec": {
    "acceptance_criteria": [],
    "affected_services": [],
    "data_model_changes": [],
    "api_contract_changes": [],
    "edge_cases": [],
    "open_questions": []
  },
  "execution_plan": {
    "contracts": [],
    "child_issues": [],
    "migration_flags": []
  },
  "dispatch_records": [
    {
      "key": "<epic_id>:<spoke_repo>:<task_hash>",
      "spoke_repo": "lackmannicholas/tenant-api",
      "issue_number": null,
      "status": "pending | created | failed",
      "created_at": null,
      "retry_count": 0
    }
  ],
  "spoke_statuses": {
    "lackmannicholas/tenant-api": {
      "child_issue_number": 45,
      "status": "pending | in_progress | completed | failed",
      "pr_number": null,
      "retry_count": 0,
      "last_updated": "2024-01-01T00:00:00Z"
    }
  }
}
```

## Dispatch Key Format

Dispatch operations are keyed by `<epic_id>:<spoke_repo>:<task_hash>` to
guarantee idempotency. Re-running dispatch skips any record whose key already
exists with `status: created`.

## Failure Modes Tracked

| Failure | Detection | State Field |
|---------|-----------|-------------|
| Spoke agent timeout | PR not opened within threshold | `spoke_statuses.<repo>.status = failed` |
| CI failure | Check suite conclusion | `spoke_statuses.<repo>.retry_count` incremented |
| Partial dispatch | Key mismatch in dispatch_records | Idempotent retry |
| Registry sync failure | Validation action fail | Recorded in `failure_log.jsonl` |
