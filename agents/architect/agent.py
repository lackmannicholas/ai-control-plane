"""Architect Agent.

Triggered by GitHub Actions on:
  - ``issues`` ``labeled`` with ``architect-ready``  → begin planning
  - ``issues`` ``labeled`` with ``approved-for-dispatch`` → dispatch child issues
  - ``issue_comment`` ``created`` on issue with ``architect-planning`` label
    → incorporate feedback and revise plan
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from agents.architect.prompts import (
    EXECUTION_PLAN_COMMENT,
    PLANNING_PROMPT,
    REVISION_PROMPT,
    SYSTEM_PROMPT,
)
from agents.shared.llm.interface import LLMInterface, Message
from agents.shared.platform.interface import Issue, PlatformInterface
from agents.shared.registry import Registry
from agents.shared.state import EpicState, StateManager

logger = logging.getLogger(__name__)

# Label constants
LABEL_ARCHITECT_READY = "architect-ready"
LABEL_ARCHITECT_PLANNING = "architect-planning"
LABEL_APPROVED_FOR_DISPATCH = "approved-for-dispatch"
LABEL_DISPATCHING = "dispatching"

# Marker used to identify bot comments
BOT_COMMENT_MARKER = "<!-- architect-bot -->"


class ArchitectAgent:
    """Orchestrates the architecture planning and dispatch phases.

    Args:
        platform: Concrete platform adapter.
        llm: Concrete LLM adapter.
        registry: Loaded service registry.
        state_manager: Persistent state manager.
        repo: ``owner/repo`` of the hub repository.
        bot_login: GitHub login of the bot account.
    """

    def __init__(
        self,
        platform: PlatformInterface,
        llm: LLMInterface,
        registry: Registry,
        state_manager: StateManager,
        repo: str,
        bot_login: str = "github-actions[bot]",
    ) -> None:
        self._platform = platform
        self._llm = llm
        self._registry = registry
        self._state = state_manager
        self._repo = repo
        self._bot_login = bot_login

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    def handle_architect_ready(self, issue_number: int) -> None:
        """Called when ``architect-ready`` label is applied by an engineer."""
        issue = self._platform.read_issue(self._repo, issue_number)
        logger.info("Architect planning started for epic #%d: %s", issue_number, issue.title)

        state = self._state.load(issue_number)
        if state is None:
            logger.error("No state found for epic #%d; aborting.", issue_number)
            return

        self._platform.add_label(self._repo, issue_number, LABEL_ARCHITECT_PLANNING)

        plan = self._generate_plan(issue, state)
        state.execution_plan.contracts = plan.get("contracts", [])
        state.execution_plan.child_issues = plan.get("child_issues", [])
        state.execution_plan.migration_flags = [f.get("description", "") for f in plan.get("migration_flags", [])]
        self._state.transition(state, "architect_planning")

        self._post_execution_plan(issue_number, plan)

    def handle_engineer_feedback(self, issue_number: int) -> None:
        """Called when an engineer comments on an architect-planning issue."""
        issue = self._platform.read_issue(self._repo, issue_number)

        if LABEL_ARCHITECT_PLANNING not in issue.labels:
            return

        state = self._state.load(issue_number)
        if state is None:
            return

        original_plan = {
            "contracts": state.execution_plan.contracts,
            "child_issues": state.execution_plan.child_issues,
            "migration_flags": state.execution_plan.migration_flags,
        }
        feedback = self._extract_latest_engineer_comment(issue)
        revised_plan = self._revise_plan(issue, state, original_plan, feedback)

        state.execution_plan.contracts = revised_plan.get("contracts", [])
        state.execution_plan.child_issues = revised_plan.get("child_issues", [])
        state.execution_plan.migration_flags = [f.get("description", "") if isinstance(f, dict) else f for f in revised_plan.get("migration_flags", [])]
        self._state.save(state)
        self._post_execution_plan(issue_number, revised_plan)

    def handle_approved_for_dispatch(self, issue_number: int) -> None:
        """Called when ``approved-for-dispatch`` label is applied by an engineer."""
        self._platform.read_issue(self._repo, issue_number)
        logger.info("Dispatching child issues for epic #%d", issue_number)

        state = self._state.load(issue_number)
        if state is None:
            logger.error("No state found for epic #%d; aborting dispatch.", issue_number)
            return

        # Support retries: skip transitions that have already been applied.
        if state.status not in ("approved", "dispatching"):
            self._state.transition(state, "approved")
        self._platform.add_label(self._repo, issue_number, LABEL_DISPATCHING)

        child_issues = state.execution_plan.child_issues
        if not child_issues:
            logger.warning("No child issues in execution plan for epic #%d.", issue_number)
            return

        if state.status != "dispatching":
            self._state.transition(state, "dispatching")
        self._dispatch_child_issues(issue_number, state, child_issues)

    # ------------------------------------------------------------------
    # Planning helpers
    # ------------------------------------------------------------------

    def _generate_plan(self, issue: Issue, state: EpicState) -> dict[str, Any]:
        spec_json = json.dumps(
            {
                "acceptance_criteria": state.spec.acceptance_criteria,
                "affected_services": state.spec.affected_services,
                "data_model_changes": state.spec.data_model_changes,
                "api_contract_changes": state.spec.api_contract_changes,
                "edge_cases": state.spec.edge_cases,
                "open_questions": state.spec.open_questions,
            },
            indent=2,
        )
        registry_context = self._build_registry_context(state.spec.affected_services)
        prompt = PLANNING_PROMPT.format(
            title=issue.title,
            spec_json=spec_json,
            registry_context=registry_context,
        )
        response = self._llm.complete(
            system_prompt=SYSTEM_PROMPT,
            messages=[Message(role="user", content=prompt)],
        )
        return self._extract_plan(response)

    def _revise_plan(
        self,
        issue: Issue,
        state: EpicState,
        original_plan: dict[str, Any],
        feedback: str,
    ) -> dict[str, Any]:
        registry_context = self._build_registry_context(state.spec.affected_services)
        prompt = REVISION_PROMPT.format(
            title=issue.title,
            original_plan=json.dumps(original_plan, indent=2),
            feedback=feedback,
            registry_context=registry_context,
        )
        response = self._llm.complete(
            system_prompt=SYSTEM_PROMPT,
            messages=[Message(role="user", content=prompt)],
        )
        return self._extract_plan(response)

    @staticmethod
    def _extract_plan(response: str) -> dict[str, Any]:
        match = re.search(r"```json\s*(\{.*?\})\s*```", response, re.DOTALL)
        if not match:
            logger.warning("No JSON block found in LLM response; returning empty plan.")
            return {"contracts": [], "child_issues": [], "migration_flags": []}
        try:
            data = json.loads(match.group(1))
            return data.get("execution_plan", data)
        except json.JSONDecodeError:
            logger.warning("Failed to parse plan JSON.")
            return {"contracts": [], "child_issues": [], "migration_flags": []}

    def _build_registry_context(self, service_names: list[str]) -> str:
        if not service_names:
            service_names = [svc.name for svc in self._registry.all_services()]
        return self._registry.build_context_summary(service_names)

    # ------------------------------------------------------------------
    # Comment helpers
    # ------------------------------------------------------------------

    def _post_execution_plan(self, issue_number: int, plan: dict[str, Any]) -> None:
        summary = plan.get("summary", "No summary provided.")
        child_issues = plan.get("child_issues", [])
        contracts = plan.get("contracts", [])
        migration_flags = plan.get("migration_flags", [])

        child_table_rows = "\n".join(f"| `{ci.get('spoke_repo', '?')}` | {ci.get('title', '?')} |" for ci in child_issues)
        child_issues_table = "| Repository | Issue Title |\n|------------|-------------|\n" + child_table_rows if child_table_rows else "_No child issues planned._"

        contracts_summary = "\n".join(f"- **{c.get('service', '?')}** ({c.get('type', '?')}): {c.get('description', '')}" for c in contracts) or "_No new contracts._"

        migration_section = (
            "\n".join(f"- **{f.get('service', '?')}** [{f.get('risk', '?')}]: {f.get('description', '')}" if isinstance(f, dict) else f"- {f}" for f in migration_flags)
            or "_No migrations required._"
        )

        body = EXECUTION_PLAN_COMMENT.format(
            summary=summary,
            child_issues_table=child_issues_table,
            contracts_summary=contracts_summary,
            migration_flags=migration_section,
            plan_json=json.dumps({"execution_plan": plan}, indent=2),
        )
        marked_body = f"{BOT_COMMENT_MARKER}\n{body}"
        self._platform.post_comment(self._repo, issue_number, marked_body)

    def _extract_latest_engineer_comment(self, issue: Issue) -> str:
        """Return the most recent non-bot comment on *issue*."""
        non_bot = [c for c in reversed(issue.comments) if self._bot_login not in c.get("author", "") and BOT_COMMENT_MARKER not in c.get("body", "")]
        if non_bot:
            return non_bot[0].get("body", "")
        return ""

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch_child_issues(
        self,
        epic_number: int,
        state: EpicState,
        child_issues: list[dict[str, Any]],
    ) -> None:
        """Create child issues in spoke repos, skipping already-dispatched ones."""
        created_count = 0
        for child in child_issues:
            spoke_repo = child.get("spoke_repo", "")
            title = child.get("title", "")
            body = child.get("body", "")
            labels = child.get("labels", [])

            if not spoke_repo or not title:
                logger.warning("Skipping child issue with missing repo or title.")
                continue

            key = self._state.dispatch_key(epic_number, spoke_repo, title)
            if self._state.is_dispatched(state, key):
                logger.info("Skipping already-dispatched key: %s", key)
                continue

            try:
                issue = self._platform.create_issue(spoke_repo, title, body, labels)
                self._state.record_dispatch(state, spoke_repo, title, issue.number)
                created_count += 1
                logger.info("Created child issue #%d in %s", issue.number, spoke_repo)
            except Exception as exc:
                logger.error("Failed to create child issue in %s: %s", spoke_repo, exc)
                self._state.record_failure(
                    epic_number,
                    f"Failed to dispatch child issue to {spoke_repo}: {exc}",
                    {"spoke_repo": spoke_repo, "title": title},
                )

        if created_count > 0:
            self._state.transition(state, "in_progress")
            logger.info(
                "Dispatch complete: %d child issues created for epic #%d.",
                created_count,
                epic_number,
            )
