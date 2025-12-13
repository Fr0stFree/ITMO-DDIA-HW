from http import HTTPStatus
from typing import Callable
import pytest
from datetime import timedelta
from unittest.mock import call

from resilience.sender import HTTPStatus
from resilience.client import BackoffClient, Client
from resilience.strategies import ResilienceStrategy, ResilienceStrategyExhausted, ExhaustedReason, BackoffStrategy


@pytest.mark.asyncio
class TestBasicClientCapabilities:
    async def test_client_should_succeed_on_first_attempt(
        self,
        create_client: Callable[[ResilienceStrategy, HTTPStatus, float], Client],
    ) -> None:
        strategy = ResilienceStrategy(latency_budget=timedelta(seconds=1), max_retries=1)
        outcome, delay = HTTPStatus.OK, 0.1
        client = create_client(strategy, outcome, delay)

        result = await client.request(payload={})

        assert result == HTTPStatus.OK
        client.sender.send.assert_called_once()

    async def test_client_fail_on_any_error(
        self,
        create_client: Callable[[ResilienceStrategy, HTTPStatus, float], Client],
    ) -> None:
        strategy = ResilienceStrategy(latency_budget=timedelta(seconds=1), max_retries=1)
        outcome, delay = HTTPStatus.INTERNAL_SERVER_ERROR, 0.1
        client = create_client(strategy, outcome, delay)

        with pytest.raises(ResilienceStrategyExhausted) as exc_info:
            await client.request(payload={})

        assert exc_info.value.reason == ExhaustedReason.MAX_RETRIES_EXCEEDED
        client.sender.send.assert_called_once()

    async def test_client_should_fail_on_latency_budget_exhaustion(
        self,
        create_client: Callable[[ResilienceStrategy, HTTPStatus, float], Client],
    ) -> None:
        strategy = ResilienceStrategy(
            latency_budget=timedelta(seconds=0.05),
            max_retries=1,
            fast_errors=(HTTPStatus.BAD_REQUEST,),
        )
        outcome, delay = HTTPStatus.OK, 0.1
        client = create_client(strategy, outcome, delay)

        with pytest.raises(ResilienceStrategyExhausted) as exc_info:
            await client.request(payload={})

        assert exc_info.value.reason == ExhaustedReason.LATENCY_BUDGET_EXHAUSTED
        client.sender.send.assert_called_once()


@pytest.mark.asyncio
class TestClientRetryCapabilities:
    async def test_client_should_retry_on_any_error(
        self,
        create_client: Callable[[ResilienceStrategy, HTTPStatus, float], Client],
    ) -> None:
        strategy = ResilienceStrategy(
            latency_budget=timedelta(seconds=1),
            max_retries=3,
            fast_errors=(HTTPStatus.BAD_REQUEST,),
        )
        outcome, delay = HTTPStatus.INTERNAL_SERVER_ERROR, 0.1
        client = create_client(strategy, outcome, delay)

        with pytest.raises(ResilienceStrategyExhausted) as exc_info:
            await client.request(payload={})

        assert exc_info.value.reason == ExhaustedReason.MAX_RETRIES_EXCEEDED
        assert client.sender.send.call_count == strategy.max_retries

    async def test_client_should_stop_retries_on_fast_error(
        self,
        create_client: Callable[[ResilienceStrategy, HTTPStatus, float], Client],
    ) -> None:
        strategy = ResilienceStrategy(
            latency_budget=timedelta(seconds=1),
            max_retries=3,
            fast_errors=(HTTPStatus.BAD_REQUEST,),
        )
        outcome, delay = HTTPStatus.BAD_REQUEST, 0.1
        client = create_client(strategy, outcome, delay)

        with pytest.raises(ResilienceStrategyExhausted) as exc_info:
            await client.request(payload={})

        assert exc_info.value.reason == ExhaustedReason.NON_RETRYABLE_ERROR
        client.sender.send.assert_called_once()

    async def test_client_should_stop_retries_on_budget_exhaustion(
        self,
        create_client: Callable[[ResilienceStrategy, HTTPStatus, float], Client],
    ) -> None:
        strategy = ResilienceStrategy(
            latency_budget=timedelta(seconds=0.25),
            max_retries=5,
            fast_errors=(HTTPStatus.BAD_REQUEST,),
        )
        outcome, delay = HTTPStatus.INTERNAL_SERVER_ERROR, 0.1
        client = create_client(strategy, outcome, delay)

        with pytest.raises(ResilienceStrategyExhausted) as exc_info:
            await client.request(payload={})

        assert exc_info.value.reason == ExhaustedReason.LATENCY_BUDGET_EXHAUSTED
        assert client.sender.send.call_count < strategy.max_retries


@pytest.mark.asyncio
class TestClientBackoffCapabilities:
    async def test_client_should_apply_backoff_between_retries(
        self,
        create_client: Callable[[ResilienceStrategy, HTTPStatus, float], BackoffClient],
    ) -> None:
        strategy = ResilienceStrategy(
            latency_budget=timedelta(seconds=5),
            max_retries=4,
            fast_errors=(HTTPStatus.BAD_REQUEST,),
            extra_strategy=BackoffStrategy(
                initial_delay=timedelta(milliseconds=100),
                backoff_factor=2.0,
            ),
        )
        outcome, delay = HTTPStatus.INTERNAL_SERVER_ERROR, 0.1
        client = create_client(strategy, outcome, delay)

        print(f"{type(client)=}")
        with pytest.raises(ResilienceStrategyExhausted) as exc_info:
            await client.request(payload={})

        assert exc_info.value.reason == ExhaustedReason.MAX_RETRIES_EXCEEDED
        assert client.sender.send.call_count == strategy.max_retries
        client._wait.assert_has_awaits(
            [
                call(0.1),  # 100ms
                call(0.2),  # 200ms
                call(0.4),  # 400ms
            ]
        )

    async def test_client_backoff_should_respect_latency_budget(
        self,
        create_client: Callable[[ResilienceStrategy, HTTPStatus, float], BackoffClient],
    ) -> None:
        strategy = ResilienceStrategy(
            latency_budget=timedelta(seconds=0.5),
            max_retries=5,
            fast_errors=(HTTPStatus.BAD_REQUEST,),
            extra_strategy=BackoffStrategy(
                initial_delay=timedelta(milliseconds=200),
                backoff_factor=2.0,
            ),
        )
        outcome, delay = HTTPStatus.INTERNAL_SERVER_ERROR, 0.1
        client = create_client(strategy, outcome, delay)

        with pytest.raises(ResilienceStrategyExhausted) as exc_info:
            await client.request(payload={})

        assert exc_info.value.reason == ExhaustedReason.LATENCY_BUDGET_EXHAUSTED
        assert client.sender.send.call_count < strategy.max_retries
        client._wait.assert_has_awaits([call(0.2)])  # 200ms - first backoff only

    async def test_client_no_backoff_when_initial_delay_zero(
        self,
        create_client: Callable[[ResilienceStrategy, HTTPStatus, float], BackoffClient],
    ) -> None:
        strategy = ResilienceStrategy(
            latency_budget=timedelta(seconds=1),
            max_retries=3,
            fast_errors=(HTTPStatus.BAD_REQUEST,),
            extra_strategy=BackoffStrategy(
                initial_delay=timedelta(0),
                backoff_factor=2.0,
            ),
        )
        outcome, delay = HTTPStatus.INTERNAL_SERVER_ERROR, 0.1
        client = create_client(strategy, outcome, delay)

        with pytest.raises(ResilienceStrategyExhausted) as exc_info:
            await client.request(payload={})

        assert exc_info.value.reason == ExhaustedReason.MAX_RETRIES_EXCEEDED
        assert client.sender.send.call_count == strategy.max_retries
        client._wait.assert_has_awaits(
            [
                call(0.0),
                call(0.0),
            ]
        )
