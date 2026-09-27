"""Explicit failures from the only approved LLM gateway."""


class LLMError(Exception):
    """Base class for LLM gateway failures safe to report to operators."""


class BudgetExceeded(LLMError):
    """Raised before a call that would breach a configured Redis guard."""


class LLMOutputError(LLMError):
    """Raised when an LLM response remains invalid after one repair attempt."""


class LLMProviderError(LLMError):
    """Raised for an unavailable or misconfigured provider."""
