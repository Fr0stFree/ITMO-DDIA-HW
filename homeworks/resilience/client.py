import asyncio
from http import HTTPStatus
import time
from typing import Any, Literal, override
from datetime import timedelta

from resilience.strategies import (
    ResilienceStrategy,
    ResilienceStrategyExhausted,
    ExhaustedReason,
)
from resilience.sender import ISender


class Client:
    def __init__(self, strategy: ResilienceStrategy, sender: ISender) -> None:
        self._strategy = strategy
        self._sender = sender
        self._current_attempt = 0
        self._time_spent = timedelta(0)

    @property
    def sender(self) -> ISender:
        return self._sender

    @property
    def strategy(self) -> ResilienceStrategy:
        return self._strategy

    def _select_sender(self) -> ISender:
        return self._sender

    async def request(self, payload: Any) -> Literal[HTTPStatus.OK]:
        if self._current_attempt >= self._strategy.max_retries:
            raise ResilienceStrategyExhausted(ExhaustedReason.MAX_RETRIES_EXCEEDED)

        remaining_budget = self._strategy.latency_budget - self._time_spent
        if remaining_budget <= timedelta(0):
            raise ResilienceStrategyExhausted(reason=ExhaustedReason.LATENCY_BUDGET_EXHAUSTED)

        start_time = time.monotonic()
        try:
            task = self._make_request(payload)
            result = await asyncio.wait_for(task, timeout=remaining_budget.total_seconds())
        except asyncio.TimeoutError as error:
            raise ResilienceStrategyExhausted(reason=ExhaustedReason.LATENCY_BUDGET_EXHAUSTED) from error

        if result in self._strategy.fast_errors:
            raise ResilienceStrategyExhausted(reason=ExhaustedReason.NON_RETRYABLE_ERROR)

        if result == HTTPStatus.OK:
            return result

        end_time = time.monotonic()
        self._time_spent += timedelta(seconds=(end_time - start_time))
        self._current_attempt += 1

        return await self.request(payload)

    async def _make_request(self, payload: Any) -> HTTPStatus:
        sender = self._select_sender()
        task = sender.send(payload)
        result = await task
        return result


class BackoffClient(Client):

    @override
    async def _make_request(self, payload: Any) -> HTTPStatus:
        if self._current_attempt > 0:
            await self._execute_backoff()

        return await super()._make_request(payload)

    async def _execute_backoff(self) -> None:
        initial, factor = (
            self._strategy.extra_strategy.initial_delay,
            self._strategy.extra_strategy.backoff_factor,
        )
        delay = initial.total_seconds() * (factor ** (self._current_attempt - 1))
        await self._wait(delay)

    async def _wait(self, delay: float) -> None:
        await asyncio.sleep(delay)
