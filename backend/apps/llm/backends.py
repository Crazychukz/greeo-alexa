"""Provider adapters. Only client.py may invoke these adapters."""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from typing import Any, Protocol

from django.conf import settings

from .exceptions import LLMProviderError

JSON_ONLY_INSTRUCTION = (
    "Return only one valid JSON object. Do not use markdown, prose, or code fences."
)


@dataclass(frozen=True)
class BackendResponse:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0


class LLMBackend(Protocol):
    name: str

    def generate(self, *, prompt: str, model_id: str, max_tokens: int) -> BackendResponse: ...


class MockLLM:
    """Deterministic, visibly synthetic fixtures for local development and tests."""

    name = "mock"
    model_id = "mock-synthetic-v1"

    _OUTPUTS: dict[str, dict[str, Any]] = {
        "establish_facts": {"facts": [], "synthetic": True},
        "build_context": {"context": [], "synthetic": True},
        "compare_perspectives": {"perspectives": [], "synthetic": True},
        "classify_tone": {"tone": "balanced", "synthetic": True},
        "write_telling": {
            "beats": ["SYNTHETIC BEAT: no real-world content."],
            "reflection": "SYNTHETIC REFLECTION: no real-world lesson.",
            "synthetic": True,
        },
        "check_telling": {"valid": True, "issues": [], "synthetic": True},
        "revise_telling": {
            "beats": ["SYNTHETIC REVISED BEAT: no real-world content."],
            "synthetic": True,
        },
        "rerank_proverb": {"ranked_candidate_ids": [], "synthetic": True},
        "summarize_update": {"summary": "SYNTHETIC UPDATE.", "synthetic": True},
        "grade_recall": {"score": 0, "synthetic": True},
    }

    def generate(self, *, prompt: str, model_id: str, max_tokens: int) -> BackendResponse:
        """Return a canned JSON payload identified by the registry prompt heading."""
        del model_id, max_tokens
        prompt_name = prompt.splitlines()[0].removeprefix("PROMPT_NAME: ").strip()
        try:
            payload = self._OUTPUTS[prompt_name]
        except KeyError as error:
            raise LLMProviderError(f"MockLLM has no canned output for {prompt_name!r}.") from error
        text = json.dumps(payload, sort_keys=True)
        return BackendResponse(
            text=text, tokens_in=ceil_tokens(prompt), tokens_out=ceil_tokens(text)
        )


class BedrockLLM:
    """Amazon Bedrock Converse adapter with bounded retry behaviour."""

    name = "bedrock"

    def __init__(self, client: Any | None = None, sleep: Any = time.sleep) -> None:
        self._sleep = sleep
        if client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError as error:  # pragma: no cover - dependency is pinned.
                raise LLMProviderError("Install boto3 to use LLM_BACKEND=bedrock.") from error
            client = boto3.client(
                "bedrock-runtime",
                region_name=settings.AWS_REGION,
                config=Config(
                    connect_timeout=settings.LLM_TIMEOUT_SECONDS,
                    read_timeout=settings.LLM_TIMEOUT_SECONDS,
                    retries={"max_attempts": 0},
                ),
            )
        self.client = client

    def generate(self, *, prompt: str, model_id: str, max_tokens: int) -> BackendResponse:
        """Call Converse using JSON-only instructions and return its usage metadata."""
        if not model_id:
            raise LLMProviderError(
                "BEDROCK_MODEL_ID is required when LLM_BACKEND=bedrock. "
                "Set it to a model enabled in AWS_REGION."
            )

        request = {
            "modelId": model_id,
            "system": [{"text": JSON_ONLY_INSTRUCTION}],
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0},
        }
        last_error: Exception | None = None
        for attempt in range(settings.LLM_PROVIDER_RETRIES + 1):
            try:
                response = self.client.converse(**request)
                text = "".join(
                    part["text"]
                    for part in response["output"]["message"]["content"]
                    if "text" in part
                )
                if not text:
                    raise LLMProviderError("Bedrock Converse returned no text content.")
                usage = response.get("usage", {})
                return BackendResponse(
                    text=text,
                    tokens_in=int(usage.get("inputTokens", 0)),
                    tokens_out=int(usage.get("outputTokens", 0)),
                )
            except Exception as error:  # Botocore exceptions differ by transport failure.
                last_error = error
                if not is_retryable(error) or attempt == settings.LLM_PROVIDER_RETRIES:
                    raise bedrock_error(error, settings.AWS_REGION, model_id) from error
                self._sleep((2**attempt) + random.uniform(0, 0.25))
        raise bedrock_error(last_error, settings.AWS_REGION, model_id)  # pragma: no cover


def ceil_tokens(value: str) -> int:
    """Use a simple deterministic estimate where a provider supplied none."""
    return max(1, (len(value) + 3) // 4)


def is_retryable(error: Exception) -> bool:
    """Retry only transient provider failures; configuration errors must surface."""
    try:
        from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError
    except ImportError:  # Supports Bedrock stubs before the SDK is installed.
        return False
    if isinstance(error, (ConnectTimeoutError, ReadTimeoutError)):
        return True
    if isinstance(error, ClientError):
        code = error.response.get("Error", {}).get("Code", "")
        return code in {"InternalServerException", "ModelTimeoutException", "ThrottlingException"}
    return False


def bedrock_error(error: Exception | None, region: str, model_id: str) -> LLMProviderError:
    """Translate common AWS errors into an operator-actionable message."""
    code = ""
    message = str(error or "unknown Bedrock error")
    try:
        from botocore.exceptions import ClientError

        if isinstance(error, ClientError):
            code = error.response.get("Error", {}).get("Code", "")
            message = error.response.get("Error", {}).get("Message", message)
    except ImportError:
        pass
    if code == "AccessDeniedException":
        return LLMProviderError(
            f"Bedrock access denied for {model_id!r} in {region}. "
            "Check IAM permission bedrock:InvokeModel and model access."
        )
    if code in {"ResourceNotFoundException", "ValidationException"}:
        return LLMProviderError(
            f"Bedrock model {model_id!r} is unavailable in {region}. "
            "Confirm its ID, region, and that model access is enabled. Details: " + message
        )
    return LLMProviderError(f"Bedrock Converse failed for {model_id!r} in {region}: {message}")
