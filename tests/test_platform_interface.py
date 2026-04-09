"""Tests for the platform abstraction layer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.shared.platform.github_adapter import GitHubAdapter
from agents.shared.platform.interface import (
    PlatformInterface,
)


class TestPlatformInterfaceIsAbstract:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            PlatformInterface()  # type: ignore[abstract]

    def test_all_methods_are_abstract(self):
        abstract_methods = getattr(PlatformInterface, "__abstractmethods__", set())
        expected = {
            "create_issue",
            "read_issue",
            "create_pr",
            "add_label",
            "remove_label",
            "post_comment",
            "get_file",
        }
        assert abstract_methods == expected


class TestGitHubAdapterInit:
    def test_default_base_url(self):
        adapter = GitHubAdapter(token="tok")
        assert adapter._base_url == "https://api.github.com"

    def test_custom_base_url_strips_trailing_slash(self):
        adapter = GitHubAdapter(token="tok", base_url="https://ghe.example.com/")
        assert adapter._base_url == "https://ghe.example.com"

    def test_authorization_header_is_set(self):
        adapter = GitHubAdapter(token="my-token")
        assert adapter._session.headers["Authorization"] == "Bearer my-token"


class TestGitHubAdapterRequests:
    def _make_adapter(self) -> GitHubAdapter:
        return GitHubAdapter(token="test-token")

    def test_create_issue_calls_post(self):
        adapter = self._make_adapter()
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "number": 42,
            "title": "My issue",
            "body": "body",
            "labels": [],
            "state": "open",
            "html_url": "https://github.com/org/repo/issues/42",
            "user": {"login": "author"},
        }
        with patch.object(adapter._session, "request", return_value=mock_response):
            issue = adapter.create_issue("org/repo", "My issue", "body", ["label"])
        assert issue.number == 42
        assert issue.title == "My issue"

    def test_post_comment_calls_correct_endpoint(self):
        adapter = self._make_adapter()
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": 1, "body": "hello"}
        with patch.object(adapter._session, "request", return_value=mock_response) as mock_req:
            adapter.post_comment("org/repo", 1, "hello")
        call_args = mock_req.call_args
        assert "/repos/org/repo/issues/1/comments" in call_args.args[1]

    def test_add_label_sends_correct_payload(self):
        adapter = self._make_adapter()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        with patch.object(adapter._session, "request", return_value=mock_response) as mock_req:
            adapter.add_label("org/repo", 5, "epic")
        call_args = mock_req.call_args
        assert call_args.kwargs["json"] == {"labels": ["epic"]}

    def test_rate_limit_retry_with_exponential_backoff(self):
        adapter = self._make_adapter()
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.headers = {"Retry-After": "0"}
        success = MagicMock()
        success.status_code = 204
        success.json.return_value = None
        with patch.object(adapter._session, "request", side_effect=[rate_limited, success]):
            with patch("time.sleep"):
                adapter.remove_label("org/repo", 1, "refining")

    def test_get_file_decodes_base64_content(self):
        import base64

        adapter = self._make_adapter()
        content = "hello world"
        encoded = base64.b64encode(content.encode()).decode() + "\n"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "path": "README.md",
            "content": encoded,
            "sha": "abc123",
        }
        with patch.object(adapter._session, "request", return_value=mock_response):
            fc = adapter.get_file("org/repo", "README.md")
        assert fc.content == content
        assert fc.sha == "abc123"
