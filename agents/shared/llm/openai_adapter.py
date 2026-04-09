"""OpenAI adapter for LLMInterface."""

from __future__ import annotations

from openai import OpenAI

from agents.shared.llm.interface import LLMInterface, Message


class OpenAIAdapter(LLMInterface):
    """Wraps the OpenAI Python SDK.

    Args:
        api_key: OpenAI API key (defaults to ``OPENAI_API_KEY`` env var).
        model: Model identifier. Defaults to ``gpt-4o``.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o",
    ) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def complete(
        self,
        system_prompt: str,
        messages: list[Message],
        max_tokens: int = 4096,
    ) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                *[{"role": m.role, "content": m.content} for m in messages],
            ],
        )
        return response.choices[0].message.content
