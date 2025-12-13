from collections import deque
from http import HTTPStatus
import itertools
from typing import Sequence, Any, override
import asyncio
from datetime import timedelta, datetime

from resilience.client import Client
from resilience.strategies import (
    ExhaustedReason,
    HedgingStrategy,
    ResilienceStrategy,
    CircuitBreakerStrategy,
    ResilienceStrategyExhausted,
)
from resilience.sender import ISender


class MultiClient(Client):
    def __init__(self, strategy: ResilienceStrategy, senders: Sequence[ISender]) -> None:
        self._senders = senders
        self._senders_cycle = itertools.cycle(senders)
        super().__init__(strategy=strategy, sender=senders[0])

    @property
    def senders(self) -> list[ISender]:
        return list(self._senders)

    @override
    def _select_sender(self) -> ISender:
        self._sender = next(self._senders_cycle)
        return self._sender


class HedgingMultiClient(MultiClient):

    @override
    async def _make_request(self, payload: Any) -> HTTPStatus:
        params: HedgingStrategy = self.strategy.extra_strategy
        main_sender = self._select_sender()
        main_task = main_sender.send(payload)
        try:
            result = await asyncio.wait_for(asyncio.shield(main_task), timeout=params.hedging_delay.total_seconds())
            return result
        except asyncio.TimeoutError:
            other_senders = [sender for sender in self._senders if sender != main_sender]
            tasks = [main_task] + [sender.send(payload) for sender in other_senders]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            for task in pending:
                task.cancel()

            for task in done:
                return await task


### Circuit Breaker Related Code ###


class ManagedSender:
    def __init__(self, strategy: CircuitBreakerStrategy, sender: ISender) -> None:
        self._strategy = strategy
        self._last_results = deque[bool](maxlen=strategy.window_size)
        self._recover_at: datetime = datetime.min
        self._sender = sender

    @property
    def sender(self) -> ISender:
        return self._sender

    def record_success(self) -> None:
        self._last_results.append(True)

    def record_failure(self) -> None:
        self._last_results.append(False)
        failure_rate = self.failure_rate
        if failure_rate >= self._strategy.failure_threshold:
            self._recover_at = datetime.now() + self._strategy.recovery_timeout

    @property
    def failure_rate(self) -> float:
        if not self._last_results:
            return 0.0
        failures = sum(1 for result in self._last_results if not result)
        return failures / len(self._last_results)

    @property
    def recovery_time(self) -> timedelta:
        if self._recover_at is None:
            return timedelta(0)
        return self._recover_at - datetime.now()

    @property
    def is_circuit_open(self) -> bool:
        return datetime.now() < self._recover_at


class CircuitBreakerMultiClient(MultiClient):
    def __init__(self, strategy: ResilienceStrategy, senders: Sequence[ISender]) -> None:
        self._managed_senders = {sender: ManagedSender(strategy.extra_strategy, sender) for sender in senders}
        super().__init__(strategy=strategy, senders=senders)

    @override
    def _select_sender(self) -> ISender:
        sorted_senders = sorted(
            self._managed_senders.values(),
            key=lambda manager: (not manager.is_circuit_open, -manager.failure_rate, manager.recovery_time),
        )
        self._sender = sorted_senders[-1].sender
        return self._sender

    @override
    async def _make_request(self, payload: Any) -> HTTPStatus:
        sender = self._select_sender()
        managed_sender = self._managed_senders[sender]
        if managed_sender.is_circuit_open:  # means that even the best possible sender is open
            raise ResilienceStrategyExhausted(ExhaustedReason.CIRCUIT_BREAKER_OPEN)

        result = await super()._make_request(payload)
        if result == HTTPStatus.OK:
            managed_sender.record_success()
        else:
            managed_sender.record_failure()
        return result
