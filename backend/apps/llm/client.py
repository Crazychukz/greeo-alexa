"""The sole gateway through which Greeo may request LLM output."""

from __future__ import annotations

import json
import os
import time
from decimal import Decimal
from typing import Any, TypeVar

from django.conf import settings
from pydantic import BaseModel, ValidationError

from .backends import BackendResponse, BedrockLLM, LLMBackend, MockLLM
from .budget import BudgetGuard, RedisBudgetGuard
from .exceptions import LLMError, LLMOutputError
from .models import LLMCall
from .prompt_registry import PromptDefinition, load_prompt

OutputModel = TypeVar("OutputModel", bound=BaseModel)


class LLMGateway:
    """Render, guard, call, validate, and audit every request in one place."""

    def __init__(
        self, backend: LLMBackend | None = None, budget: BudgetGuard | None = None
    ) -> None:
        self.backend = backend or configured_backend()
        self.budget = budget or RedisBudgetGuard()

    def generate_json(
        self,
        prompt_name: str,
        variables: dict[str, Any],
        output_model: type[OutputModel],
    ) -> OutputModel:
        """Return only Pydantic-validated output, repairing malformed JSON once."""
        definition = load_prompt(prompt_name)
        rendered = render_prompt(definition, variables, output_model)
        first = self._call(definition, rendered, variables)
        parsed = validate_output(first.text, output_model)
        if parsed is not None:
            return parsed

        repair = render_repair_prompt(rendered, first.text, output_model)
        second = self._call(definition, repair, variables)
        parsed = validate_output(second.text, output_model)
        if parsed is not None:
            return parsed
        raise LLMOutputError(
            f"{prompt_name!r} returned invalid JSON after one bounded repair attempt."
        )

    def _call(
        self,
        definition: PromptDefinition,
        rendered_prompt: str,
        variables: dict[str, Any],
    ) -> BackendResponse:
        """Reserve budget, invoke the provider once, and write one audit record."""
        model_id = model_for_prompt(definition.name)
        run_id = str(variables.get("pipeline_run_id", "global"))
        reservation = self.budget.reserve(run_id, rendered_prompt, settings.LLM_MAX_TOKENS)
        started = time.monotonic()
        try:
            response = self.backend.generate(
                prompt=rendered_prompt,
                model_id=model_id,
                max_tokens=settings.LLM_MAX_TOKENS,
            )
        except Exception as error:
            self.budget.settle(reservation, 0)
            self._record_call(
                definition=definition,
                model_id=model_id,
                variables=variables,
                tokens_in=0,
                tokens_out=0,
                latency_ms=elapsed_ms(started),
                ok=False,
                error=str(error),
            )
            raise

        self.budget.settle(reservation, response.tokens_in + response.tokens_out)
        self._record_call(
            definition=definition,
            model_id=model_id,
            variables=variables,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            latency_ms=elapsed_ms(started),
            ok=True,
            error="",
        )
        return response

    def _record_call(
        self,
        *,
        definition: PromptDefinition,
        model_id: str,
        variables: dict[str, Any],
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        ok: bool,
        error: str,
    ) -> None:
        """Persist metadata, never the input evidence or generated content itself."""
        story = None
        story_id = variables.get("story_id")
        if story_id:
            from apps.stories.models import Story

            story = Story.objects.filter(pk=story_id).first()
        LLMCall.objects.create(
            prompt_name=definition.name,
            prompt_version=definition.version,
            model=model_id if self.backend.name != "mock" else MockLLM.model_id,
            backend=self.backend.name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            cost_estimate_usd=estimate_cost(tokens_in, tokens_out),
            ok=ok,
            error=error[:2000],
            story=story,
        )


def generate_json[OutputModel: BaseModel](
    prompt_name: str, variables: dict[str, Any], output_model: type[OutputModel]
) -> OutputModel:
    """Convenience entry point for services; no code may bypass this function."""
    return LLMGateway().generate_json(prompt_name, variables, output_model)


def configured_backend() -> LLMBackend:
    """Select exactly one provider from environment-backed Django settings."""
    if settings.LLM_BACKEND == "mock":
        return MockLLM()
    if settings.LLM_BACKEND == "bedrock":
        return BedrockLLM()
    raise LLMError("LLM_BACKEND must be 'mock' or 'bedrock'.")


def model_for_prompt(prompt_name: str) -> str:
    """Allow each registered prompt to choose a Bedrock model through its env var."""
    key = f"LLM_{prompt_name.upper()}_MODEL_ID"
    return str(os.environ.get(key, settings.BEDROCK_MODEL_ID))


def render_prompt(
    definition: PromptDefinition, variables: dict[str, Any], output_model: type[BaseModel]
) -> str:
    """Attach supplied variables and the JSON schema to the versioned prompt asset."""
    return "\n\n".join(
        [
            f"PROMPT_NAME: {definition.name}",
            definition.text.strip(),
            "INPUT_VARIABLES_JSON:\n" + json.dumps(variables, sort_keys=True, default=str),
            "OUTPUT_SCHEMA_JSON:\n" + json.dumps(output_model.model_json_schema(), sort_keys=True),
        ]
    )


def render_repair_prompt(
    original_prompt: str, invalid_output: str, output_model: type[BaseModel]
) -> str:
    """Ask for one schema-constrained correction without a recursive repair loop."""
    return "\n\n".join(
        [
            original_prompt,
            "REPAIR_REQUIRED: Your previous response was not valid for OUTPUT_SCHEMA_JSON.",
            "PREVIOUS_OUTPUT:\n" + invalid_output,
            "Return only one corrected JSON object matching OUTPUT_SCHEMA_JSON.",
        ]
    )


def validate_output[OutputModel: BaseModel](
    text: str, output_model: type[OutputModel]
) -> OutputModel | None:
    """Return a parsed Pydantic instance or None so the caller can repair once."""
    try:
        return output_model.model_validate_json(text)
    except (ValidationError, ValueError):
        return None


def estimate_cost(tokens_in: int, tokens_out: int) -> Decimal:
    """Use configurable per-million prices because Bedrock prices vary by model."""
    input_price = Decimal(settings.LLM_INPUT_PRICE_PER_MILLION_USD)
    output_price = Decimal(settings.LLM_OUTPUT_PRICE_PER_MILLION_USD)
    return (Decimal(tokens_in) * input_price + Decimal(tokens_out) * output_price) / Decimal(
        1_000_000
    )


def elapsed_ms(started: float) -> int:
    """Record coarse request latency without coupling to a provider clock."""
    return max(0, round((time.monotonic() - started) * 1000))
