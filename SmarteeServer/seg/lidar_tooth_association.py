"""Conservative association of one RF-DETR tooth mask with LiDAR depth."""

from __future__ import annotations

from collections import Counter
from typing import Dict

import numpy as np
from scipy.ndimage import binary_erosion

from seg.lidar_keyframe_geometry import (
    back_project_depth_pixel,
    map_cropped_rgb_pixel_to_depth,
    map_rgb_pixel_to_depth,
    transform_point_to_reference,
)


MIN_DEPTH_METRES = 0.05
MAX_DEPTH_METRES = 2.0


def _record(
    keyframe_id: str,
    instance_id: str,
    slot_id: str | None,
    detector_confidence: float,
    depth_confidence: int | None,
    rgb_xy: tuple[int, int],
    depth_xy: tuple[int, int],
    point_k0: tuple[float, float, float] | None,
    reason: str | None,
) -> dict:
    return {
        "keyframeID": keyframe_id,
        "instanceID": instance_id,
        "slotID": slot_id,
        "detectorConfidence": float(detector_confidence),
        "depthConfidence": depth_confidence,
        "rgbXY": [int(rgb_xy[0]), int(rgb_xy[1])],
        "depthXY": [int(depth_xy[0]), int(depth_xy[1])],
        "pointK0": list(point_k0) if point_k0 is not None else None,
        "rejectionReason": reason,
    }


def associate_instance_depth(
    mask: np.ndarray,
    keyframe_id: str,
    instance_id: str,
    detector_confidence: float,
    depth_metres: np.ndarray,
    confidence_values: np.ndarray,
    metadata: Dict[str, object],
    slot_id: str | None = None,
) -> dict:
    """Return accepted/rejected point associations for a single filled tooth mask."""

    detector_confidence = float(detector_confidence)
    if not np.isfinite(detector_confidence) or not 0.0 <= detector_confidence <= 1.0:
        raise ValueError("detector_confidence must be finite and in [0, 1].")
    foreground = np.asarray(mask) > 127
    if foreground.ndim != 2:
        raise ValueError("mask must be a two-dimensional filled mask.")
    depth = np.asarray(depth_metres, dtype=np.float32)
    confidence = np.asarray(confidence_values)
    if depth.ndim != 2 or confidence.shape != depth.shape:
        raise ValueError("depth and confidence grids must be matching two-dimensional arrays.")
    rgb_height, rgb_width = foreground.shape
    depth_height, depth_width = depth.shape
    try:
        intrinsics = metadata["intrinsicMatrix"]
        reference_size = (
            int(metadata["intrinsicReferenceWidth"]),
            int(metadata["intrinsicReferenceHeight"]),
        )
        transform = metadata["cameraToReferenceTransform"]
        rgb_crop = metadata.get("rgbCrop")
        orientation = metadata.get("orientation")
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"missing usable keyframe calibration: {error}") from error

    eroded = binary_erosion(
        foreground, structure=np.ones((3, 3), dtype=bool), border_value=0
    )
    accepted = []
    rejected = []
    rejection_counts: Counter[str] = Counter()
    for rgb_y, rgb_x in np.argwhere(foreground):
        if rgb_crop is not None or orientation is not None:
            if rgb_crop is None or orientation is None:
                raise ValueError("RGB crop and orientation metadata must be supplied together")
            depth_x, depth_y = map_cropped_rgb_pixel_to_depth(
                int(rgb_x),
                int(rgb_y),
                rgb_width,
                rgb_height,
                reference_size[0],
                reference_size[1],
                depth_width,
                depth_height,
                rgb_crop,
                str(orientation),
            )
        else:
            depth_x, depth_y = map_rgb_pixel_to_depth(
                int(rgb_x), int(rgb_y), rgb_width, rgb_height, depth_width, depth_height
            )
        depth_confidence = int(confidence[depth_y, depth_x])
        if not eroded[rgb_y, rgb_x]:
            reason = "mask_edge_eroded"
            rejected.append(_record(keyframe_id, instance_id, slot_id, detector_confidence, depth_confidence, (rgb_x, rgb_y), (depth_x, depth_y), None, reason))
            rejection_counts[reason] += 1
            continue
        depth_value = float(depth[depth_y, depth_x])
        if depth_confidence == 0:
            reason = "depth_confidence_zero"
        elif not np.isfinite(depth_value):
            reason = "depth_not_finite"
        elif not MIN_DEPTH_METRES <= depth_value <= MAX_DEPTH_METRES:
            reason = "depth_out_of_range"
        else:
            reason = None
        if reason is not None:
            rejected.append(_record(keyframe_id, instance_id, slot_id, detector_confidence, depth_confidence, (rgb_x, rgb_y), (depth_x, depth_y), None, reason))
            rejection_counts[reason] += 1
            continue
        try:
            camera_point = back_project_depth_pixel(
                depth_x, depth_y, depth_value, intrinsics, reference_size, (depth_width, depth_height)
            )
            point_k0 = transform_point_to_reference(camera_point, transform)
        except ValueError:
            reason = "invalid_calibration"
            rejected.append(_record(keyframe_id, instance_id, slot_id, detector_confidence, depth_confidence, (rgb_x, rgb_y), (depth_x, depth_y), None, reason))
            rejection_counts[reason] += 1
            continue
        accepted.append(_record(keyframe_id, instance_id, slot_id, detector_confidence, depth_confidence, (rgb_x, rgb_y), (depth_x, depth_y), point_k0, None))

    return {
        "accepted": accepted,
        "rejected": rejected,
        "rejectionCounts": dict(sorted(rejection_counts.items())),
    }
