"""PRD Refiner Agent.

Triggered by GitHub Actions on:
  - ``issues`` ``labeled`` with ``epic``  → begin refinement
  - ``issue_comment`` ``created`` on issue with ``epic`` + ``refining`` labels
    → continue refinement loop

The agent iterates with the PM in the issue comment thread until a complete,
machine-actionable specification has been produced, then adds the
``spec-ready`` label and removes ``refining``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from agents.prd_refiner.prompts import (
    INITIAL_ANALYSIS_PROMPT,
    REFINEMENT_LOOP_PROMPT,
    SPEC_COMPLETE_COMMENT,
    SYSTEM_PROMPT,
)
from agents.shared.llm.interface import LLMInterface, Message
from agents.shared.platform.interface import Issue, PlatformInterface
from agents.shared.registry import Registry
from agents.shared.state import StateManager

logger = logging.getLogger(__name__)

# Label constants
LABEL_EPIC = "epic"
LABEL_REFINING = "refining"
LABEL_SPEC_READY = "spec-ready"
LABEL_ARCHITECT_READY = "architect-ready"

# Marker used to identify bot comments in the thread
BOT_COMMENT_MARKER = "<!-- prd-refiner-bot -->"


class PRDRefinerAgent:
    """Orchestrates the PRD refinement loop for a single epic issue.

    Args:
        platform: Concrete platform adapter (GitHub, etc.).
        llm: Concrete LLM adapter (Anthropic, etc.).
        registry: Loaded service registry.
        state_manager: Persistent state manager.
        repo: ``owner/repo`` of the hub repository (e.g. ``org/ai-control-plane``).
        bot_login: GitHub login of the bot account posting comments.
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
    # Entry points called by the GitHub Actions workflow
    # ------------------------------------------------------------------

    def handle_epic_labeled(self, issue_number: int) -> None:
        """Called when an issue receives the ``epic`` label for the first time."""
        issue = self._platform.read_issue(self._repo, issue_number)
        logger.info("Starting refinement for epic #%d: %s", issue_number, issue.title)

        # Initialise or resume state
        state = self._state.load(issue_number)
        if state is None:
            state = self._state.create(issue_number, self._repo, issue.title)

        # Ensure the refining label is present
        if LABEL_REFINING not in issue.labels:
            self._platform.add_label(self._repo, issue_number, LABEL_REFINING)

        registry_context = self._build_registry_context(issue)
        prompt = INITIAL_ANALYSIS_PROMPT.format(
            title=issue.title,
            body=issue.body,
            registry_context=registry_context,
        )
        response = self._llm.complete(
            system_prompt=SYSTEM_PROMPT,
            messages=[Message(role="user", content=prompt)],
        )
        self._post_bot_comment(issue_number, response)

    def handle_pm_comment(self, issue_number: int) -> None:
        """Called when the PM posts a new comment on a refining epic."""
        issue = self._platform.read_issue(self._repo, issue_number)

        # Guard: only act on issues that are actively being refined
        if LABEL_REFINING not in issue.labels:
            logger.debug("Issue #%d is not in refining state; skipping.", issue_number)
            return

        state = self._state.load(issue_number)
        if state is None:
            logger.warning("No state found for epic #%d; starting fresh.", issue_number)
            state = self._state.create(issue_number, self._repo, issue.title)

        conversation = self._format_conversation(issue.comments)
        registry_context = self._build_registry_context(issue)
        prompt = REFINEMENT_LOOP_PROMPT.format(
            title=issue.title,
            body=issue.body,
            registry_context=registry_context,
            conversation=conversation,
        )
        response = self._llm.complete(
            system_prompt=SYSTEM_PROMPT,
            messages=[Message(role="user", content=prompt)],
        )

        spec_data = self._try_extract_spec(response)
        if spec_data:
            self._finalise_spec(issue_number, state, spec_data)
        else:
            self._post_bot_comment(issue_number, response)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_registry_context(self, issue: Issue) -> str:
        """Return a markdown registry context block relevant to *issue*."""
        all_services = self._registry.all_services()
        summary = self._registry.build_context_summary([svc.name for svc in all_services])
        return f"The following services are registered in the hub:\n\n{summary}"

    @staticmethod
    def _format_conversation(comments: list[dict[str, Any]]) -> str:
        lines = []
        for c in comments:
            author = c.get("author", "unknown")
            body = c.get("body", "").strip()
            lines.append(f"**{author}:** {body}\n")
        return "\n".join(lines)

    def _post_bot_comment(self, issue_number: int, body: str) -> None:
        marked_body = f"{BOT_COMMENT_MARKER}\n{body}"
        self._platform.post_comment(self._repo, issue_number, marked_body)

    @staticmethod
    def _try_extract_spec(response: str) -> dict[str, Any] | None:
        """Extract and parse the spec JSON block if the LLM declared completion."""
        match = re.search(r"```json\s*(\{.*?\})\s*```", response, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(1))
            if data.get("status") == "complete":
                return data
        except json.JSONDecodeError:
            logger.warning("Failed to parse spec JSON from LLM response.")
        return None

    def _finalise_spec(
        self,
        issue_number: int,
        state: Any,
        spec_data: dict[str, Any],
    ) -> None:
        """Persist the completed spec, post the summary comment, and update labels."""
        spec = spec_data.get("spec", {})
        summary = spec_data.get("summary", "")

        # Update state
        state.spec.acceptance_criteria = spec.get("acceptance_criteria", [])
        state.spec.affected_services = spec.get("affected_services", [])
        state.spec.data_model_changes = spec.get("data_model_changes", [])
        state.spec.api_contract_changes = spec.get("api_contract_changes", [])
        state.spec.edge_cases = spec.get("edge_cases", [])
        state.spec.open_questions = spec.get("open_questions", [])
        self._state.transition(state, "spec_ready")

        # Post structured summary comment
        comment_body = SPEC_COMPLETE_COMMENT.format(
            summary=summary,
            acceptance_criteria=", ".join(spec.get("acceptance_criteria", [])) or "—",
            affected_services=", ".join(spec.get("affected_services", [])) or "—",
            data_model_changes=", ".join(spec.get("data_model_changes", [])) or "—",
            api_contract_changes=", ".join(spec.get("api_contract_changes", [])) or "—",
            edge_cases=", ".join(spec.get("edge_cases", [])) or "—",
            open_questions=", ".join(spec.get("open_questions", [])) or "—",
        )
        self._post_bot_comment(issue_number, comment_body)

        # Transition labels
        self._platform.remove_label(self._repo, issue_number, LABEL_REFINING)
        self._platform.add_label(self._repo, issue_number, LABEL_SPEC_READY)

        logger.info("Spec complete for epic #%d.", issue_number)
