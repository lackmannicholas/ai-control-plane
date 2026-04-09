"""
Platform abstraction layer for the AI control plane.

All agent code interacts with source-control platforms exclusively through
this interface. The GitHub implementation lives in github_adapter.py; a
future Azure DevOps implementation would live in ado_adapter.py while the
agent logic remains unchanged.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Issue:
    number: int
    title: str
    body: str
    labels: list[str]
    state: str
    url: str
    author: str
    comments: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PullRequest:
    number: int
    title: str
    body: str
    head: str
    base: str
    url: str
    state: str


@dataclass
class FileContent:
    path: str
    content: str
    sha: str


class PlatformInterface(ABC):
    """Abstract interface for source-control platform operations.

    Agents must only call methods defined here. No platform-specific API
    client may be referenced outside of a concrete adapter class.
    """

    @abstractmethod
    def create_issue(
        self,
        repo: str,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> Issue:
        """Create a new issue in *repo* and return the created Issue."""

    @abstractmethod
    def read_issue(self, repo: str, issue_number: int) -> Issue:
        """Return the Issue identified by *issue_number* in *repo*."""

    @abstractmethod
    def create_pr(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str,
    ) -> PullRequest:
        """Open a pull request from *head* into *base* in *repo*."""

    @abstractmethod
    def add_label(self, repo: str, issue_number: int, label: str) -> None:
        """Add *label* to the issue identified by *issue_number* in *repo*."""

    @abstractmethod
    def remove_label(self, repo: str, issue_number: int, label: str) -> None:
        """Remove *label* from the issue identified by *issue_number* in *repo*."""

    @abstractmethod
    def post_comment(self, repo: str, issue_number: int, body: str) -> dict[str, Any]:
        """Post a comment on the issue identified by *issue_number* in *repo*."""

    @abstractmethod
    def get_file(self, repo: str, path: str, ref: str = "main") -> FileContent:
        """Return the contents of *path* at *ref* in *repo*."""
