"""Entry point for the Architect Agent invoked by GitHub Actions."""

from __future__ import annotations

import logging
import os
import sys

from agents.architect.agent import ArchitectAgent
from agents.shared.llm.anthropic_adapter import AnthropicAdapter
from agents.shared.platform.github_adapter import GitHubAdapter
from agents.shared.registry import Registry
from agents.shared.state import StateManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        logger.error("Required environment variable %s is not set.", name)
        sys.exit(1)
    return value


def main() -> None:
    github_token = _require_env("GITHUB_TOKEN")
    anthropic_api_key = _require_env("ANTHROPIC_API_KEY")
    repo = _require_env("GITHUB_REPOSITORY")
    event_name = _require_env("GITHUB_EVENT_NAME")
    issue_number = int(_require_env("ISSUE_NUMBER"))
    label_name = os.environ.get("LABEL_NAME", "")

    platform = GitHubAdapter(token=github_token)
    llm = AnthropicAdapter(api_key=anthropic_api_key)
    registry = Registry()
    state_manager = StateManager()

    agent = ArchitectAgent(
        platform=platform,
        llm=llm,
        registry=registry,
        state_manager=state_manager,
        repo=repo,
    )

    if event_name == "issues" and label_name == "architect-ready":
        agent.handle_architect_ready(issue_number)
    elif event_name == "issues" and label_name == "approved-for-dispatch":
        agent.handle_approved_for_dispatch(issue_number)
    elif event_name == "issue_comment":
        agent.handle_engineer_feedback(issue_number)
    else:
        logger.warning("Unhandled event: event_name=%s label_name=%s", event_name, label_name)


if __name__ == "__main__":
    main()
