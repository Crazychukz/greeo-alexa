"""Gateway tests ensure unvalidated model output cannot move into Greeo."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from apps.llm.backends import JSON_ONLY_INSTRUCTION, BackendResponse, BedrockLLM, MockLLM
from apps.llm.budget import RedisBudgetGuard
from apps.llm.client import LLMGateway
from apps.llm.exceptions import BudgetExceeded, LLMOutputError, LLMProviderError
from apps.llm.models import LLMCall
from django.test import override_settings
from pydantic import BaseModel


class FactsResponse(BaseModel):
    facts: list[str]
    synthetic: bool


@dataclass
class FixedBudget:
    reservations: list[int]

    def reserve(self, run_id: str, prompt: str, max_tokens: int) -> int:
        del run_id, prompt, max_tokens
        reservation = len(self.reservations) + 1
        self.reservations.append(reservation)
        return reservation

    def settle(self, reservation: int, actual_tokens: int) -> None:
        del reservation, actual_tokens


class SequenceBackend:
    name = "mock"

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = iter(outputs)
        self.calls = 0

    def generate(
        self, *, prompt: str, model_id: str, max_tokens: int, temperature: float = 0.0
    ) -> BackendResponse:
        del prompt, model_id, max_tokens
        self.calls += 1
        return BackendResponse(next(self.outputs), tokens_in=2, tokens_out=3)


@pytest.mark.django_db
def test_mock_round_trip_is_pydantic_valid_and_audited() -> None:
    gateway = LLMGateway(backend=MockLLM(), budget=FixedBudget([]))

    response = gateway.generate_json("establish_facts", {}, FactsResponse)

    assert response == FactsResponse(facts=[], synthetic=True)
    call = LLMCall.objects.get()
    assert call.backend == "mock"
    assert call.prompt_version == "v2"
    assert call.ok is True


@pytest.mark.django_db
def test_malformed_json_gets_exactly_one_repair_retry() -> None:
    backend = SequenceBackend(["not json", '{"facts": [], "synthetic": true}'])
    gateway = LLMGateway(backend=backend, budget=FixedBudget([]))

    assert gateway.generate_json("establish_facts", {}, FactsResponse).synthetic is True
    assert backend.calls == 2
    assert LLMCall.objects.count() == 2


@pytest.mark.django_db
def test_invalid_repair_stops_after_two_total_provider_calls() -> None:
    backend = SequenceBackend(["not json", "still not json"])
    gateway = LLMGateway(backend=backend, budget=FixedBudget([]))

    with pytest.raises(LLMOutputError):
        gateway.generate_json("establish_facts", {}, FactsResponse)

    assert backend.calls == 2


class RejectingBudget:
    def reserve(self, run_id: str, prompt: str, max_tokens: int) -> int:
        del run_id, prompt, max_tokens
        raise BudgetExceeded("synthetic budget limit")

    def settle(self, reservation: int, actual_tokens: int) -> None:
        raise AssertionError("settle must not be called")


@pytest.mark.django_db
def test_budget_guard_stops_call_before_provider() -> None:
    backend = SequenceBackend(['{"facts": [], "synthetic": true}'])
    gateway = LLMGateway(backend=backend, budget=RejectingBudget())

    with pytest.raises(BudgetExceeded, match="synthetic budget limit"):
        gateway.generate_json("establish_facts", {}, FactsResponse)

    assert backend.calls == 0
    assert LLMCall.objects.count() == 0


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def incrby(self, key: str, amount: int) -> int:
        self.values[key] = self.values.get(key, 0) + amount
        return self.values[key]

    def decr(self, key: str) -> int:
        return self.incrby(key, -1)

    def decrby(self, key: str, amount: int) -> int:
        return self.incrby(key, -amount)

    def expire(self, key: str, seconds: int) -> bool:
        del key, seconds
        return True

    def pipeline(self, transaction: bool = True) -> FakePipeline:
        del transaction
        return FakePipeline(self)


class FakePipeline:
    """Queue commands like redis-py and run them together on execute()."""

    def __init__(self, redis: FakeRedis) -> None:
        self.redis = redis
        self.commands: list[tuple[str, tuple[object, ...]]] = []

    def incrby(self, key: str, amount: int) -> None:
        self.commands.append(("incrby", (key, amount)))

    def expire(self, key: str, seconds: int) -> None:
        self.commands.append(("expire", (key, seconds)))

    def execute(self) -> list[object]:
        return [getattr(self.redis, name)(*args) for name, args in self.commands]


@override_settings(LLM_MAX_CALLS_PER_RUN=1, LLM_DAILY_TOKEN_BUDGET=1000)
def test_redis_budget_guard_enforces_per_run_limit() -> None:
    guard = RedisBudgetGuard(client=FakeRedis())
    guard.reserve("synthetic-run", "prompt", 10)

    with pytest.raises(BudgetExceeded, match="LLM_MAX_CALLS_PER_RUN"):
        guard.reserve("synthetic-run", "prompt", 10)


class RecordingBudget:
    def __init__(self) -> None:
        self.settled: list[tuple[int, int]] = []

    def reserve(self, run_id: str, prompt: str, max_tokens: int) -> int:
        del run_id, prompt, max_tokens
        return 500

    def settle(self, reservation: int, actual_tokens: int) -> None:
        self.settled.append((reservation, actual_tokens))


class FailingBackend:
    name = "mock"

    def generate(
        self, *, prompt: str, model_id: str, max_tokens: int, temperature: float = 0.0
    ) -> BackendResponse:
        del prompt, model_id, max_tokens
        raise LLMProviderError("synthetic provider outage")


@pytest.mark.django_db
def test_failed_provider_call_returns_its_budget_reservation() -> None:
    budget = RecordingBudget()
    gateway = LLMGateway(backend=FailingBackend(), budget=budget)

    with pytest.raises(LLMProviderError):
        gateway.generate_json("establish_facts", {}, FactsResponse)

    assert budget.settled == [(500, 0)]
    assert LLMCall.objects.get().ok is False


@override_settings(LLM_MAX_CALLS_PER_RUN=10, LLM_DAILY_TOKEN_BUDGET=1000)
def test_settling_a_failed_call_frees_the_daily_reservation() -> None:
    redis = FakeRedis()
    guard = RedisBudgetGuard(client=redis)

    reservation = guard.reserve("synthetic-run", "prompt", 100)
    guard.settle(reservation, 0)

    assert sum(v for k, v in redis.values.items() if k.startswith("greeo:llm:tokens:")) == 0


class NoNetworkBedrockClient:
    def __init__(self) -> None:
        self.request: dict[str, object] | None = None

    def converse(self, **request: object) -> dict[str, object]:
        self.request = request
        return {
            "output": {"message": {"content": [{"text": '{"facts": [], "synthetic": true}'}]}},
            "usage": {"inputTokens": 7, "outputTokens": 5},
        }


@override_settings(AWS_REGION="us-east-1")
def test_bedrock_adapter_uses_converse_shape_without_network() -> None:
    fake = NoNetworkBedrockClient()
    response = BedrockLLM(client=fake).generate(
        prompt="PROMPT_NAME: establish_facts", model_id="test.model", max_tokens=123
    )

    assert response.tokens_in == 7
    assert fake.request == {
        "modelId": "test.model",
        "system": [{"text": JSON_ONLY_INSTRUCTION}],
        "messages": [{"role": "user", "content": [{"text": "PROMPT_NAME: establish_facts"}]}],
        "inferenceConfig": {"maxTokens": 123, "temperature": 0},
    }


@override_settings(AWS_REGION="us-east-1")
def test_bedrock_requires_a_model_id_before_network() -> None:
    with pytest.raises(LLMProviderError, match="BEDROCK_MODEL_ID"):
        BedrockLLM(client=object()).generate(prompt="test", model_id="", max_tokens=10)
