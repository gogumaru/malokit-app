"""Run RF-DETR inference without importing its dependencies into Smartee."""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

import numpy as np
import skimage.io

from seg.prediction_types import EdgePrediction, ToothInstancePrediction


REPO_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PYTHON = REPO_DIR / ".venv-rfdetr" / "bin" / "python"
DEFAULT_SCRIPT = REPO_DIR / "seg" / "rfdetr" / "predict_edges.py"
DEFAULT_MULTIVIEW_CHECKPOINT = (
    REPO_DIR
    / "seg"
    / "rfdetr"
    / "runs"
    / "small-multiview"
    / "checkpoint_best_regular.pth"
)
DEFAULT_CHECKPOINT = Path(
    os.environ.get("SMARTEE_RFDETR_CHECKPOINT", str(DEFAULT_MULTIVIEW_CHECKPOINT))
)


class RFDETRInferenceError(RuntimeError):
    """RF-DETR could not produce a usable prediction."""


def _load_binary_mask(path: Path) -> np.ndarray:
    mask = skimage.io.imread(str(path))
    if mask.ndim == 3:
        mask = mask[..., :3].max(axis=-1)
    return ((mask > 127) * 255).astype(np.uint8)


def _load_instance(
    output_dir: Path, record: dict, expected_shape: Tuple[int, int]
) -> ToothInstancePrediction:
    mask_path = output_dir / str(record["mask"])
    if not mask_path.is_file():
        raise RFDETRInferenceError(
            f"RF-DETR instance mask not found: {mask_path.name}"
        )
    mask = _load_binary_mask(mask_path)
    if mask.shape != expected_shape or not np.any(mask):
        raise RFDETRInferenceError(
            f"Invalid RF-DETR instance mask {mask_path.name}: {mask.shape}, "
            f"expected {expected_shape}."
        )
    confidence = float(record["confidence"])
    if not np.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise RFDETRInferenceError(f"Invalid RF-DETR confidence: {confidence}")
    bbox = tuple(int(value) for value in record["bboxXYWH"])
    centroid = tuple(float(value) for value in record["centroidXY"])
    if len(bbox) != 4 or len(centroid) != 2:
        raise RFDETRInferenceError("Invalid RF-DETR instance geometry metadata.")
    return ToothInstancePrediction(
        local_id=str(record["localId"]),
        mask=mask,
        confidence=confidence,
        bbox_xywh=bbox,
        centroid_xy=centroid,
        area_pixels=int(record["areaPixels"]),
    )


def predict_rfdetr_predictions(
    image_paths: Sequence[str],
    resized_width: int = 800,
    confidence: float = 0.5,
    python_executable: Optional[Path] = None,
    script: Optional[Path] = None,
    checkpoint: Optional[Path] = None,
    timeout_seconds: int = 5 * 60,
) -> List[Union[EdgePrediction, RFDETRInferenceError]]:
    """Run one RF-DETR batch and return a structured outcome for every image."""

    paths = [Path(path).resolve() for path in image_paths]
    if not paths:
        return []
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise RFDETRInferenceError(f"Input image not found: {missing[0]}")
    if resized_width <= 0:
        raise RFDETRInferenceError("resized_width must be positive")

    # Do not resolve this symlink: a venv's ``bin/python`` commonly points to
    # the base interpreter, and resolving it would discard the venv packages.
    python_path = Path(python_executable or DEFAULT_PYTHON).absolute()
    script_path = Path(script or DEFAULT_SCRIPT).resolve()
    checkpoint_path = Path(checkpoint or DEFAULT_CHECKPOINT).resolve()
    required = (
        (python_path, "RF-DETR Python interpreter"),
        (script_path, "RF-DETR prediction script"),
        (checkpoint_path, "RF-DETR checkpoint"),
    )
    for path, label in required:
        if not path.is_file():
            raise RFDETRInferenceError(f"{label} not found: {path}")

    with tempfile.TemporaryDirectory(prefix="smartee-rfdetr-") as temporary_root:
        output_dir = Path(temporary_root) / "predictions"
        command = [
            str(python_path),
            str(script_path),
            "--input",
            *[str(path) for path in paths],
            "--output",
            str(output_dir),
            "--checkpoint",
            str(checkpoint_path),
            "--edge-width",
            str(resized_width),
            "--confidence",
            str(confidence),
        ]
        try:
            result = subprocess.run(
                command,
                cwd=str(REPO_DIR),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RFDETRInferenceError(f"RF-DETR process failed: {exc}") from exc

        if result.returncode != 0:
            details = (result.stderr or result.stdout or "no output")[-2000:]
            raise RFDETRInferenceError(
                f"RF-DETR exited with code {result.returncode}:\n{details}"
            )

        manifest_path = output_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RFDETRInferenceError(
                f"RF-DETR could not read its manifest: {exc}"
            ) from exc
        if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
            raise RFDETRInferenceError("RF-DETR produced an unsupported manifest schema")
        image_records = manifest.get("images")
        if not isinstance(image_records, list):
            raise RFDETRInferenceError("RF-DETR manifest does not contain an images list")

        records_by_path = {}
        for record in image_records:
            if not isinstance(record, dict):
                continue
            try:
                record_path = Path(str(record["image"])).resolve()
            except (KeyError, TypeError, ValueError):
                continue
            records_by_path.setdefault(record_path, []).append(record)

        outcomes = []
        for image_path in paths:
            try:
                records = records_by_path.get(image_path, [])
                if len(records) != 1:
                    raise RFDETRInferenceError(
                        f"RF-DETR manifest has {len(records)} records for "
                        f"{image_path.name}; expected exactly one."
                    )
                record = records[0]
                width = int(record["width"])
                height = int(record["height"])
                if width <= 0 or height <= 0:
                    raise RFDETRInferenceError(
                        f"Invalid RF-DETR source geometry for {image_path.name}."
                    )
                edge_path = output_dir / str(record["edgeMask"])
                if not edge_path.is_file():
                    raise RFDETRInferenceError(
                        f"RF-DETR did not create an edge mask for {image_path.name}"
                    )
                edge_mask = _load_binary_mask(edge_path)
                if edge_mask.ndim != 2 or not np.any(edge_mask):
                    raise RFDETRInferenceError(
                        f"RF-DETR produced an empty edge mask for {image_path.name}"
                    )
                instance_records = record["instances"]
                if not isinstance(instance_records, list):
                    raise RFDETRInferenceError(
                        f"Invalid RF-DETR instance records for {image_path.name}."
                    )
                instances = tuple(
                    _load_instance(output_dir, instance, (height, width))
                    for instance in instance_records
                )
                outcomes.append(
                    EdgePrediction(
                        edge_mask=edge_mask,
                        source="rfdetr",
                        instances=instances,
                    )
                )
            except (KeyError, OSError, TypeError, ValueError, RFDETRInferenceError) as exc:
                outcomes.append(RFDETRInferenceError(f"{image_path.name}: {exc}"))
        return outcomes


def predict_rfdetr_edge_masks(*args, **kwargs) -> List[np.ndarray]:
    """Return legacy edge masks, raising if any view is not usable."""

    outcomes = predict_rfdetr_predictions(*args, **kwargs)
    failures = [value for value in outcomes if isinstance(value, RFDETRInferenceError)]
    if failures:
        raise RFDETRInferenceError("; ".join(str(value) for value in failures))
    return [value.edge_mask for value in outcomes]
