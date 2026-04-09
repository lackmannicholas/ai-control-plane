"""Anthropic Claude adapter for LLMInterface."""

from __future__ import annotations

import anthropic

from agents.shared.llm.interface import LLMInterface, Message


class AnthropicAdapter(LLMInterface):
    """Wraps the Anthropic Python SDK.

    Args:
        api_key: Anthropic API key (defaults to ``ANTHROPIC_API_KEY`` env var).
        model: Model identifier. Defaults to ``claude-3-5-sonnet-20241022``.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-3-5-sonnet-20241022",
    ) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(
        self,
        system_prompt: str,
        messages: list[Message],
        max_tokens: int = 4096,
    ) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": m.role, "content": m.content} for m in messages],
        )
        return response.content[0].text
