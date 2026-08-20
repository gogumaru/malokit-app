import unittest

import numpy as np

from seg.lidar_tooth_association import associate_instance_depth


class LiDARToothAssociationTests(unittest.TestCase):
    def test_associates_only_eroded_valid_depth_cells_with_full_provenance(self):
        mask = np.full((5, 5), 255, dtype=np.uint8)
        depth = np.full((5, 5), 1.0, dtype=np.float32)
        confidence = np.full((5, 5), 2, dtype=np.uint8)
        confidence[1:4, 1:4] = 0
        confidence[2, 2] = 2
        confidence[1, 3] = 2
        confidence[3, 1] = 2
        confidence[3, 3] = 2
        depth[1, 3] = np.nan
        depth[3, 1] = 0.04
        depth[3, 3] = 2.01
        result = associate_instance_depth(
            mask=mask,
            keyframe_id="K4",
            instance_id="tooth-7",
            detector_confidence=0.87,
            depth_metres=depth,
            confidence_values=confidence,
            metadata={
                "intrinsicMatrix": [5, 0, 0, 0, 5, 0, 2, 2, 1],
                "intrinsicReferenceWidth": 5,
                "intrinsicReferenceHeight": 5,
                "cameraToReferenceTransform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0.01, 0, 0, 1],
            },
        )

        self.assertEqual(len(result["accepted"]), 1)
        point = result["accepted"][0]
        self.assertEqual(point["keyframeID"], "K4")
        self.assertEqual(point["instanceID"], "tooth-7")
        self.assertEqual(point["depthConfidence"], 2)
        self.assertEqual(point["rgbXY"], [2, 2])
        self.assertEqual(point["depthXY"], [2, 2])
        self.assertEqual(point["pointK0"], [0.01, 0.0, -1.0])
        self.assertEqual(point["rejectionReason"], None)
        self.assertEqual(result["rejectionCounts"]["mask_edge_eroded"], 16)
        self.assertEqual(result["rejectionCounts"]["depth_confidence_zero"], 5)
        self.assertEqual(result["rejectionCounts"]["depth_not_finite"], 1)
        self.assertEqual(result["rejectionCounts"]["depth_out_of_range"], 2)

    def test_associated_depth_record_preserves_an_assigned_slot_id(self):
        mask = np.full((3, 3), 255, dtype=np.uint8)
        result = associate_instance_depth(
            mask=mask,
            keyframe_id="K0",
            instance_id="tooth-4",
            slot_id="L-04",
            detector_confidence=0.9,
            depth_metres=np.full((3, 3), 1.0, dtype=np.float32),
            confidence_values=np.full((3, 3), 2, dtype=np.uint8),
            metadata={
                "intrinsicMatrix": [5, 0, 0, 0, 5, 0, 1, 1, 1],
                "intrinsicReferenceWidth": 3,
                "intrinsicReferenceHeight": 3,
                "cameraToReferenceTransform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            },
        )

        self.assertEqual(result["accepted"][0]["slotID"], "L-04")


if __name__ == "__main__":
    unittest.main()
