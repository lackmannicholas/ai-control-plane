"""LLM abstraction layer.

Agents call the LLM through this interface so that the underlying provider
(Anthropic, OpenAI, etc.) can be swapped without touching agent logic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str


class LLMInterface(ABC):
    """Minimal interface for text-generation models."""

    @abstractmethod
    def complete(
        self,
        system_prompt: str,
        messages: list[Message],
        max_tokens: int = 4096,
    ) -> str:
        """Return the model's response text given a conversation history."""
