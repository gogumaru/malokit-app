"""Independent RF-DETR tooth masks for persisted Figure-8 keyframes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, Sequence

import numpy as np
import skimage.io

from seg.prediction_types import EdgePrediction
from seg.rfdetr_bridge import predict_rfdetr_predictions
from seg.lidar_tooth_slots import assign_keyframe_slots


KEYFRAME_IDS = tuple(f"K{index}" for index in range(7))


def _load_metadata(path: Path) -> dict:
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid metadata: {error}") from error
    if not isinstance(metadata, dict):
        raise ValueError("metadata is not an object")
    return metadata


def _eligibility(root: Path, keyframe_id: str) -> tuple[bool, str | None, dict | None]:
    required = [
        root / f"{keyframe_id}.rgb.png",
        root / f"{keyframe_id}.depth.f32",
        root / f"{keyframe_id}.confidence.u8",
        root / f"{keyframe_id}.metadata.json",
    ]
    if not all(path.is_file() for path in required):
        return False, "incomplete_keyframe_bundle", None
    try:
        metadata = _load_metadata(required[-1])
    except ValueError:
        return False, "invalid_metadata", None
    eligible = (
        metadata.get("schemaVersion") == 4
        and metadata.get("isDirectView") is True
        and metadata.get("ssmDepthEligible") is True
        and metadata.get("trackingState") == "normal"
        and metadata.get("matrixLayout") == "column-major"
        and metadata.get("coordinateSystem") == "ARKit camera-to-world"
        and isinstance(metadata.get("cameraToReferenceTransform"), list)
        and len(metadata["cameraToReferenceTransform"]) == 16
    )
    return eligible, None if eligible else "ineligible_keyframe", metadata


def _save_mask(path: Path, mask: np.ndarray, expected_shape: tuple[int, int]) -> None:
    image = ((np.asarray(mask) > 127) * 255).astype(np.uint8)
    if image.shape != expected_shape or not np.any(image):
        raise ValueError(f"invalid filled instance mask: {image.shape}, expected {expected_shape}")
    skimage.io.imsave(str(path), image, check_contrast=False)


def _write_manifest(path: Path, manifest: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def segment_lidar_keyframes(
    view_directory: Path,
    predictor: Callable[[Sequence[str]], Sequence[object]] = predict_rfdetr_predictions,
    field: str | None = None,
    photo_index: int | None = None,
    active_original_indices: np.ndarray | None = None,
) -> Dict[str, object]:
    """Segment independently eligible K0–K6 RGB images with RF-DETR only."""

    root = Path(view_directory)
    if not (root / "figure8_manifest.json").is_file():
        raise ValueError("missing figure8_manifest.json")
    output_directory = root / "segmentation"
    output_directory.mkdir(parents=True, exist_ok=True)
    records: Dict[str, dict] = {}
    eligible_ids = []
    image_paths = []
    for keyframe_id in KEYFRAME_IDS:
        eligible, reason, _ = _eligibility(root, keyframe_id)
        if not eligible:
            records[keyframe_id] = {"backend": None, "instanceCount": 0, "reason": reason}
            continue
        image_path = root / f"{keyframe_id}.rgb.png"
        eligible_ids.append(keyframe_id)
        image_paths.append(str(image_path))

    try:
        predictions = list(predictor(image_paths)) if image_paths else []
        if len(predictions) != len(eligible_ids):
            raise ValueError("RF-DETR returned the wrong number of keyframe predictions")
    except Exception as error:  # RF-DETR failures are diagnostic, never H5 fallbacks.
        for keyframe_id in eligible_ids:
            records[keyframe_id] = {
                "backend": "rfdetr",
                "instanceCount": 0,
                "reason": f"rfdetr_failure: {error}",
            }
    else:
        for keyframe_id, prediction in zip(eligible_ids, predictions):
            if not isinstance(prediction, EdgePrediction) or prediction.source != "rfdetr":
                detail = str(prediction).strip() or "unusable_prediction"
                records[keyframe_id] = {
                    "backend": "rfdetr",
                    "instanceCount": 0,
                    "reason": f"rfdetr_failure: {detail}",
                }
                continue
            rgb = np.asarray(skimage.io.imread(str(root / f"{keyframe_id}.rgb.png")))
            rgb_shape = tuple(rgb.shape[:2])
            instances = []
            try:
                for ordinal, instance in enumerate(prediction.instances):
                    filename = f"{keyframe_id}-instance-{ordinal:03d}.png"
                    _save_mask(output_directory / filename, instance.mask, rgb_shape)
                    instances.append(
                        {
                            "localId": str(instance.local_id),
                            "mask": filename,
                            "confidence": float(instance.confidence),
                            "bboxXYWH": list(instance.bbox_xywh),
                            "centroidXY": list(instance.centroid_xy),
                            "areaPixels": int(instance.area_pixels),
                        }
                    )
            except (OSError, TypeError, ValueError) as error:
                records[keyframe_id] = {
                    "backend": "rfdetr",
                    "instanceCount": 0,
                    "reason": f"rfdetr_failure: {error}",
                }
                continue
            records[keyframe_id] = {
                "backend": "rfdetr",
                "rgbWidth": int(rgb_shape[1]),
                "rgbHeight": int(rgb_shape[0]),
                "instanceCount": len(instances),
                "instances": instances,
                "reason": None,
            }

    manifest = {"schemaVersion": 1, "keyframes": records}
    _write_manifest(output_directory / "instances.json", manifest)
    if field is not None or photo_index is not None or active_original_indices is not None:
        if field is None or photo_index is None or active_original_indices is None:
            raise ValueError("field, photo_index, and active_original_indices must be supplied together")
        slot_keyframes = {}
        for keyframe_id, record in records.items():
            if record.get("reason") is not None:
                slot_keyframes[keyframe_id] = {"assignments": {}, "rejections": {}}
                continue
            width = int(record["rgbWidth"])
            height = int(record["rgbHeight"])
            normalized_instances = [
                {
                    **instance,
                    "normalizedCentroidXY": [
                        float(instance["centroidXY"][0]) / width,
                        float(instance["centroidXY"][1]) / height,
                    ],
                }
                for instance in record.get("instances", [])
            ]
            if keyframe_id == "K0":
                assignments, rejections = assign_keyframe_slots(
                    instances=normalized_instances,
                    photo_index=int(photo_index),
                    active_original_indices=np.asarray(active_original_indices, dtype=np.intp),
                )
            else:
                assignments = {}
                rejections = {
                    str(instance["localId"]): "awaiting_k0_surface_match"
                    for instance in normalized_instances
                }
            slot_keyframes[keyframe_id] = {
                "assignments": assignments,
                "rejections": rejections,
            }
        _write_manifest(
            output_directory / "slot_assignments.json",
            {
                "schemaVersion": 2,
                "field": str(field),
                "photoIndex": int(photo_index),
                "keyframes": slot_keyframes,
            },
        )
    return {
        "keyframeCount": sum(record.get("backend") == "rfdetr" and record.get("reason") is None for record in records.values()),
        "instanceCount": sum(int(record.get("instanceCount", 0)) for record in records.values()),
        "rejectionCounts": {
            reason: sum(record.get("reason") == reason for record in records.values())
            for reason in sorted({record.get("reason") for record in records.values()} - {None})
        },
    }
