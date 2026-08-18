import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import skimage.io

from seg.lidar_keyframe_segmentation import segment_lidar_keyframes
from seg.prediction_types import EdgePrediction, ToothInstancePrediction
from seg.rfdetr_bridge import RFDETRInferenceError


KEYFRAME_IDS = tuple(f"K{index}" for index in range(7))


class LiDARKeyframeSegmentationTests(unittest.TestCase):
    def write_bundle(self, root: Path, mirrored_keyframe=None):
        for keyframe_id in KEYFRAME_IDS:
            rgb = np.zeros((3, 4, 3), dtype=np.uint8)
            skimage.io.imsave(str(root / f"{keyframe_id}.rgb.png"), rgb, check_contrast=False)
            (root / f"{keyframe_id}.depth.f32").write_bytes(np.ones(2, dtype="<f4").tobytes())
            (root / f"{keyframe_id}.confidence.u8").write_bytes(bytes([2, 2]))
            metadata = {
                "schemaVersion": 4,
                "depthWidth": 2,
                "depthHeight": 1,
                "bytesPerSample": 4,
                "isDirectView": keyframe_id != mirrored_keyframe,
                "ssmDepthEligible": keyframe_id != mirrored_keyframe,
                "trackingState": "normal",
                "matrixLayout": "column-major",
                "coordinateSystem": "ARKit camera-to-world",
                "cameraToReferenceTransform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            }
            (root / f"{keyframe_id}.metadata.json").write_text(json.dumps(metadata))
        (root / "figure8_manifest.json").write_text(
            json.dumps({"schemaVersion": 1, "keyframes": [{"id": keyframe_id} for keyframe_id in KEYFRAME_IDS]})
        )

    @staticmethod
    def predictor(image_paths):
        mask_a = np.zeros((3, 4), dtype=np.uint8)
        mask_a[:, :2] = 255
        mask_b = np.zeros((3, 4), dtype=np.uint8)
        mask_b[:, 2:] = 255
        instances = (
            ToothInstancePrediction("tooth-a", mask_a, 0.9, (0, 0, 2, 3), (0.5, 1.0), 6),
            ToothInstancePrediction("tooth-b", mask_b, 0.8, (2, 0, 2, 3), (2.5, 1.0), 6),
        )
        return [EdgePrediction(mask_a, "rfdetr", instances) for _ in image_paths]

    def test_segments_complete_bundle_in_keyframe_order_and_persists_masks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_bundle(root)
            requested = []

            def recording_predictor(paths):
                requested.extend(Path(path).name for path in paths)
                return self.predictor(paths)

            summary = segment_lidar_keyframes(root, predictor=recording_predictor)

            self.assertEqual(requested, [f"{keyframe_id}.rgb.png" for keyframe_id in KEYFRAME_IDS])
            manifest = json.loads((root / "segmentation" / "instances.json").read_text())
            self.assertEqual(manifest["keyframes"]["K0"]["backend"], "rfdetr")
            self.assertEqual(manifest["keyframes"]["K0"]["instanceCount"], 2)
            self.assertTrue((root / "segmentation" / "K0-instance-000.png").is_file())
            self.assertTrue((root / "segmentation" / "K6-instance-001.png").is_file())
            self.assertEqual(summary["keyframeCount"], 7)

    def test_skips_mirrored_keyframe_without_running_a_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_bundle(root, mirrored_keyframe="K3")
            requested = []

            def recording_predictor(paths):
                requested.extend(Path(path).name for path in paths)
                return self.predictor(paths)

            segment_lidar_keyframes(root, predictor=recording_predictor)

            manifest = json.loads((root / "segmentation" / "instances.json").read_text())
            self.assertNotIn("K3.rgb.png", requested)
            self.assertEqual(manifest["keyframes"]["K3"]["reason"], "ineligible_keyframe")
            self.assertFalse((root / "segmentation" / "K3-instance-000.png").exists())

    def test_preserves_the_rfdetr_failure_reason_for_an_unusable_keyframe(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_bundle(root)

            def failing_predictor(paths):
                predictions = list(self.predictor(paths))
                predictions[1] = RFDETRInferenceError("K1.rgb.png: RF-DETR produced an empty edge mask")
                return predictions

            segment_lidar_keyframes(root, predictor=failing_predictor)

            manifest = json.loads((root / "segmentation" / "instances.json").read_text())
            self.assertEqual(
                manifest["keyframes"]["K1"]["reason"],
                "rfdetr_failure: K1.rgb.png: RF-DETR produced an empty edge mask",
            )

    def test_writes_slot_assignment_manifest_when_the_reconstruction_view_is_known(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_bundle(root)

            segment_lidar_keyframes(
                root,
                predictor=self.predictor,
                field="front",
                photo_index=4,
                active_original_indices=np.arange(28),
            )

            slots = json.loads((root / "segmentation" / "slot_assignments.json").read_text())
            self.assertEqual(slots["schemaVersion"], 2)
            self.assertEqual(slots["field"], "front")
            self.assertEqual(slots["photoIndex"], 4)
            self.assertIn("assignments", slots["keyframes"]["K0"])
            self.assertEqual(slots["keyframes"]["K1"]["assignments"], {})
            self.assertEqual(
                set(slots["keyframes"]["K1"]["rejections"].values()),
                {"awaiting_k0_surface_match"},
            )


if __name__ == "__main__":
    unittest.main()
