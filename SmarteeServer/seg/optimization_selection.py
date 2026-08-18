"""Small, dependency-free helpers for retaining the best optimizer state."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass


@dataclass
class BestOptimizationState:
    """The strictly lowest-loss parameter snapshot seen in one optimizer stage."""

    loss: float
    parameters: dict

    def __post_init__(self) -> None:
        self.loss = float(self.loss)
        self.parameters = deepcopy(self.parameters)

    def consider(self, loss: float, parameters: dict) -> bool:
        """Retain a deep-copied snapshot only when its loss improves strictly."""

        loss = float(loss)
        if loss >= self.loss:
            return False
        self.loss = loss
        self.parameters = deepcopy(parameters)
        return True
