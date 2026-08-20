"""Voxel-deduplicated, provenance-preserving Figure-8 dental cloud output."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np


def apply_propagated_slots(points: Iterable[dict], assignments: dict[str, dict[str, str]]) -> list[dict]:
    """Return records relabeled only by authoritative K0-propagated assignments."""

    relabeled = []
    for record in points:
        value = dict(record)
        keyframe_id = str(value.get("keyframeID", ""))
        instance_id = str(value.get("instanceID", ""))
        value["slotID"] = assignments.get(keyframe_id, {}).get(instance_id)
        relabeled.append(value)
    return relabeled


def _voxel_key(point_xyz: list[float], voxel_size_metres: float) -> tuple[int, int, int]:
    return tuple(math.floor(float(value) / voxel_size_metres) for value in point_xyz)


def _rank(record: dict) -> tuple:
    """Higher depth confidence wins, then detector confidence, then stable identity."""

    return (
        -int(record["depthConfidence"]),
        -float(record["detectorConfidence"]),
        str(record["keyframeID"]),
        str(record["instanceID"]),
        tuple(record["rgbXY"]),
    )


def fuse_dental_points(points: Iterable[dict], voxel_size_metres: float = 0.002) -> dict:
    """Keep one highest-quality accepted source record per 2 mm K0-space voxel."""

    voxel_size_metres = float(voxel_size_metres)
    if not math.isfinite(voxel_size_metres) or voxel_size_metres <= 0:
        raise ValueError("voxel_size_metres must be finite and positive.")
    candidates = defaultdict(list)
    rejection_counts: Counter[str] = Counter()
    for record in points:
        reason = record.get("rejectionReason")
        point_k0 = record.get("pointK0")
        if reason is not None:
            rejection_counts[str(reason)] += 1
            continue
        if not isinstance(point_k0, (list, tuple)) or len(point_k0) != 3 or not all(
            math.isfinite(float(value)) for value in point_k0
        ):
            rejection_counts["invalid_point"] += 1
            continue
        candidates[_voxel_key(point_k0, voxel_size_metres)].append(dict(record))

    selected = [min(records, key=_rank) for _, records in sorted(candidates.items())]
    per_keyframe = defaultdict(lambda: {"acceptedPointCount": 0, "instanceCount": 0})
    instance_ids = defaultdict(set)
    for record in selected:
        keyframe_id = str(record["keyframeID"])
        per_keyframe[keyframe_id]["acceptedPointCount"] += 1
        instance_ids[keyframe_id].add(str(record["instanceID"]))
    for keyframe_id, ids in instance_ids.items():
        per_keyframe[keyframe_id]["instanceCount"] = len(ids)
    return {
        "voxelSizeMetres": voxel_size_metres,
        "points": selected,
        "perKeyframe": dict(sorted(per_keyframe.items())),
        "rejectionCounts": dict(sorted(rejection_counts.items())),
    }


def persist_dental_cloud(
    view_directory: Path, fused: dict, rejected_associations: Iterable[dict] = ()
) -> dict:
    """Write a JSON provenance report and compact numeric NPZ without replacing K-frames."""

    root = Path(view_directory)
    root.mkdir(parents=True, exist_ok=True)
    points = list(fused.get("points", []))
    rejected = list(rejected_associations)
    payload = {
        "schemaVersion": 1,
        "voxelSizeMetres": fused["voxelSizeMetres"],
        "pointCount": len(points),
        "perKeyframe": fused.get("perKeyframe", {}),
        "rejectionCounts": fused.get("rejectionCounts", {}),
        "points": points,
        "rejectedAssociations": rejected,
    }
    json_path = root / "dental_cloud.json"
    json_temporary = root / "dental_cloud.json.tmp"
    json_temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    json_temporary.replace(json_path)

    npz_path = root / "dental_cloud.npz"
    npz_temporary = root / "dental_cloud.npz.tmp"
    with npz_temporary.open("wb") as file:
        np.savez_compressed(
            file,
            pointK0=np.asarray([record["pointK0"] for record in points], dtype=np.float32).reshape((-1, 3)),
            keyframeID=np.asarray([record["keyframeID"] for record in points], dtype=str),
            instanceID=np.asarray([record["instanceID"] for record in points], dtype=str),
            slotID=np.asarray([record.get("slotID") or "" for record in points], dtype=str),
            detectorConfidence=np.asarray([record["detectorConfidence"] for record in points], dtype=np.float32),
            depthConfidence=np.asarray([record["depthConfidence"] for record in points], dtype=np.uint8),
            rgbXY=np.asarray([record["rgbXY"] for record in points], dtype=np.int32).reshape((-1, 2)),
            depthXY=np.asarray([record["depthXY"] for record in points], dtype=np.int32).reshape((-1, 2)),
        )
    npz_temporary.replace(npz_path)
    return {
        "pointCount": len(points),
        "voxelSizeMetres": fused["voxelSizeMetres"],
        "perKeyframe": fused.get("perKeyframe", {}),
        "rejectionCounts": fused.get("rejectionCounts", {}),
    }
