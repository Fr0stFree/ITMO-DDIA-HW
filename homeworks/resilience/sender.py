from abc import ABC, abstractmethod
import asyncio
from http import HTTPStatus
from typing import Any


class ISender(ABC):
    
    @abstractmethod
    def send(self, payload: Any) -> asyncio.Task[HTTPStatus]:
        raise NotImplementedError
