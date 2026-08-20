"""Dependency-light segmentation predictions shared across reconstruction layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np


@dataclass(frozen=True)
class ToothInstancePrediction:
    """One view-local filled tooth mask and its detector metadata."""

    local_id: str
    mask: np.ndarray
    confidence: float
    bbox_xywh: Tuple[int, int, int, int]
    centroid_xy: Tuple[float, float]
    area_pixels: int


@dataclass(frozen=True)
class EdgePrediction:
    """The legacy combined edge map plus optional filled tooth instances."""

    edge_mask: np.ndarray
    source: str
    instances: Tuple[ToothInstancePrediction, ...] = ()
