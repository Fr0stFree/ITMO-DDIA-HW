import asyncio
from http import HTTPStatus
from typing import Any, Callable, Iterable
from unittest.mock import Mock, AsyncMock

import pytest

from resilience.sender import ISender
from resilience.client import BackoffClient, Client
from resilience.multi_client import HedgingMultiClient, MultiClient, CircuitBreakerMultiClient
from resilience.strategies import BackoffStrategy, ResilienceStrategy, HedgingStrategy, CircuitBreakerStrategy


class TestSender(ISender):
    def __init__(self, outcome: HTTPStatus, delay: float = 0.0) -> None:
        self.outcome = outcome
        self.delay = delay

    async def _simulate_send(self, payload: Any) -> HTTPStatus:
        await asyncio.sleep(self.delay)
        return self.outcome

    def send(self, payload: Any) -> asyncio.Task[HTTPStatus]:
        task = asyncio.create_task(self._simulate_send(payload))
        return task


@pytest.fixture
def create_client() -> Callable[[ResilienceStrategy, HTTPStatus, float], Client | BackoffClient]:
    def _create_client(
        strategy: ResilienceStrategy,
        outcome: HTTPStatus,
        delay: float,
    ) -> Client:
        sender = TestSender(outcome=outcome, delay=delay)
        sender.send = Mock(wraps=sender.send)
        if isinstance(strategy.extra_strategy, BackoffStrategy):
            client = BackoffClient(strategy=strategy, sender=sender)
            client._wait = AsyncMock(wraps=client._wait)
        else:
            client = Client(strategy=strategy, sender=sender)
        return client

    return _create_client


@pytest.fixture
def create_multi_client() -> (
    Callable[[ResilienceStrategy, Iterable[HTTPStatus], Iterable[float]], MultiClient | HedgingMultiClient]
):
    def _create_multi_client(
        strategy: ResilienceStrategy,
        outcomes: Iterable[HTTPStatus],
        delays: Iterable[float],
    ) -> MultiClient:
        senders = []
        for outcome, delay in zip(outcomes, delays):
            sender = TestSender(outcome=outcome, delay=delay)
            sender.send = Mock(wraps=sender.send)
            senders.append(sender)

        if isinstance(strategy.extra_strategy, HedgingStrategy):
            multi_client = HedgingMultiClient(strategy=strategy, senders=senders)
        elif isinstance(strategy.extra_strategy, CircuitBreakerStrategy):
            multi_client = CircuitBreakerMultiClient(strategy=strategy, senders=senders)
        else:
            multi_client = MultiClient(strategy=strategy, senders=senders)
        return multi_client

    return _create_multi_client
