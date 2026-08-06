"""
The provider-agnostic LLM interface.

Every model provider (DeepSeek, Claude, ...) implements LLMProvider. Callers
depend on this interface, never on a concrete provider — that's your scoping's
"never hardcode a provider" rule made concrete. Swapping or adding a model is a
new class here, not a change everywhere.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMError(Exception):
    """A provider failed to return a usable completion (network, auth, shape)."""


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """
        Send system + user prompts to the model and return its text output.

        For quiz generation we always ask for JSON, so the returned string is
        expected to be a JSON document (parsed/validated by the caller).
        """
        raise NotImplementedError
