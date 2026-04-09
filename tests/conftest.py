"""Shared pytest fixtures."""

from __future__ import annotations

from agents.shared.platform.interface import Issue


def make_issue(
    number: int = 1,
    title: str = "Test issue",
    body: str = "Test body",
    labels: list[str] | None = None,
    state: str = "open",
    author: str = "pm-user",
    comments: list[dict] | None = None,
) -> Issue:
    return Issue(
        number=number,
        title=title,
        body=body,
        labels=labels or [],
        state=state,
        url=f"https://github.com/test/repo/issues/{number}",
        author=author,
        comments=comments or [],
    )
