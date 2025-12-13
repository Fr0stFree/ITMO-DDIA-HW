from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from http import HTTPStatus


@dataclass
class HedgingStrategy:
    hedging_delay: timedelta


@dataclass
class BackoffStrategy:
    initial_delay: timedelta
    backoff_factor: float


@dataclass
class CircuitBreakerStrategy:
    window_size: int
    failure_threshold: float
    recovery_timeout: timedelta


@dataclass
class ResilienceStrategy:
    max_retries: int
    latency_budget: timedelta
    fast_errors: tuple[HTTPStatus, ...] = tuple()
    extra_strategy: BackoffStrategy | HedgingStrategy | CircuitBreakerStrategy | None = None


class ExhaustedReason(Enum):
    MAX_RETRIES_EXCEEDED = "Max retries exceeded"
    LATENCY_BUDGET_EXHAUSTED = "Latency budget exhausted"
    NON_RETRYABLE_ERROR = "Non-retryable error encountered"
    CIRCUIT_BREAKER_OPEN = "Circuit breaker is open"


class ResilienceStrategyExhausted(Exception):
    def __init__(self, reason: ExhaustedReason) -> None:
        super().__init__(reason.value)
        self.reason = reason
