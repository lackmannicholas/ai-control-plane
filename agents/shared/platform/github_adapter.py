"""GitHub adapter — concrete implementation of PlatformInterface."""

from __future__ import annotations

import base64
import time
from typing import Any

import requests

from agents.shared.platform.interface import (
    FileContent,
    Issue,
    PlatformInterface,
    PullRequest,
)


class GitHubAdapter(PlatformInterface):
    """Implements PlatformInterface against the GitHub REST API.

    Args:
        token: A GitHub personal-access token or Actions GITHUB_TOKEN with
               ``repo`` scope (or ``issues`` + ``pull_requests`` scopes for
               the minimum surface used here).
        base_url: Override for GitHub Enterprise Server installations.
    """

    _MAX_RETRIES = 5
    _RETRY_BASE_DELAY = 1.0  # seconds; doubled on each attempt (exponential back-off)

    def __init__(self, token: str, base_url: str = "https://api.github.com") -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> Any:
        """Execute *method* against *path*, handling rate-limit retries."""
        url = f"{self._base_url}{path}"
        delay = self._RETRY_BASE_DELAY
        for attempt in range(self._MAX_RETRIES):
            response = self._session.request(method, url, **kwargs)
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", delay))
                time.sleep(retry_after)
                delay *= 2
                continue
            response.raise_for_status()
            if response.status_code == 204:
                return None
            return response.json()
        raise RuntimeError(f"Exceeded max retries for {method} {url}")

    @staticmethod
    def _parse_issue(data: dict[str, Any]) -> Issue:
        return Issue(
            number=data["number"],
            title=data["title"],
            body=data.get("body") or "",
            labels=[lbl["name"] for lbl in data.get("labels", [])],
            state=data["state"],
            url=data["html_url"],
            author=data["user"]["login"],
        )

    # ------------------------------------------------------------------
    # PlatformInterface implementation
    # ------------------------------------------------------------------

    def create_issue(
        self,
        repo: str,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> Issue:
        data = self._request(
            "POST",
            f"/repos/{repo}/issues",
            json={"title": title, "body": body, "labels": labels or []},
        )
        return self._parse_issue(data)

    def read_issue(self, repo: str, issue_number: int) -> Issue:
        data = self._request("GET", f"/repos/{repo}/issues/{issue_number}")
        issue = self._parse_issue(data)
        comments_data = self._request(
            "GET",
            f"/repos/{repo}/issues/{issue_number}/comments",
            params={"per_page": 100},
        )
        issue.comments = [
            {
                "id": c["id"],
                "author": c["user"]["login"],
                "body": c["body"],
                "created_at": c["created_at"],
            }
            for c in (comments_data or [])
        ]
        return issue

    def create_pr(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str,
    ) -> PullRequest:
        data = self._request(
            "POST",
            f"/repos/{repo}/pulls",
            json={"title": title, "body": body, "head": head, "base": base},
        )
        return PullRequest(
            number=data["number"],
            title=data["title"],
            body=data.get("body") or "",
            head=data["head"]["ref"],
            base=data["base"]["ref"],
            url=data["html_url"],
            state=data["state"],
        )

    def add_label(self, repo: str, issue_number: int, label: str) -> None:
        self._request(
            "POST",
            f"/repos/{repo}/issues/{issue_number}/labels",
            json={"labels": [label]},
        )

    def remove_label(self, repo: str, issue_number: int, label: str) -> None:
        self._request(
            "DELETE",
            f"/repos/{repo}/issues/{issue_number}/labels/{label}",
        )

    def post_comment(self, repo: str, issue_number: int, body: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/repos/{repo}/issues/{issue_number}/comments",
            json={"body": body},
        )

    def get_file(self, repo: str, path: str, ref: str = "main") -> FileContent:
        data = self._request(
            "GET",
            f"/repos/{repo}/contents/{path}",
            params={"ref": ref},
        )
        raw_content = base64.b64decode(data["content"]).decode("utf-8")
        return FileContent(path=data["path"], content=raw_content, sha=data["sha"])
