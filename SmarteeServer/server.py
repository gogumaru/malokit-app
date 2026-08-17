"""
server.py — local dev HTTP server wrapping main.py for the TeethLidar iOS app.

This is a LOCAL DEV SERVER, not something meant to be deployed. The app talks
to it over plain HTTP on your LAN while you're both on the same Wi-Fi network.

Run:
    source venv_py39/bin/activate
    python server.py

Then point the app at http://<this Mac's LAN IP>:8000/reconstruct
Find your IP with: ipconfig getifaddr en0   (or en1 if you're on Ethernet/USB)

Each request:
  1. Saves the 5 uploaded photos into seg/valid/image/ under a fresh tag
     (no manual patient registration needed — see const.py's TOOTH_EXIST_MASK).
  2. Runs the configured `python main.py <tag>` reconstruction in a separate
     subprocess.
     Separate processes matter because the
     EM-optimization/Ray step is documented (see run_safe.sh, KIRO_QUICK_START_GUIDE.md)
     as occasionally segfaulting on macOS/arm64. Running it in a subprocess means
     a crash only fails that one request instead of taking the whole server down,
     and — matching run_safe.sh's own workaround — failed attempts are retried.
  3. Reads back the two resulting OBJ meshes and returns them as JSON text
     (no zip/binary format needed since OBJ is already plain text, and the app
     already has an OBJ parser).
"""

import base64
import json
import os
import subprocess
import sys
import time
import uuid
from collections import Counter
from pathlib import Path

import h5py
import numpy as np
import skimage.io
from flask import Flask, jsonify, request
from seg.lidar_dental_cloud import apply_propagated_slots, fuse_dental_points, persist_dental_cloud
from seg.lidar_keyframe_segmentation import KEYFRAME_IDS, segment_lidar_keyframes
from seg.lidar_ssm_constraints import LiDARConstraintConfiguration, load_lidar_view_constraints
from seg.lidar_tooth_pose_constraints import load_lidar_tooth_pose_constraints
from seg.lidar_tooth_association import associate_instance_depth
from seg.lidar_tooth_slots import propagate_k0_slots
from seg.tooth_inventory import (
    build_tooth_inventory,
    load_inventory_views,
    write_tooth_inventory,
)

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(REPO_DIR, "venv_py39", "bin", "python")
IMAGE_DIR = os.path.join(REPO_DIR, "seg", "valid", "image")
MESH_DIR = os.path.join(REPO_DIR, "demo", "mesh")
LOG_DIR = os.path.join(REPO_DIR, "demo", "_temp")
EDGE_MASK_DIR = os.path.join(REPO_DIR, "demo", "_temp", "edge_masks")
INSTANCE_MASK_DIR = os.path.join(REPO_DIR, "demo", "_temp", "instance_masks")
TOOTH_INVENTORY_DIR = os.path.join(REPO_DIR, "demo", "_temp", "tooth_inventory")
LIDAR_DIAGNOSTIC_DIR = os.path.join(REPO_DIR, "demo", "_temp", "lidar_constraints")
RECONSTRUCTION_DATA_DIR = os.path.join(REPO_DIR, "demo", "reconstruction_data")
LIDAR_DIR = os.path.join(REPO_DIR, "seg", "valid", "lidar")
EDGE_BACKEND = os.environ.get("SMARTEE_EDGE_BACKEND", "h5").lower()
if EDGE_BACKEND not in ("h5", "rfdetr"):
    raise ValueError("SMARTEE_EDGE_BACKEND must be 'h5' or 'rfdetr'")
CAPTURE_EDGE_BACKEND = "rfdetr"

MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5
SUBPROCESS_TIMEOUT_SECONDS = 20 * 60  # EM optimization is slow; adjust if needed

COMPARISON_MODELS = (
    {
        "id": "pc10-regularized",
        "title": "10 PCs · Regularization 1.0",
        "num_pc": 10,
        "shape_regularization": 1.0,
        "engine": "baseline",
    },
)

# Take-5-Pictures' own model list, separate from COMPARISON_MODELS (Upload 5
# Photos), so the LiDAR-engine trial-and-error can never change what Upload
# returns. Same settings as the baseline model for now — emopt5views_lidar.py
# starts as an exact copy of emopt5views.py.
CAPTURE_MODELS = (
    {
        "id": "pc10-lidar",
        "title": "10 PCs · Regularization 1.0 (LiDAR)",
        "num_pc": 10,
        "shape_regularization": 1.0,
        "engine": "lidar",
    },
)

# The app's IntraoralPhotoType -> this pipeline's PHOTO enum index (const.py).
FIELD_TO_PHOTO_INDEX = {
    "maxillary": 0,    # PHOTO.UPPER
    "mandibular": 1,   # PHOTO.LOWER
    "leftLateral": 2,  # PHOTO.LEFT
    "rightLateral": 3, # PHOTO.RIGHT
    "front": 4,        # PHOTO.FRONTAL
}
FIGURE8_KEYFRAME_IDS = tuple(f"K{index}" for index in range(7))

app = Flask(__name__)


def selected_reconstruction_models():
    """Return the request's model set without changing the server default."""
    if request.form.get("modelMode") == "baseline-only":
        return CAPTURE_MODELS
    return COMPARISON_MODELS


def selected_edge_backend():
    """Use RF-DETR for Take 5 Pictures without changing Upload defaults."""
    if request.form.get("modelMode") == "baseline-only":
        return CAPTURE_EDGE_BACKEND
    return EDGE_BACKEND


def load_segmentation_view_summary(tag: str):
    path = os.path.join(INSTANCE_MASK_DIR, tag, "instances.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as file:
        manifest = json.load(file)
    if manifest.get("schemaVersion") != 1:
        raise ValueError(
            f"Unsupported instance manifest schema: {manifest.get('schemaVersion')}"
        )
    summary = {}
    for field, photo_index in FIELD_TO_PHOTO_INDEX.items():
        view = manifest.get("views", {}).get(str(photo_index))
        if view is not None:
            summary[field] = {
                "backend": view.get("backend"),
                "instanceCount": int(view.get("instanceCount", 0)),
                "fallbackReason": view.get("fallbackReason"),
            }
    return summary


def load_tooth_inventory_summary(tag: str):
    path = os.path.join(TOOTH_INVENTORY_DIR, tag, "tooth_inventory.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as file:
        inventory = json.load(file)
    if inventory.get("schemaVersion") != 1:
        raise ValueError(
            f"Unsupported tooth inventory schema: {inventory.get('schemaVersion')}"
        )
    return inventory


def persist_tooth_inventory(tag: str):
    """Write inventory without allowing missing/invalid evidence to fail a mesh request."""

    try:
        inventory = build_tooth_inventory(
            tag, load_inventory_views(Path(INSTANCE_MASK_DIR), tag)
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        inventory = {
            "schemaVersion": 1,
            "tag": tag,
            "available": False,
            "reason": str(error),
            "slots": [],
        }
    write_tooth_inventory(Path(TOOTH_INVENTORY_DIR), tag, inventory)
    return inventory


def save_lidar_capture_bundles(request_tag: str):
    """Validate and persist optional RGB-aligned Float32 LiDAR depth bundles."""
    saved_views = {}
    output_dir = os.path.join(LIDAR_DIR, request_tag)

    for field in FIELD_TO_PHOTO_INDEX:
        depth_key = f"{field}Depth"
        metadata_key = f"{field}DepthMetadata"
        depth_file = request.files.get(depth_key)
        metadata_file = request.files.get(metadata_key)

        if depth_file is None and metadata_file is None:
            continue
        if depth_file is None or metadata_file is None:
            raise ValueError(
                f"LiDAR view '{field}' must include both depth and metadata files."
            )

        try:
            metadata = json.loads(metadata_file.read().decode("utf-8"))
            width = int(metadata["depthWidth"])
            height = int(metadata["depthHeight"])
            bytes_per_sample = int(metadata.get("bytesPerSample", 4))
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Invalid LiDAR metadata for '{field}': {error}")

        if width <= 0 or height <= 0 or bytes_per_sample != 4:
            raise ValueError(
                f"Invalid LiDAR dimensions/format for '{field}': "
                f"{width}x{height}, {bytes_per_sample} bytes/sample."
            )

        depth_bytes = depth_file.read()
        expected_size = width * height * bytes_per_sample
        if len(depth_bytes) != expected_size:
            raise ValueError(
                f"LiDAR depth size mismatch for '{field}': expected "
                f"{expected_size} bytes, received {len(depth_bytes)}."
            )

        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, f"{field}.depth.f32"), "wb") as file:
            file.write(depth_bytes)
        with open(
            os.path.join(output_dir, f"{field}.depth.json"), "w", encoding="utf-8"
        ) as file:
            json.dump(metadata, file, indent=2, sort_keys=True)

        saved_views[field] = {
            "depthWidth": width,
            "depthHeight": height,
            "validFraction": metadata.get("validFraction"),
            "ssmDepthEligible": bool(metadata.get("ssmDepthEligible", False)),
        }

    return saved_views


def _atomic_write(path, data):
    """Write one artifact atomically so a checkpoint never exposes a half file."""
    temporary_path = f"{path}.{uuid.uuid4().hex}.tmp"
    with open(temporary_path, "wb") as file:
        file.write(data)
    os.replace(temporary_path, path)


def _figure8_file(field, keyframe_id, suffix):
    return request.files.get(f"{field}Figure8{keyframe_id}{suffix}")


def _validate_figure8_metadata(field, keyframe_id, metadata, depth_bytes, confidence_bytes, rgb_bytes):
    prefix = f"Figure-8 keyframe {keyframe_id} for '{field}'"
    try:
        width = int(metadata["depthWidth"])
        height = int(metadata["depthHeight"])
        bytes_per_sample = int(metadata["bytesPerSample"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{prefix} has invalid dimensions: {error}")

    if metadata.get("schemaVersion") != 4:
        raise ValueError(f"{prefix} must use metadata schema 4.")
    if width <= 0 or height <= 0 or bytes_per_sample != 4:
        raise ValueError(f"{prefix} has invalid Float32 dimensions.")
    if len(depth_bytes) != width * height * bytes_per_sample:
        raise ValueError(f"{prefix} depth byte count does not match dimensions.")
    if len(confidence_bytes) != width * height:
        raise ValueError(f"{prefix} confidence byte count does not match dimensions.")
    if not rgb_bytes:
        raise ValueError(f"{prefix} RGB PNG is empty.")
    if metadata.get("figure8KeyframeID") != keyframe_id:
        raise ValueError(f"{prefix} metadata keyframe ID does not match the upload field.")
    if metadata.get("isDirectView") is not True or metadata.get("ssmDepthEligible") is not True:
        raise ValueError(f"{prefix} must be a direct, depth-eligible view.")
    if metadata.get("trackingState") != "normal":
        raise ValueError(f"{prefix} must have normal ARKit tracking.")
    if metadata.get("matrixLayout") != "column-major":
        raise ValueError(f"{prefix} must declare column-major matrices.")
    if metadata.get("coordinateSystem") != "ARKit camera-to-world":
        raise ValueError(f"{prefix} must declare the ARKit camera coordinate system.")
    transform = metadata.get("cameraToReferenceTransform")
    if not isinstance(transform, list) or len(transform) != 16:
        raise ValueError(f"{prefix} must include a 4x4 camera-to-reference transform.")
    if not isinstance(metadata.get("orientation"), str) or not metadata["orientation"]:
        raise ValueError(f"{prefix} must include image orientation.")


def save_figure8_keyframe_bundles(request_tag: str):
    """Validate and persist complete direct-view K0–K6 bundles independently."""
    saved_views = {}
    root = os.path.join(LIDAR_DIR, request_tag)

    for field in FIELD_TO_PHOTO_INDEX:
        manifest_file = request.files.get(f"{field}Figure8Manifest")
        any_keyframe_file = any(
            key.startswith(f"{field}Figure8") for key in request.files
        )
        if manifest_file is None and not any_keyframe_file:
            continue
        if manifest_file is None:
            raise ValueError(f"Figure-8 view '{field}' is missing its manifest.")

        try:
            manifest_bytes = manifest_file.read()
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            manifest_ids = [entry["id"] for entry in manifest["keyframes"]]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise ValueError(f"Invalid Figure-8 manifest for '{field}': {error}")

        unknown_ids = [keyframe_id for keyframe_id in manifest_ids if keyframe_id not in FIGURE8_KEYFRAME_IDS]
        if unknown_ids:
            raise ValueError(f"Figure-8 view '{field}' has unknown keyframe {unknown_ids[0]}.")
        if not manifest_ids or manifest_ids[0] != "K0":
            raise ValueError(f"Figure-8 view '{field}' must list K0 first.")
        if manifest_ids != list(FIGURE8_KEYFRAME_IDS):
            raise ValueError(f"Figure-8 view '{field}' must list ordered K0 through K6 exactly once.")

        validated = []
        for keyframe_id in FIGURE8_KEYFRAME_IDS:
            rgb_file = _figure8_file(field, keyframe_id, "RGB")
            depth_file = _figure8_file(field, keyframe_id, "Depth")
            confidence_file = _figure8_file(field, keyframe_id, "Confidence")
            metadata_file = _figure8_file(field, keyframe_id, "Metadata")
            missing = [
                name for name, file in (
                    ("RGB", rgb_file), ("depth", depth_file),
                    ("confidence", confidence_file), ("metadata", metadata_file),
                ) if file is None
            ]
            if missing:
                raise ValueError(f"Figure-8 keyframe {keyframe_id} for '{field}' is missing {missing[0]}.")
            try:
                metadata_bytes = metadata_file.read()
                metadata = json.loads(metadata_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(f"Figure-8 keyframe {keyframe_id} for '{field}' has invalid metadata: {error}")
            rgb_bytes = rgb_file.read()
            depth_bytes = depth_file.read()
            confidence_bytes = confidence_file.read()
            _validate_figure8_metadata(
                field, keyframe_id, metadata, depth_bytes, confidence_bytes, rgb_bytes
            )
            validated.append((keyframe_id, rgb_bytes, depth_bytes, confidence_bytes, metadata_bytes))

        output_dir = os.path.join(root, field)
        os.makedirs(output_dir, exist_ok=True)
        for keyframe_id, rgb_bytes, depth_bytes, confidence_bytes, metadata_bytes in validated:
            _atomic_write(os.path.join(output_dir, f"{keyframe_id}.rgb.png"), rgb_bytes)
            _atomic_write(os.path.join(output_dir, f"{keyframe_id}.depth.f32"), depth_bytes)
            _atomic_write(os.path.join(output_dir, f"{keyframe_id}.confidence.u8"), confidence_bytes)
            _atomic_write(os.path.join(output_dir, f"{keyframe_id}.metadata.json"), metadata_bytes)
        _atomic_write(os.path.join(output_dir, "figure8_manifest.json"), manifest_bytes)
        saved_views[field] = {
            "keyframeCount": len(validated),
            "keyframeIDs": list(FIGURE8_KEYFRAME_IDS),
        }

    return saved_views


def _load_figure8_depth_grids(view_directory: Path, keyframe_id: str, metadata: dict):
    try:
        width = int(metadata["depthWidth"])
        height = int(metadata["depthHeight"])
        depth_bytes = (view_directory / f"{keyframe_id}.depth.f32").read_bytes()
        confidence_bytes = (view_directory / f"{keyframe_id}.confidence.u8").read_bytes()
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise ValueError(f"cannot read {keyframe_id} depth bundle: {error}") from error
    if width <= 0 or height <= 0 or len(depth_bytes) != width * height * 4:
        raise ValueError(f"invalid {keyframe_id} Float32 depth grid")
    if len(confidence_bytes) != width * height:
        raise ValueError(f"invalid {keyframe_id} confidence grid")
    return (
        np.frombuffer(depth_bytes, dtype="<f4").reshape((height, width)),
        np.frombuffer(confidence_bytes, dtype=np.uint8).reshape((height, width)),
    )


def _load_keyframe_metadata(view_directory: Path, keyframe_id: str) -> dict:
    try:
        metadata = json.loads(
            (view_directory / f"{keyframe_id}.metadata.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read {keyframe_id} metadata: {error}") from error
    if not isinstance(metadata, dict):
        raise ValueError(f"invalid {keyframe_id} metadata")
    return metadata


def process_lidar_dental_cloud(request_tag: str, predictor=None, active_original_indices=None):
    """Build per-direct-view diagnostic clouds after the photo reconstruction succeeds."""

    root = Path(LIDAR_DIR) / request_tag
    summaries = {}
    for field in FIELD_TO_PHOTO_INDEX:
        view_directory = root / field
        if not (view_directory / "figure8_manifest.json").is_file():
            continue
        try:
            segmentation_summary = segment_lidar_keyframes(
                view_directory,
                field=field,
                photo_index=FIELD_TO_PHOTO_INDEX[field],
                active_original_indices=(
                    np.arange(28, dtype=np.intp)
                    if active_original_indices is None
                    else np.asarray(active_original_indices, dtype=np.intp)
                ),
                **({"predictor": predictor} if predictor is not None else {}),
            )
            segmentation = json.loads(
                (view_directory / "segmentation" / "instances.json").read_text(encoding="utf-8")
            )
            slot_assignments = json.loads(
                (view_directory / "segmentation" / "slot_assignments.json").read_text(encoding="utf-8")
            )
            if (
                slot_assignments.get("schemaVersion") != 2
                or slot_assignments.get("field") != field
                or slot_assignments.get("photoIndex") != FIELD_TO_PHOTO_INDEX[field]
            ):
                raise ValueError("invalid keyframe slot-assignment manifest")
            associations = []
            rejected_associations = []
            for keyframe_id in KEYFRAME_IDS:
                keyframe = segmentation.get("keyframes", {}).get(keyframe_id, {})
                if keyframe.get("reason") is not None:
                    continue
                metadata = _load_keyframe_metadata(view_directory, keyframe_id)
                depth, confidence = _load_figure8_depth_grids(view_directory, keyframe_id, metadata)
                for instance in keyframe.get("instances", []):
                    mask = skimage.io.imread(str(view_directory / "segmentation" / instance["mask"]))
                    result = associate_instance_depth(
                        mask=mask,
                        keyframe_id=keyframe_id,
                        instance_id=str(instance["localId"]),
                        detector_confidence=float(instance["confidence"]),
                        depth_metres=depth,
                        confidence_values=confidence,
                        metadata=metadata,
                        slot_id=None,
                    )
                    associations.extend(result["accepted"])
                    associations.extend(result["rejected"])
            k0_assignments = slot_assignments.get("keyframes", {}).get("K0", {}).get("assignments", {})
            if not isinstance(k0_assignments, dict):
                raise ValueError("invalid K0 slot assignments")
            propagated_assignments, propagation_diagnostics = propagate_k0_slots(
                associations, k0_assignments
            )
            associations = apply_propagated_slots(associations, propagated_assignments)
            rejected_associations = [
                record for record in associations if record.get("rejectionReason") is not None
            ]
            # propagate_k0_slots only produces a diagnostic for K0 instances
            # that already reached assign_keyframe_slots' k0_assignments
            # (i.e. were assigned a slot). Instances assign_keyframe_slots
            # itself rejected outright (e.g. "ambiguous_arch_rows") never
            # appear there, so preserve those original K0 rejection reasons
            # before they'd otherwise be silently dropped below.
            original_k0_rejections = dict(
                slot_assignments.get("keyframes", {}).get("K0", {}).get("rejections", {})
            )
            for keyframe_id in KEYFRAME_IDS:
                keyframe_slots = slot_assignments.setdefault("keyframes", {}).setdefault(
                    keyframe_id, {"assignments": {}, "rejections": {}}
                )
                keyframe_slots["assignments"] = propagated_assignments.get(keyframe_id, {})
                keyframe_slots["matchDiagnostics"] = propagation_diagnostics.get(keyframe_id, {})
                keyframe_slots["rejections"] = {
                    **(original_k0_rejections if keyframe_id == "K0" else {}),
                    **{
                        instance_id: diagnostic["reason"]
                        for instance_id, diagnostic in propagation_diagnostics.get(keyframe_id, {}).items()
                        if diagnostic.get("reason") not in ("matched_k0_anchor", "k0_slot_anchor")
                    },
                }
            slot_assignment_path = view_directory / "segmentation" / "slot_assignments.json"
            temporary_slot_path = slot_assignment_path.with_suffix(".json.tmp")
            temporary_slot_path.write_text(
                json.dumps(slot_assignments, indent=2) + "\n", encoding="utf-8"
            )
            temporary_slot_path.replace(slot_assignment_path)
            fused = fuse_dental_points(associations)
            combined_rejections = Counter(fused["rejectionCounts"])
            combined_rejections.update(segmentation_summary.get("rejectionCounts", {}))
            fused["rejectionCounts"] = dict(sorted(combined_rejections.items()))
            persisted = persist_dental_cloud(view_directory, fused, rejected_associations)
            persisted["keyframeCount"] = segmentation_summary["keyframeCount"]
            summaries[field] = persisted
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            summaries[field] = {
                "available": False,
                "reason": f"dental_cloud_failure: {error}",
                "pointCount": 0,
                "perKeyframe": {},
                "rejectionCounts": {},
            }
    return summaries


def dental_cloud_response_summary(clouds: dict):
    """Return only JSON-safe coverage diagnostics, never patient point data."""

    return {
        field: {
            "available": cloud.get("available", True),
            "keyframeCount": int(cloud.get("keyframeCount", 0)),
            "pointCount": int(cloud.get("pointCount", 0)),
            "occupiedVoxelCount": int(cloud.get("pointCount", 0)),
            "voxelSizeMetres": cloud.get("voxelSizeMetres"),
            "perKeyframe": cloud.get("perKeyframe", {}),
            "rejectionCounts": cloud.get("rejectionCounts", {}),
            **({"reason": cloud["reason"]} if cloud.get("reason") else {}),
        }
        for field, cloud in clouds.items()
    }


def lidar_constraint_response_summary(constraints: dict, skipped: dict) -> dict:
    """Expose capture eligibility without returning patient point coordinates."""

    return {
        "eligible": bool(constraints),
        "eligibleViews": {
            constraint.field: {
                "photoIndex": int(constraint.photo_index),
                "pointCount": int(len(constraint.points_k0_metres)),
                "contributingKeyframes": list(constraint.contributing_keyframes),
            }
            for constraint in constraints.values()
        },
        "skippedViews": dict(skipped),
    }


def lidar_tooth_pose_constraint_response_summary(constraints: dict, skipped: dict) -> dict:
    """Expose only M6 coverage/provenance counts, never patient geometry."""

    eligible_slots = {}
    for values in constraints.values():
        for constraint in values:
            entry = eligible_slots.setdefault(
                constraint.slot_id,
                {"fields": [], "photoIndices": [], "keyframes": [], "pointCount": 0},
            )
            entry["fields"].append(constraint.field)
            entry["photoIndices"].append(int(constraint.photo_index))
            entry["keyframes"].append(list(constraint.contributing_keyframes))
            entry["pointCount"] += int(len(constraint.points_k0_metres))
    for entry in eligible_slots.values():
        entry["fields"].sort()
        entry["photoIndices"].sort()
    return {"eligible": bool(eligible_slots), "eligibleSlots": eligible_slots, "skipped": dict(skipped)}


def load_lidar_tooth_shape_constraint_summary(tag: str) -> dict:
    """Read M7 diagnostics while excluding masks and patient point coordinates."""

    path = os.path.join(RECONSTRUCTION_DATA_DIR, f"demo-tag={tag}.h5")
    if not os.path.exists(path):
        return {"eligible": False, "reason": "reconstruction_diagnostics_missing"}
    try:
        with h5py.File(path, "r") as file:
            encoded = file["EMOPT"].attrs.get("LIDAR_TOOTH_SHAPE_CONSTRAINTS_JSON")
        if encoded is None:
            return {"eligible": False, "reason": "m7_not_recorded"}
        if isinstance(encoded, bytes):
            encoded = encoded.decode("utf-8")
        diagnostic = json.loads(encoded)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        return {"eligible": False, "reason": f"invalid_m7_diagnostics: {error}"}

    summary = {
        "eligible": bool(diagnostic.get("enabled")),
        "eligibleSlots": diagnostic.get("eligibleSlots", {}),
        "featureVectorDeltaNorms": diagnostic.get("featureVectorDeltaNorms", {}),
    }
    if "weight" in diagnostic:
        summary["weight"] = float(diagnostic["weight"])
    if "lastLossMetresSquared" in diagnostic:
        summary["lastLossMetresSquared"] = float(
            diagnostic["lastLossMetresSquared"]
        )
    if not summary["eligible"]:
        summary["reason"] = diagnostic.get("reason", "m7_disabled")
    return summary


def load_lidar_optimization_diagnostic_summary(tag: str) -> dict:
    path = Path(LIDAR_DIAGNOSTIC_DIR) / f"{tag}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False, "reason": "optimizer_diagnostics_missing"}
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        return {"available": False, "reason": "optimizer_diagnostics_invalid"}
    safe_keys = {
        "enabled",
        "accepted",
        "inputEligible",
        "fallbackApplied",
        "reason",
        "weight",
        "eligibleViews",
        "skippedViews",
        "skipped",
        "pairCounts",
        "noInGateCorrespondences",
        "metricScaleMetresPerSSMUnit",
        "lastLossMetresSquared",
        "photoOnlyMedianDistanceMillimetres",
        "photoOnlyP95DistanceMillimetres",
        "coarseLiDARMedianDistanceMillimetres",
        "coarseLiDARP95DistanceMillimetres",
        "photoContourLossBefore",
        "photoContourLossAfter",
        "photoContourLossChangePercent",
        "stage2PoseParameterDeltaFromCoarseLiDAR",
        "stage3FeatureVectorDeltaFromCoarseLiDAR",
        "eligibleSlots",
        "poseDeltaNorms",
        "scaleParameterDeltaFromM6Loss",
        "stage3FeatureVectorDeltaFromM6Loss",
        "featureVectorDeltaNorms",
    }

    def sanitized(value):
        return {
            key: item
            for key, item in value.items()
            if key in safe_keys
        } if isinstance(value, dict) else {}

    return {
        "available": True,
        "coarse": sanitized(payload.get("coarse", {})),
        "toothPose": sanitized(payload.get("toothPose", {})),
        "toothShape": sanitized(payload.get("toothShape", {})),
    }


def run_reconstruction(
    tag: str,
    num_pc: int = 10,
    shape_regularization: float = 1.0,
    edge_mask_source_tag: str = None,
    engine: str = "baseline",
    edge_backend: str = EDGE_BACKEND,
    lidar_capture_tag: str = None,
):
    """Runs main.py for `tag`, retrying on crash. Returns (upper_obj_path, lower_obj_path) or raises RuntimeError."""
    if edge_backend not in ("h5", "rfdetr"):
        raise ValueError(f"Unknown edge backend: {edge_backend!r}")
    upper_obj = os.path.join(MESH_DIR, tag, f"Pred_Upper_Mesh_Tag={tag}.obj")
    lower_obj = os.path.join(MESH_DIR, tag, f"Pred_Lower_Mesh_Tag={tag}.obj")

    def output_mtime(path):
        try:
            return os.path.getmtime(path)
        except OSError:
            return None

    last_result = None
    last_failure_reason = "not started"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        output_mtimes_before = {
            path: output_mtime(path)
            for path in (upper_obj, lower_obj)
        }
        print(
            f"[{tag}] Reconstruction attempt {attempt}/{MAX_ATTEMPTS} "
            f"(PCs={num_pc}, regularization={shape_regularization}, "
            f"engine={engine}, edge_backend={edge_backend})...",
            flush=True,
        )
        command = [
            VENV_PYTHON,
            "main.py",
            tag,
            "--num-pc",
            str(num_pc),
            "--shape-regularization",
            str(shape_regularization),
            "--engine",
            engine,
            "--edge-backend",
            edge_backend,
        ]
        if edge_mask_source_tag is not None:
            command.extend(["--edge-mask-source-tag", edge_mask_source_tag])
        if engine == "lidar" and lidar_capture_tag is not None:
            command.extend(["--lidar-capture-tag", lidar_capture_tag])
        try:
            last_result = subprocess.run(
                command,
                cwd=REPO_DIR,
                env={
                    **os.environ,
                    "OMP_NUM_THREADS": "1",
                    "SMARTEE_EDGE_BACKEND": edge_backend,
                },
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as e:
            last_result = e
            last_failure_reason = "timed out"
            print(f"[{tag}] Attempt {attempt} timed out.", flush=True)
            continue

        fresh_outputs = all(
            os.path.exists(path)
            and (
                output_mtimes_before[path] is None
                or os.path.getmtime(path) > output_mtimes_before[path]
            )
            for path in (upper_obj, lower_obj)
        )
        if last_result.returncode == 0 and fresh_outputs:
            print(f"[{tag}] Reconstruction succeeded.", flush=True)
            return upper_obj, lower_obj

        reason = f"exit code {last_result.returncode}" if last_result.returncode != 0 else "exited 0 but wrote no fresh mesh"
        last_failure_reason = reason
        print(f"[{tag}] Attempt {attempt} failed ({reason}).", flush=True)
        if attempt < MAX_ATTEMPTS:
            time.sleep(RETRY_DELAY_SECONDS)

    log_tail = ""
    log_path = os.path.join(LOG_DIR, f"Tag={tag}.log")
    if os.path.exists(log_path):
        with open(log_path, "r", errors="replace") as f:
            log_tail = f.read()[-4000:]
    stderr_tail = getattr(last_result, "stderr", "") or ""
    raise RuntimeError(
        f"Reconstruction failed after {MAX_ATTEMPTS} attempts "
        f"({last_failure_reason}).\nLog tail:\n{log_tail}\n"
        f"Stderr tail:\n{stderr_tail[-2000:]}"
    )


# Ordered stage markers main.py writes into demo/_temp/Tag=<tag>.log. Only the
# ids are contract with the app, which owns the wording shown to the user.
# Mesh building is deliberately absent: main.py restores the console before it,
# so it never reaches this log and cannot be observed here.
PROGRESS_MARKERS = (
    ("Requested edge-mask backend:", "segmenting"),
    ("Start Stage 0.", "stage0"),
    ("Start Stage 1.", "stage1"),
    ("Start Grid Search.", "gridSearch"),
    ("Start Stage 2 and 3.", "stage23"),
)


def is_valid_request_tag(tag):
    """Tags name files and directories, so reject anything but [A-Za-z0-9-]."""
    return bool(tag) and len(tag) <= 40 and all(c.isalnum() or c == "-" for c in tag)


def reconstruction_stage(tag):
    """The newest stage this request has reached, read from its own log."""
    logs = sorted(Path(LOG_DIR).glob(f"Tag={tag}*.log"), key=os.path.getmtime)
    if not logs:
        return "queued"
    text = logs[-1].read_text(errors="replace")
    stage = "queued"
    for marker, name in PROGRESS_MARKERS:
        if marker in text:
            stage = name
    return stage


@app.get("/progress/<tag>")
def progress(tag):
    """Polled while /reconstruct is still in flight, so the app can show which
    pipeline stage is running instead of one frozen label for the whole run."""
    if not is_valid_request_tag(tag):
        return jsonify(error="Invalid tag."), 400
    return jsonify(stage=reconstruction_stage(tag))


@app.post("/reconstruct")
def reconstruct():
    missing = [field for field in FIELD_TO_PHOTO_INDEX if field not in request.files]
    if missing:
        return jsonify(error=f"Missing photo(s): {', '.join(missing)}"), 400

    # The app sends the tag it will poll /progress with; without one, requests
    # still work exactly as before, just without live stage reporting.
    request_tag = request.form.get("requestTag", "").strip() or uuid.uuid4().hex[:12]
    if not is_valid_request_tag(request_tag):
        return jsonify(error="Invalid requestTag."), 400
    try:
        lidar_views = save_lidar_capture_bundles(request_tag)
        figure8_keyframes = save_figure8_keyframe_bundles(request_tag)
    except ValueError as error:
        return jsonify(error=str(error)), 400

    dental_cloud = process_lidar_dental_cloud(request_tag) if figure8_keyframes else {}
    lidar_constraints, lidar_constraint_skips = load_lidar_view_constraints(
        Path(LIDAR_DIR), request_tag, LiDARConstraintConfiguration()
    )
    tooth_pose_constraints, tooth_pose_skips = load_lidar_tooth_pose_constraints(
        Path(LIDAR_DIR), request_tag, np.arange(28, dtype=np.intp)
    )
    eligible_lidar_fields = {constraint.field for constraint in lidar_constraints.values()}
    tooth_pose_constraints = {
        tooth_index: tuple(value for value in values if value.field in eligible_lidar_fields)
        for tooth_index, values in tooth_pose_constraints.items()
    }
    tooth_pose_constraints = {
        tooth_index: values for tooth_index, values in tooth_pose_constraints.items() if len(values) >= 2
    }
    models_to_run = selected_reconstruction_models()
    request_edge_backend = selected_edge_backend()
    model_tags = [f"{request_tag}-{model['id']}" for model in models_to_run]
    os.makedirs(IMAGE_DIR, exist_ok=True)
    for field, photo_index in FIELD_TO_PHOTO_INDEX.items():
        image_data = request.files[field].read()
        for tag in model_tags:
            with open(os.path.join(IMAGE_DIR, f"{tag}-{photo_index}.png"), "wb") as f:
                f.write(image_data)

    reconstructed_models = []
    edge_mask_source_tag = None
    try:
        for model, tag in zip(models_to_run, model_tags):
            upper_path, lower_path = run_reconstruction(
                tag,
                num_pc=model["num_pc"],
                shape_regularization=model["shape_regularization"],
                edge_mask_source_tag=edge_mask_source_tag,
                engine=model["engine"],
                edge_backend=request_edge_backend,
                lidar_capture_tag=request_tag if model["engine"] == "lidar" else None,
            )
            with open(upper_path, "r") as f:
                upper_obj = f.read()
            with open(lower_path, "r") as f:
                lower_obj = f.read()
            upper_texture_path = os.path.join(
                MESH_DIR, tag, f"Pred_Upper_Texture_Tag={tag}.png"
            )
            lower_texture_path = os.path.join(
                MESH_DIR, tag, f"Pred_Lower_Texture_Tag={tag}.png"
            )
            with open(upper_texture_path, "rb") as file:
                upper_texture = base64.b64encode(file.read()).decode("ascii")
            with open(lower_texture_path, "rb") as file:
                lower_texture = base64.b64encode(file.read()).decode("ascii")
            reconstructed_models.append(
                {
                    "id": model["id"],
                    "title": model["title"],
                    "numPC": model["num_pc"],
                    "shapeRegularization": model["shape_regularization"],
                    "upperObj": upper_obj,
                    "lowerObj": lower_obj,
                    "upperTexture": upper_texture,
                    "lowerTexture": lower_texture,
                    "lidarToothShapeConstraints": load_lidar_tooth_shape_constraint_summary(tag),
                    "lidarOptimizationDiagnostics": load_lidar_optimization_diagnostic_summary(tag),
                }
            )
            if edge_mask_source_tag is None:
                edge_mask_source_tag = tag
    except RuntimeError as e:
        return jsonify(error=str(e)), 500

    edge_masks = {}
    predicted_edge_masks = {}
    persist_tooth_inventory(edge_mask_source_tag)
    for field, photo_index in FIELD_TO_PHOTO_INDEX.items():
        mask_path = os.path.join(
            EDGE_MASK_DIR,
            edge_mask_source_tag,
            f"{edge_mask_source_tag}-{photo_index}.png",
        )
        if os.path.exists(mask_path):
            with open(mask_path, "rb") as f:
                edge_masks[field] = base64.b64encode(f.read()).decode("ascii")

        predicted_mask_path = os.path.join(
            EDGE_MASK_DIR,
            edge_mask_source_tag,
            f"{edge_mask_source_tag}-{photo_index}-predicted.png",
        )
        if os.path.exists(predicted_mask_path):
            with open(predicted_mask_path, "rb") as f:
                predicted_edge_masks[field] = base64.b64encode(f.read()).decode("ascii")

    baseline = reconstructed_models[0]
    return jsonify(
        # Keep the original fields so older app paths can use the model directly.
        upperObj=baseline["upperObj"],
        lowerObj=baseline["lowerObj"],
        upperTexture=baseline["upperTexture"],
        lowerTexture=baseline["lowerTexture"],
        models=reconstructed_models,
        edgeMasks=edge_masks,
        predictedEdgeMasks=predicted_edge_masks,
        segmentationViews=load_segmentation_view_summary(edge_mask_source_tag),
        toothInventory=load_tooth_inventory_summary(edge_mask_source_tag),
        lidarCaptureTag=request_tag if lidar_views else None,
        lidarViews=lidar_views,
        figure8Keyframes=figure8_keyframes,
        dentalCloud=dental_cloud_response_summary(dental_cloud),
        lidarConstraints=lidar_constraint_response_summary(lidar_constraints, lidar_constraint_skips),
        lidarToothPoseConstraints=lidar_tooth_pose_constraint_response_summary(
            tooth_pose_constraints, tooth_pose_skips
        ),
        lidarToothShapeConstraints=baseline["lidarToothShapeConstraints"],
        lidarOptimizationDiagnostics=baseline["lidarOptimizationDiagnostics"],
    )


@app.get("/health")
def health():
    return jsonify(
        status="ok",
        edgeBackend=EDGE_BACKEND,
        captureEdgeBackend=CAPTURE_EDGE_BACKEND,
        uploadEdgeBackend=EDGE_BACKEND,
        acceptsLiDARDepth=True,
        comparisonModels=[
            {
                "id": model["id"],
                "numPC": model["num_pc"],
                "shapeRegularization": model["shape_regularization"],
            }
            for model in COMPARISON_MODELS
        ],
    )


if __name__ == "__main__":
    print(f"Repo dir:   {REPO_DIR}")
    print(f"Interpreter: {VENV_PYTHON}")
    print(f"Edge backend: {EDGE_BACKEND}")
    if not os.path.exists(VENV_PYTHON):
        print("⚠️  venv_py39 not found — run this from inside the repo with the venv set up.", file=sys.stderr)
    app.run(host="0.0.0.0", port=8000)
