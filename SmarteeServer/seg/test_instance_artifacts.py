import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import skimage.io

from seg.instance_artifacts import write_instance_bundle
from seg.prediction_types import EdgePrediction, ToothInstancePrediction


class InstanceArtifactPersistenceTests(unittest.TestCase):
    def prediction(self, source="rfdetr"):
        mask = np.zeros((8, 12), dtype=np.uint8)
        mask[1:5, 2:6] = 255
        return EdgePrediction(
            edge_mask=np.ones((10, 20), dtype=np.uint8) * 255,
            source=source,
            instances=(
                ToothInstancePrediction(
                    local_id="instance-000",
                    mask=mask,
                    confidence=0.91,
                    bbox_xywh=(2, 1, 4, 4),
                    centroid_xy=(3.5, 2.5),
                    area_pixels=16,
                ),
            ) if source == "rfdetr" else (),
        )

    def source_image(self, root):
        path = Path(root) / "capture-pc10-lidar-4.png"
        skimage.io.imsave(
            str(path), np.zeros((8, 12, 3), dtype=np.uint8), check_contrast=False
        )
        return path

    def view_payload(self, source_image, prediction, fallback_reason=None):
        return {
            "prediction": prediction,
            "sourceImage": str(source_image),
            "checkpoint": "frontal",
            "keyframe": None,
            "fallbackReason": fallback_reason,
        }

    def test_writes_binary_png_and_versioned_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            source_path = self.source_image(root)
            manifest_path = write_instance_bundle(
                Path(root),
                "capture-pc10-lidar",
                {4: self.view_payload(source_path, self.prediction())},
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            view = manifest["views"]["4"]
            self.assertEqual(manifest["schemaVersion"], 1)
            self.assertEqual(view["backend"], "rfdetr")
            self.assertEqual(view["instanceCount"], 1)
            self.assertEqual((view["rgbWidth"], view["rgbHeight"]), (12, 8))
            self.assertEqual(view["rgbOrientation"], "up")
            self.assertEqual(view["checkpoint"], "frontal")
            self.assertIsNone(view["keyframe"])
            saved = skimage.io.imread(str(Path(root) / view["instances"][0]["mask"]))
            self.assertEqual(saved.shape, (8, 12))
            self.assertEqual(set(np.unique(saved)), {0, 255})
            overlay = skimage.io.imread(str(Path(root) / view["overlay"]))
            self.assertEqual(overlay.shape, (8, 12, 3))
            self.assertTrue(np.any(overlay))

    def test_h5_view_records_zero_instances_and_fallback_reason(self):
        with tempfile.TemporaryDirectory() as root:
            source_path = self.source_image(root)
            manifest_path = write_instance_bundle(
                Path(root),
                "capture-pc10-lidar",
                {
                    4: self.view_payload(
                        source_path,
                        self.prediction(source="h5"),
                        "checkpoint missing",
                    )
                },
            )
            view = json.loads(manifest_path.read_text())["views"]["4"]
            self.assertEqual(view["backend"], "h5")
            self.assertEqual(view["instances"], [])
            self.assertEqual(view["fallbackReason"], "checkpoint missing")


if __name__ == "__main__":
    unittest.main()
