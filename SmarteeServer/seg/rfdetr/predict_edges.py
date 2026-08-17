#!/usr/bin/env python3
"""Convert RF-DETR tooth instance masks into Smartee-style binary edge masks."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
os.environ.setdefault("RF_HOME", str(SCRIPT_DIR / ".cache" / "models"))
os.environ.setdefault("MPLCONFIGDIR", str(SCRIPT_DIR / ".cache" / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(SCRIPT_DIR / ".cache" / "xdg"))

import cv2
import numpy as np
import torch
from rfdetr import RFDETRSegSmall


def resolve_device(requested: str) -> str:
    if requested != "auto":
        if requested == "mps" and not torch.backends.mps.is_available():
            raise ValueError("MPS was requested but is not available to PyTorch.")
        if requested == "cuda" and not torch.cuda.is_available():
            raise ValueError("CUDA was requested but is not available to PyTorch.")
        return requested
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def edge_mask_from_instances(
    masks: np.ndarray, edge_width: int | None = 800, thickness: int = 1
) -> np.ndarray:
    """Trace every separate tooth mask, retaining boundaries between teeth."""

    if masks.ndim != 3:
        raise ValueError(f"Expected masks shaped (instances, height, width), got {masks.shape}.")
    if thickness < 1:
        raise ValueError("thickness must be at least 1 pixel.")

    _, height, width = masks.shape
    edge_mask = np.zeros((height, width), dtype=np.uint8)
    for mask in masks:
        contours, _ = cv2.findContours(
            mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
        )
        cv2.drawContours(edge_mask, contours, contourIdx=-1, color=255, thickness=thickness)

    if edge_width is not None:
        if edge_width <= 0:
            raise ValueError("edge_width must be positive or omitted.")
        output_height = int(height * edge_width / width)
        edge_mask = cv2.resize(
            edge_mask, (edge_width, output_height), interpolation=cv2.INTER_NEAREST
        )
    return edge_mask


def overlay_edges(image: np.ndarray, edge_mask: np.ndarray) -> np.ndarray:
    """Return an RGB inspection image with green predicted edges."""

    resized = cv2.resize(
        image, (edge_mask.shape[1], edge_mask.shape[0]), interpolation=cv2.INTER_LINEAR
    )
    if resized.ndim == 2:
        resized = cv2.cvtColor(resized, cv2.COLOR_GRAY2RGB)
    elif resized.shape[2] == 4:
        resized = cv2.cvtColor(resized, cv2.COLOR_RGBA2RGB)
    else:
        resized = resized[..., :3]
    overlay = resized.copy()
    overlay[edge_mask > 0] = (0, 255, 0)
    return overlay


def normalize_instance_masks(
    masks: np.ndarray, image_height: int, image_width: int
) -> np.ndarray:
    """Convert model masks to boolean masks at the source RGB geometry."""

    masks = np.asarray(masks)
    if masks.ndim != 3:
        raise ValueError(
            "Expected masks shaped (instances, height, width), "
            f"got {masks.shape}."
        )

    normalized = []
    for mask in masks:
        binary = mask.astype(bool).astype(np.uint8)
        if binary.shape != (image_height, image_width):
            binary = cv2.resize(
                binary,
                (image_width, image_height),
                interpolation=cv2.INTER_NEAREST,
            )
        normalized.append(binary.astype(bool))

    if not normalized:
        return np.empty((0, image_height, image_width), dtype=bool)
    return np.stack(normalized, axis=0)


def write_instance_artifacts(
    output_dir: Path,
    stem: str,
    masks: np.ndarray,
    confidences: np.ndarray,
    image_height: int,
    image_width: int,
) -> list[dict[str, Any]]:
    """Persist one lossless binary PNG and record for each non-empty tooth."""

    normalized = normalize_instance_masks(masks, image_height, image_width)
    confidences = np.asarray(confidences, dtype=np.float32).reshape(-1)
    if len(confidences) != len(normalized):
        raise ValueError(
            f"RF-DETR mask/confidence count mismatch: {len(normalized)} masks, "
            f"{len(confidences)} confidence values."
        )

    records: list[dict[str, Any]] = []
    for index, (mask, confidence) in enumerate(zip(normalized, confidences)):
        rows, columns = np.nonzero(mask)
        if len(rows) == 0:
            continue
        local_id = f"instance-{index:03d}"
        filename = f"{stem}-{local_id}.png"
        encoded = mask.astype(np.uint8) * 255
        if not cv2.imwrite(str(output_dir / filename), encoded):
            raise OSError(f"Could not write RF-DETR instance mask: {filename}")
        x0, x1 = int(columns.min()), int(columns.max())
        y0, y1 = int(rows.min()), int(rows.max())
        records.append(
            {
                "localId": local_id,
                "mask": filename,
                "confidence": round(float(confidence), 6),
                "bboxXYWH": [x0, y0, x1 - x0 + 1, y1 - y0 + 1],
                "centroidXY": [float(columns.mean()), float(rows.mean())],
                "areaPixels": int(mask.sum()),
            }
        )
    return records


INSTANCE_COLOURS = np.array(
    [
        [230, 57, 70],
        [29, 185, 84],
        [48, 122, 246],
        [255, 159, 10],
        [175, 82, 222],
        [90, 200, 250],
    ],
    dtype=np.uint8,
)


def overlay_instances(image: np.ndarray, masks: np.ndarray) -> np.ndarray:
    """Return an RGB preview with each tooth instance shown in a distinct colour."""

    output = image[..., :3].astype(np.float32).copy()
    normalized = normalize_instance_masks(masks, image.shape[0], image.shape[1])
    for index, mask in enumerate(normalized):
        colour = INSTANCE_COLOURS[index % len(INSTANCE_COLOURS)].astype(np.float32)
        output[mask] = 0.45 * output[mask] + 0.55 * colour
    return np.clip(output, 0, 255).astype(np.uint8)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=SCRIPT_DIR / "runs" / "small-multiview" / "checkpoint_best_regular.pth",
    )
    parser.add_argument("--confidence", type=float, default=0.5)
    parser.add_argument("--edge-width", type=int, default=800)
    parser.add_argument("--thickness", type=int, default=1)
    parser.add_argument("--device", choices=("auto", "mps", "cpu", "cuda"), default="auto")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    images = [path.resolve() for path in args.input]
    checkpoint = args.checkpoint.resolve()
    output = args.output.resolve()
    if not images:
        raise ValueError("At least one input image is required.")
    missing = [path for path in images if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Input image not found: {missing[0]}")
    if not checkpoint.is_file():
        raise FileNotFoundError(f"Checkpoint not found: {checkpoint}")
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    if not 0.0 <= args.confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1.")

    device = resolve_device(args.device)
    print(f"Device: {device}")
    print(f"Checkpoint: {checkpoint}")
    print(f"Images: {len(images)}")
    model = RFDETRSegSmall.from_checkpoint(checkpoint, device=device)

    output.mkdir(parents=True)
    manifest_images: list[dict[str, Any]] = []
    for image_path in images:
        detections = model.predict(str(image_path), threshold=args.confidence)
        masks = detections.mask
        image = cv2.cvtColor(cv2.imread(str(image_path)), cv2.COLOR_BGR2RGB)
        if masks is None or len(masks) == 0:
            masks = np.empty((0, *image.shape[:2]))
        confidence_values = getattr(detections, "confidence", np.empty(0))
        height, width = image.shape[:2]
        normalized_masks = normalize_instance_masks(np.asarray(masks), height, width)
        edge_mask = edge_mask_from_instances(
            normalized_masks, edge_width=args.edge_width, thickness=args.thickness
        )
        stem = image_path.stem
        edge_path = output / f"{stem}_edge.png"
        overlay_path = output / f"{stem}_overlay.png"
        instance_records = write_instance_artifacts(
            output,
            stem,
            normalized_masks,
            np.asarray(confidence_values),
            height,
            width,
        )
        overlay = overlay_instances(image, normalized_masks)
        cv2.imwrite(str(edge_path), edge_mask)
        cv2.imwrite(str(overlay_path), cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR))
        manifest_images.append(
            {
                "image": str(image_path),
                "stem": stem,
                "width": width,
                "height": height,
                "edgeMask": edge_path.name,
                "overlay": overlay_path.name,
                "instances": instance_records,
            }
        )
        print(f"{image_path.name}: {len(instance_records)} tooth masks")

    with (output / "manifest.json").open("w", encoding="utf-8") as stream:
        json.dump({"schemaVersion": 1, "images": manifest_images}, stream, indent=2)
        stream.write("\n")
    print(f"Saved previews: {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
