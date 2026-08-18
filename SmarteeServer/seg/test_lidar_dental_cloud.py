import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from seg.lidar_dental_cloud import fuse_dental_points, persist_dental_cloud


def point(keyframe_id, xyz, depth_confidence, detector_confidence, reason=None, slot_id=None):
    return {
        "keyframeID": keyframe_id,
        "instanceID": f"{keyframe_id}-tooth",
        "slotID": slot_id,
        "detectorConfidence": detector_confidence,
        "depthConfidence": depth_confidence,
        "rgbXY": [2, 2],
        "depthXY": [1, 1],
        "pointK0": list(xyz) if xyz is not None else None,
        "rejectionReason": reason,
    }


class LiDARDentalCloudTests(unittest.TestCase):
    def test_relabels_records_from_k0_propagation_without_changing_points(self):
        records = [
            point("K0", (0.0, 0.0, -1.0), 2, 0.9, slot_id="U-04"),
            point("K2", (0.004, 0.0, -1.0), 2, 0.9, slot_id="U-09"),
            point("K3", (0.008, 0.0, -1.0), 2, 0.9, slot_id="U-09"),
        ]
        assignments = {
            "K0": {"K0-tooth": "U-04"},
            "K2": {"K2-tooth": "U-04"},
            "K3": {},
        }

        from seg.lidar_dental_cloud import apply_propagated_slots

        relabeled = apply_propagated_slots(records, assignments)

        self.assertEqual([record["slotID"] for record in relabeled], ["U-04", "U-04", None])
        self.assertEqual(
            [record["pointK0"] for record in relabeled],
            [record["pointK0"] for record in records],
        )

    def test_fuses_same_voxel_by_depth_then_detector_confidence(self):
        result = fuse_dental_points(
            [
                point("K0", (0.0010, 0.0, -1.0), 1, 0.99),
                point("K4", (0.0015, 0.0, -1.0), 2, 0.70),
                point("K6", (0.0041, 0.0, -1.0), 2, 0.80),
                point("K1", None, 0, 0.90, "mask_edge_eroded"),
            ]
        )

        self.assertEqual(len(result["points"]), 2)
        self.assertEqual(result["points"][0]["keyframeID"], "K4")
        self.assertEqual(result["perKeyframe"]["K4"]["acceptedPointCount"], 1)
        self.assertEqual(result["rejectionCounts"]["mask_edge_eroded"], 1)

    def test_persists_selected_representatives_without_touching_keyframes(self):
        fused = fuse_dental_points([point("K0", (0.0, 0.0, -1.0), 2, 0.9)])
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "K0.rgb.png").write_bytes(b"existing-keyframe")
            summary = persist_dental_cloud(root, fused)

            self.assertEqual(summary["pointCount"], 1)
            self.assertTrue((root / "dental_cloud.json").is_file())
            self.assertTrue((root / "dental_cloud.npz").is_file())
            self.assertEqual((root / "K0.rgb.png").read_bytes(), b"existing-keyframe")
            payload = json.loads((root / "dental_cloud.json").read_text())
            self.assertEqual(payload["pointCount"], 1)

    def test_npz_round_trip_contains_slot_ids_aligned_with_points(self):
        fused = fuse_dental_points([
            point("K0", (0.0, 0.0, -1.0), 2, 0.9, slot_id="U-03"),
            point("K2", (0.004, 0.0, -1.0), 2, 0.9, slot_id=None),
        ])
        with tempfile.TemporaryDirectory() as temp_dir:
            persist_dental_cloud(Path(temp_dir), fused)
            with np.load(Path(temp_dir) / "dental_cloud.npz", allow_pickle=False) as cloud:
                self.assertEqual(cloud["slotID"].tolist(), ["U-03", ""])
                self.assertEqual(len(cloud["slotID"]), len(cloud["pointK0"]))


if __name__ == "__main__":
    unittest.main()
