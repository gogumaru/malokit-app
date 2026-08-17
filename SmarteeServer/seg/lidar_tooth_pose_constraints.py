"""Strict, field-local LiDAR constraints for individual Stage-2 tooth poses."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from seg.lidar_ssm_constraints import DIRECT_FIELDS, FIELD_TO_PHOTO_INDEX


@dataclass(frozen=True)
class LiDARToothPoseConfiguration:
    minimum_detector_confidence: float = 0.80
    minimum_depth_confidence: int = 2
    minimum_voxel_count_per_field: int = 25
    minimum_later_keyframes: int = 2
    # Each field independently guesses which tooth is which from its own 2D
    # image — there's no cross-field matching, so "two fields agreeing" is
    # really "two independent guesses happened to land on the same tooth".
    # Requiring the full minimum_later_keyframes bar from *every* field is
    # stricter than needed: a tooth is still confirmed by two genuinely
    # independent camera angles as long as at least one field clears the
    # full bar — the other(s) only need to weakly corroborate it.
    minimum_later_keyframes_secondary_field: int = 1
    # front/leftLateral/rightLateral must first guess an ambiguous upper/
    # lower row split before slotting a tooth, so a lone assignment there
    # needs stronger proof than mandibular/maxillary's direct, unambiguous
    # alignment: near-full tracking across the whole keyframe sweep, not
    # just the ordinary two-later-keyframe bar.
    minimum_later_keyframes_lone_ambiguous_field: int = 5
    minimum_distinct_fields: int = 2
    huber_delta_metres: float = 0.002
    correspondence_gate_metres: float = 0.006
    minimum_bootstrap_pair_count: int = 30
    maximum_bootstrap_translation_metres: float = 0.012
    weight: float = 0.02


@dataclass(frozen=True)
class LiDARToothPoseConstraint:
    original_tooth_index: int
    slot_id: str
    photo_index: int
    field: str
    points_k0_metres: np.ndarray
    contributing_keyframes: tuple[str, ...]
    configuration: LiDARToothPoseConfiguration
    calibrated_rgb_depth: bool = False


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _metadata_is_eligible(metadata: dict) -> bool:
    return (
        metadata.get("schemaVersion") == 4
        and metadata.get("isDirectView") is True
        and metadata.get("ssmDepthEligible") is True
        and metadata.get("trackingState") == "normal"
        and metadata.get("matrixLayout") == "column-major"
        and metadata.get("coordinateSystem") == "ARKit camera-to-world"
    )


def _original_index(slot_id: str) -> int | None:
    if not isinstance(slot_id, str) or len(slot_id) != 4 or slot_id[1] != "-":
        return None
    try:
        ordinal = int(slot_id[2:])
    except ValueError:
        return None
    if not 1 <= ordinal <= 14 or slot_id[0] not in ("U", "L"):
        return None
    return ordinal - 1 if slot_id[0] == "U" else 14 + ordinal - 1


def _load_cloud_arrays(view: Path):
    payload = _read_json(view / "dental_cloud.json")
    if payload is None or payload.get("schemaVersion") != 1:
        raise ValueError("malformed_cloud")
    try:
        with np.load(view / "dental_cloud.npz", allow_pickle=False) as cloud:
            arrays = {
                key: np.asarray(cloud[key])
                for key in ("pointK0", "keyframeID", "slotID", "detectorConfidence", "depthConfidence")
            }
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ValueError("missing_slot_provenance") from error
    points = np.asarray(arrays["pointK0"], dtype=np.float64)
    count = len(points)
    if points.ndim != 2 or points.shape[1:] != (3,) or not np.isfinite(points).all():
        raise ValueError("malformed_cloud")
    if not isinstance(payload.get("pointCount"), int) or payload["pointCount"] != count:
        raise ValueError("malformed_cloud")
    if any(len(np.asarray(value).reshape(-1)) != count for key, value in arrays.items() if key != "pointK0"):
        raise ValueError("malformed_cloud")
    return points, {key: np.asarray(value).reshape(-1) for key, value in arrays.items() if key != "pointK0"}


def load_lidar_tooth_pose_constraints(
    lidar_root: Path,
    capture_tag: str,
    active_original_indices: np.ndarray,
    configuration: LiDARToothPoseConfiguration = LiDARToothPoseConfiguration(),
) -> tuple[dict[int, tuple[LiDARToothPoseConstraint, ...]], dict[str, str]]:
    """Load only repeatable high-confidence per-tooth points in their own K0 frames."""

    active = set(int(value) for value in np.asarray(active_original_indices, dtype=np.intp).reshape(-1))
    if any(index < 0 or index >= 28 for index in active):
        raise ValueError("active_original_indices must contain original SSM indices in [0, 27]")
    root = Path(lidar_root) / capture_tag
    accepted_by_tooth: dict[int, list[LiDARToothPoseConstraint]] = {}
    skipped: dict[str, str] = {}
    for field in DIRECT_FIELDS:
        view = root / field
        if not view.is_dir():
            continue
        try:
            points, arrays = _load_cloud_arrays(view)
        except ValueError as error:
            skipped[field] = str(error)
            continue
        slots = np.asarray(arrays["slotID"], dtype=str)
        if not np.any(slots != ""):
            skipped[field] = "missing_slot_provenance"
            continue
        for slot_id in sorted(set(slots[slots != ""])):
            key = f"{slot_id}@{field}"
            original_index = _original_index(str(slot_id))
            if original_index is None or original_index not in active:
                skipped[key] = "unknown_or_inactive_slot"
                continue
            matching = slots == slot_id
            high_quality = matching & (np.asarray(arrays["depthConfidence"], dtype=np.int64) >= configuration.minimum_depth_confidence) & (np.asarray(arrays["detectorConfidence"], dtype=np.float64) >= configuration.minimum_detector_confidence)
            if int(np.count_nonzero(high_quality)) < configuration.minimum_voxel_count_per_field:
                skipped[key] = "insufficient_high_confidence_points"
                continue
            keyframes = tuple(sorted(set(str(value) for value in arrays["keyframeID"][high_quality])))
            later_count = sum(keyframe.startswith("K") and keyframe != "K0" for keyframe in keyframes)
            if "K0" not in keyframes or later_count < configuration.minimum_later_keyframes_secondary_field:
                skipped[key] = "insufficient_repeated_keyframes"
                continue
            metadata = [_read_json(view / f"{keyframe}.metadata.json") for keyframe in keyframes]
            if any(item is None or not _metadata_is_eligible(item) for item in metadata):
                skipped[key] = "mirror_or_ineligible_view"
                continue
            accepted_by_tooth.setdefault(original_index, []).append(
                LiDARToothPoseConstraint(
                    original_tooth_index=original_index,
                    slot_id=str(slot_id),
                    photo_index=FIELD_TO_PHOTO_INDEX[field],
                    field=field,
                    points_k0_metres=points[high_quality],
                    contributing_keyframes=keyframes,
                    configuration=configuration,
                    calibrated_rgb_depth=all(
                        isinstance(item.get("rgbCrop"), dict)
                        and isinstance(item.get("orientation"), str)
                        for item in metadata
                    ),
                )
            )

    def _later_count(value: LiDARToothPoseConstraint) -> int:
        return sum(
            keyframe.startswith("K") and keyframe != "K0" for keyframe in value.contributing_keyframes
        )

    constraints = {}
    for original_index, values in accepted_by_tooth.items():
        # mandibular/maxillary see one whole arch head-on and assign slots
        # via direct DP alignment (assign_keyframe_slots' photo_index in
        # (0, 1) path) with no row-split guesswork involved. That's the same
        # view tooth_inventory.py (Milestone 1) already trusts alone for
        # patient identity — so a lone strong assignment from one of these
        # fields is as trustworthy as two independent guesses. front/
        # leftLateral/rightLateral must first guess an ambiguous upper/lower
        # split, so a lone assignment from those is trusted only when it
        # tracked almost the entire keyframe sweep — near-full tracking is
        # the compensating evidence for the row-split guess never being
        # cross-checked by a second field.
        trusted_anchor = any(
            _later_count(value) >= (
                configuration.minimum_later_keyframes
                if FIELD_TO_PHOTO_INDEX[value.field] in (0, 1)
                else configuration.minimum_later_keyframes_lone_ambiguous_field
            )
            for value in values
        )
        if len({value.field for value in values}) < configuration.minimum_distinct_fields:
            if not trusted_anchor:
                skipped[values[0].slot_id] = "insufficient_distinct_fields"
                continue
        elif max(_later_count(value) for value in values) < configuration.minimum_later_keyframes:
            skipped[values[0].slot_id] = "no_field_meets_strong_evidence_bar"
            continue
        constraints[original_index] = tuple(values)
    return constraints, dict(sorted(skipped.items()))
