from __future__ import annotations
from abc import ABC, abstractmethod
import pandas as pd

class BaseStrategy(ABC):
    @abstractmethod
    def regime(self, d1: pd.DataFrame, h4: pd.DataFrame, h1: pd.DataFrame) -> dict: ...
    @abstractmethod
    def signal(self, m15: pd.DataFrame, bias: str) -> dict: ...
