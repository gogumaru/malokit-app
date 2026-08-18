"""Persist RF-DETR tooth instances for inspection and later multi-view work."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

import numpy as np
import skimage.io


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


def _load_rgb(path: str) -> np.ndarray:
    image = np.asarray(skimage.io.imread(path))
    if image.ndim == 2:
        image = np.repeat(image[..., None], 3, axis=2)
    if image.ndim != 3 or image.shape[2] < 3:
        raise ValueError(f"Unsupported source RGB geometry: {image.shape}.")
    return image[..., :3].astype(np.uint8)


def write_instance_bundle(output_dir: Path, tag: str, views: Dict[int, dict]) -> Path:
    """Write immutable binary instance masks plus a manifest for one request."""

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_views = {}
    for photo_index, payload in sorted(views.items()):
        prediction = payload["prediction"]
        source_image = str(payload["sourceImage"])
        rgb = _load_rgb(source_image)
        rgb_height, rgb_width = rgb.shape[:2]
        overlay = rgb.astype(np.float32).copy()
        instance_records = []
        for ordinal, instance in enumerate(prediction.instances):
            filename = f"{photo_index}-instance-{ordinal:03d}.png"
            mask = ((np.asarray(instance.mask) > 127) * 255).astype(np.uint8)
            if mask.shape != (rgb_height, rgb_width) or not np.any(mask):
                raise ValueError(
                    f"Invalid instance mask for photo {photo_index}, {instance.local_id}: "
                    f"{mask.shape}, expected {(rgb_height, rgb_width)}."
                )
            skimage.io.imsave(str(output_dir / filename), mask, check_contrast=False)
            colour = INSTANCE_COLOURS[ordinal % len(INSTANCE_COLOURS)].astype(np.float32)
            foreground = mask > 127
            overlay[foreground] = 0.45 * overlay[foreground] + 0.55 * colour
            instance_records.append(
                {
                    "localId": instance.local_id,
                    "mask": filename,
                    "confidence": instance.confidence,
                    "bboxXYWH": list(instance.bbox_xywh),
                    "centroidXY": list(instance.centroid_xy),
                    "areaPixels": instance.area_pixels,
                }
            )
        overlay_filename = f"{photo_index}-instances-overlay.png"
        skimage.io.imsave(
            str(output_dir / overlay_filename),
            np.clip(overlay, 0, 255).astype(np.uint8),
            check_contrast=False,
        )
        manifest_views[str(photo_index)] = {
            "backend": prediction.source,
            "sourceImage": source_image,
            "rgbWidth": rgb_width,
            "rgbHeight": rgb_height,
            "rgbOrientation": "up",
            "checkpoint": str(payload["checkpoint"]),
            "keyframe": payload.get("keyframe"),
            "overlay": overlay_filename,
            "fallbackReason": payload.get("fallbackReason"),
            "instanceCount": len(instance_records),
            "instances": instance_records,
        }

    manifest = {"schemaVersion": 1, "tag": tag, "views": manifest_views}
    manifest_path = output_dir / "instances.json"
    temporary_path = output_dir / "instances.json.tmp"
    temporary_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(manifest_path)
    return manifest_path
