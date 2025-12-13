from http import HTTPStatus
from typing import Callable, Iterable
import pytest
from datetime import timedelta

from resilience.sender import HTTPStatus
from resilience.multi_client import CircuitBreakerMultiClient, HedgingMultiClient, MultiClient
from resilience.strategies import (
    HedgingStrategy,
    ResilienceStrategy,
    ResilienceStrategyExhausted,
    ExhaustedReason,
    CircuitBreakerStrategy,
)


@pytest.mark.asyncio
class TestBasicMultiClientCapabilities:
    async def test_client_should_succeed_on_first_attempt(
        self,
        create_multi_client: Callable[[ResilienceStrategy, Iterable[HTTPStatus], Iterable[float]], MultiClient],
    ) -> None:
        strategy = ResilienceStrategy(latency_budget=timedelta(seconds=1), max_retries=1)
        outcomes = [HTTPStatus.OK]
        delays = [0.1]
        client = create_multi_client(strategy, outcomes, delays)

        result = await client.request(payload={})

        assert result == HTTPStatus.OK
        client.sender.send.assert_called_once()

    async def test_client_should_rotate_senders_on_retries(
        self,
        create_multi_client: Callable[[ResilienceStrategy, Iterable[HTTPStatus], Iterable[float]], MultiClient],
    ) -> None:
        strategy = ResilienceStrategy(
            latency_budget=timedelta(seconds=5), max_retries=3, fast_errors=(HTTPStatus.BAD_REQUEST,)
        )
        outcomes = [HTTPStatus.INTERNAL_SERVER_ERROR, HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.OK]
        delays = [0.1, 0.1, 0.1]
        client = create_multi_client(strategy, outcomes, delays)

        result = await client.request(payload={})

        assert result == HTTPStatus.OK
        for sender in client.senders:
            sender.send.assert_called_once()

    async def test_client_should_exhaust_strategy_after_max_retries(
        self,
        create_multi_client: Callable[[ResilienceStrategy, Iterable[HTTPStatus], Iterable[float]], MultiClient],
    ) -> None:
        strategy = ResilienceStrategy(latency_budget=timedelta(seconds=2), max_retries=7)
        outcomes = [
            HTTPStatus.INTERNAL_SERVER_ERROR,
            HTTPStatus.INTERNAL_SERVER_ERROR,
            HTTPStatus.INTERNAL_SERVER_ERROR,
        ]
        delays = [0.1, 0.1, 0.1]
        client = create_multi_client(strategy, outcomes, delays)

        with pytest.raises(ResilienceStrategyExhausted) as exc_info:
            await client.request(payload={})

        assert exc_info.value.reason == ExhaustedReason.MAX_RETRIES_EXCEEDED
        total_calls = sum(sender.send.call_count for sender in client.senders)
        assert total_calls == strategy.max_retries

    async def test_client_should_exhaust_strategy_on_latency_budget(
        self,
        create_multi_client: Callable[[ResilienceStrategy, Iterable[HTTPStatus], Iterable[float]], MultiClient],
    ) -> None:
        strategy = ResilienceStrategy(latency_budget=timedelta(seconds=0.25), max_retries=5)
        outcomes = [HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.SERVICE_UNAVAILABLE]
        delays = [0.1, 0.1, 0.1]
        client = create_multi_client(strategy, outcomes, delays)

        with pytest.raises(ResilienceStrategyExhausted) as exc_info:
            await client.request(payload={})

        assert exc_info.value.reason == ExhaustedReason.LATENCY_BUDGET_EXHAUSTED
        total_calls = sum(sender.send.call_count for sender in client.senders)
        assert total_calls <= strategy.max_retries


@pytest.mark.asyncio
class TestHedgingMultiClientCapabilities:
    async def test_client_should_not_hedge_requests_when_hedging_delay_has_not_been_exceeded(
        self,
        create_multi_client: Callable[[ResilienceStrategy, Iterable[HTTPStatus], Iterable[float]], HedgingMultiClient],
    ) -> None:
        strategy = ResilienceStrategy(
            latency_budget=timedelta(seconds=5),
            max_retries=1,
            extra_strategy=HedgingStrategy(hedging_delay=timedelta(seconds=1)),
        )
        outcomes = [HTTPStatus.OK, HTTPStatus.OK, HTTPStatus.OK]
        delays = [0.1, 0.1, 0.1]
        client = create_multi_client(strategy, outcomes, delays)

        result = await client.request(payload={})

        assert result == HTTPStatus.OK
        total_calls = sum(sender.send.call_count for sender in client.senders)
        assert total_calls == 1

    async def test_client_should_hedge_requests(
        self,
        create_multi_client: Callable[[ResilienceStrategy, Iterable[HTTPStatus], Iterable[float]], HedgingMultiClient],
    ) -> None:
        strategy = ResilienceStrategy(
            latency_budget=timedelta(seconds=5),
            max_retries=1,
            extra_strategy=HedgingStrategy(hedging_delay=timedelta(milliseconds=100)),
        )
        outcomes = [HTTPStatus.GATEWAY_TIMEOUT, HTTPStatus.OK, HTTPStatus.OK, HTTPStatus.OK, HTTPStatus.GATEWAY_TIMEOUT]
        delays = [0.5, 0.1, 0.1, 0.1, 0.5]
        client = create_multi_client(strategy, outcomes, delays)

        result = await client.request(payload={})

        assert result == HTTPStatus.OK
        for sender in client.senders:
            sender.send.assert_called_once()

    async def test_client_should_exhaust_strategy_with_hedging(
        self,
        create_multi_client: Callable[[ResilienceStrategy, Iterable[HTTPStatus], Iterable[float]], HedgingMultiClient],
    ) -> None:
        strategy = ResilienceStrategy(
            latency_budget=timedelta(milliseconds=300),
            max_retries=1,
            extra_strategy=HedgingStrategy(hedging_delay=timedelta(milliseconds=50)),
        )
        outcomes = [
            HTTPStatus.GATEWAY_TIMEOUT,
            HTTPStatus.GATEWAY_TIMEOUT,
            HTTPStatus.GATEWAY_TIMEOUT,
        ]
        delays = [0.5, 0.5, 0.5]
        client = create_multi_client(strategy, outcomes, delays)

        with pytest.raises(ResilienceStrategyExhausted) as exc_info:
            await client.request(payload={})

        assert exc_info.value.reason == ExhaustedReason.LATENCY_BUDGET_EXHAUSTED
        total_calls = sum(sender.send.call_count for sender in client.senders)
        assert total_calls == len(client.senders)


@pytest.mark.asyncio
class TestMultiClientWithCircuitBreaker:

    async def test_circuit_breaker_allows_requests_when_under_threshold(
        self,
        create_multi_client: Callable[
            [ResilienceStrategy, Iterable[HTTPStatus], Iterable[float]], CircuitBreakerMultiClient
        ],
    ) -> None:
        strategy = ResilienceStrategy(
            latency_budget=timedelta(seconds=1),
            max_retries=5,
            extra_strategy=CircuitBreakerStrategy(
                failure_threshold=0.5,
                recovery_timeout=timedelta(seconds=1),
                window_size=4,
            ),
        )
        outcomes = [HTTPStatus.INTERNAL_SERVER_ERROR, HTTPStatus.INTERNAL_SERVER_ERROR, HTTPStatus.OK]
        delays = [0.1, 0.1, 0.1]
        client = create_multi_client(strategy, outcomes, delays)

        result = await client.request(payload={})

        first, second, third = (
            client._managed_senders[client.senders[0]],
            client._managed_senders[client.senders[1]],
            client._managed_senders[client.senders[2]],
        )
        assert result == HTTPStatus.OK
        assert first.is_circuit_open and first.failure_rate == 1.0
        assert second.is_circuit_open and second.failure_rate == 1.0
        assert not third.is_circuit_open and third.failure_rate == 0.0

    async def test_circuit_breaker_opens_circuit_on_exceeding_failure_threshold(
        self,
        create_multi_client: Callable[
            [ResilienceStrategy, Iterable[HTTPStatus], Iterable[float]], CircuitBreakerMultiClient
        ],
    ) -> None:
        strategy = ResilienceStrategy(
            latency_budget=timedelta(seconds=5),
            max_retries=3,
            extra_strategy=CircuitBreakerStrategy(
                failure_threshold=0.5,
                recovery_timeout=timedelta(seconds=2),
                window_size=4,
            ),
        )
        outcomes = [
            HTTPStatus.INTERNAL_SERVER_ERROR,
            HTTPStatus.INTERNAL_SERVER_ERROR,
            HTTPStatus.INTERNAL_SERVER_ERROR,
        ]
        delays = [0.1, 0.1, 0.1]
        client = create_multi_client(strategy, outcomes, delays)

        with pytest.raises(ResilienceStrategyExhausted) as exc_info:
            await client.request(payload={})

        assert exc_info.value.reason == ExhaustedReason.CIRCUIT_BREAKER_OPEN
        first, second, third = (
            client._managed_senders[client.senders[0]],
            client._managed_senders[client.senders[1]],
            client._managed_senders[client.senders[2]],
        )
        assert first.is_circuit_open and first.failure_rate == 1.0
        assert second.is_circuit_open and second.failure_rate == 1.0
        assert third.is_circuit_open and third.failure_rate == 1.0
