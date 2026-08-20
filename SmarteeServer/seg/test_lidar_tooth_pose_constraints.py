import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from seg.lidar_tooth_pose_constraints import load_lidar_tooth_pose_constraints


def metadata(keyframe_id):
    return {
        "schemaVersion": 4,
        "figure8KeyframeID": keyframe_id,
        "isDirectView": True,
        "ssmDepthEligible": True,
        "trackingState": "normal",
        "matrixLayout": "column-major",
        "coordinateSystem": "ARKit camera-to-world",
        "cameraToReferenceTransform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
    }


def write_cloud(root, field, slot_id, *, keyframes=("K0", "K1", "K2"), depth_confidence=2, offset=0.0):
    view = Path(root) / "capture" / field
    view.mkdir(parents=True, exist_ok=True)
    count = 30
    point_k0 = np.column_stack((np.arange(count), np.zeros(count), np.ones(count))) * 0.001 + offset
    frame_ids = np.array([keyframes[index % len(keyframes)] for index in range(count)])
    np.savez_compressed(
        view / "dental_cloud.npz",
        pointK0=point_k0.astype(np.float32),
        keyframeID=frame_ids,
        instanceID=np.array(["local"] * count),
        slotID=np.array([slot_id] * count),
        detectorConfidence=np.full(count, 0.9, dtype=np.float32),
        depthConfidence=np.full(count, depth_confidence, dtype=np.uint8),
    )
    (view / "dental_cloud.json").write_text(json.dumps({
        "schemaVersion": 1,
        "pointCount": count,
        "perKeyframe": {keyframe_id: {"acceptedPointCount": int(np.count_nonzero(frame_ids == keyframe_id))} for keyframe_id in keyframes},
    }))
    for keyframe_id in keyframes:
        (view / f"{keyframe_id}.metadata.json").write_text(json.dumps(metadata(keyframe_id)))


class LiDARToothPoseConstraintTests(unittest.TestCase):
    def test_accepts_only_points_with_same_slot_in_k0_and_two_later_keyframes(self):
        with tempfile.TemporaryDirectory() as temporary:
            write_cloud(temporary, "front", "U-03")
            write_cloud(temporary, "leftLateral", "U-03")
            constraints, skipped = load_lidar_tooth_pose_constraints(Path(temporary), "capture", np.arange(28))

        self.assertEqual(skipped, {})
        self.assertEqual(set(constraints), {2})
        self.assertEqual({constraint.field for constraint in constraints[2]}, {"front", "leftLateral"})

    def test_accepts_one_weak_field_when_the_other_meets_the_strong_bar(self):
        # front only has 1 later keyframe (K1) — below the strong bar of 2 —
        # but leftLateral has the full 2 (K1, K2). Two independent camera
        # angles still agree the tooth is real; front just corroborates more
        # weakly than leftLateral. Should now be accepted.
        with tempfile.TemporaryDirectory() as temporary:
            write_cloud(temporary, "front", "U-03", keyframes=("K0", "K1"))
            write_cloud(temporary, "leftLateral", "U-03")
            constraints, skipped = load_lidar_tooth_pose_constraints(Path(temporary), "capture", np.arange(28))

        self.assertIn(2, constraints)
        self.assertEqual({c.field for c in constraints[2]}, {"front", "leftLateral"})

    def test_rejects_when_no_field_meets_the_strong_evidence_bar(self):
        # Both fields only have 1 later keyframe each — two weak guesses,
        # neither one strong enough to anchor the pair. Must stay rejected.
        with tempfile.TemporaryDirectory() as temporary:
            write_cloud(temporary, "front", "U-03", keyframes=("K0", "K1"))
            write_cloud(temporary, "leftLateral", "U-03", keyframes=("K0", "K1"))
            constraints, skipped = load_lidar_tooth_pose_constraints(Path(temporary), "capture", np.arange(28))

        self.assertEqual(constraints, {})
        self.assertEqual(skipped["U-03"], "no_field_meets_strong_evidence_bar")

    def test_rejects_a_field_with_zero_later_keyframes_even_as_the_weak_side(self):
        with tempfile.TemporaryDirectory() as temporary:
            write_cloud(temporary, "front", "U-03", keyframes=("K0",))
            write_cloud(temporary, "leftLateral", "U-03")
            constraints, skipped = load_lidar_tooth_pose_constraints(Path(temporary), "capture", np.arange(28))

        self.assertEqual(constraints, {})
        self.assertEqual(skipped["U-03@front"], "insufficient_repeated_keyframes")

    def test_rejects_low_depth_confidence_and_unassigned_points_from_pose_loss_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            write_cloud(temporary, "front", "U-03", depth_confidence=1)
            write_cloud(temporary, "leftLateral", "U-03")
            constraints, skipped = load_lidar_tooth_pose_constraints(Path(temporary), "capture", np.arange(28))

        self.assertEqual(constraints, {})
        self.assertEqual(skipped["U-03@front"], "insufficient_high_confidence_points")

    def test_rejects_tooth_seen_in_only_one_direct_field(self):
        with tempfile.TemporaryDirectory() as temporary:
            write_cloud(temporary, "front", "U-03")
            constraints, skipped = load_lidar_tooth_pose_constraints(Path(temporary), "capture", np.arange(28))

        self.assertEqual(constraints, {})
        self.assertEqual(skipped["U-03"], "insufficient_distinct_fields")

    def test_accepts_a_lone_strong_mandibular_field_without_a_second_field(self):
        # mandibular assigns slots via direct DP alignment (no row-split
        # guess), so it's trusted alone once it clears the strong bar.
        with tempfile.TemporaryDirectory() as temporary:
            write_cloud(temporary, "mandibular", "L-03")
            constraints, skipped = load_lidar_tooth_pose_constraints(Path(temporary), "capture", np.arange(28))

        self.assertIn(16, constraints)
        self.assertEqual({c.field for c in constraints[16]}, {"mandibular"})
        self.assertEqual(skipped, {})

    def test_rejects_a_lone_weak_mandibular_field_without_a_second_field(self):
        with tempfile.TemporaryDirectory() as temporary:
            write_cloud(temporary, "mandibular", "L-03", keyframes=("K0", "K1"))
            constraints, skipped = load_lidar_tooth_pose_constraints(Path(temporary), "capture", np.arange(28))

        self.assertEqual(constraints, {})
        self.assertEqual(skipped["L-03"], "insufficient_distinct_fields")

    def test_rejects_a_lone_moderately_tracked_lateral_field_without_a_second_field(self):
        # leftLateral must first guess an ambiguous upper/lower row split, so
        # it needs near-full keyframe tracking to be trusted alone — the
        # ordinary two-later-keyframe bar mandibular gets is not enough here.
        with tempfile.TemporaryDirectory() as temporary:
            write_cloud(temporary, "leftLateral", "U-03")
            constraints, skipped = load_lidar_tooth_pose_constraints(Path(temporary), "capture", np.arange(28))

        self.assertEqual(constraints, {})
        self.assertEqual(skipped["U-03"], "insufficient_distinct_fields")

    def test_accepts_a_lone_near_fully_tracked_lateral_field_without_a_second_field(self):
        with tempfile.TemporaryDirectory() as temporary:
            write_cloud(temporary, "rightLateral", "U-03", keyframes=("K0", "K1", "K2", "K3", "K4", "K5", "K6"))
            constraints, skipped = load_lidar_tooth_pose_constraints(Path(temporary), "capture", np.arange(28))

        self.assertIn(2, constraints)
        self.assertEqual({c.field for c in constraints[2]}, {"rightLateral"})
        self.assertEqual(skipped, {})

    def test_keeps_same_tooth_points_in_each_field_reference_frame_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            write_cloud(temporary, "front", "U-03", offset=0.0)
            write_cloud(temporary, "leftLateral", "U-03", offset=1.0)
            constraints, _ = load_lidar_tooth_pose_constraints(Path(temporary), "capture", np.arange(28))

        by_field = {constraint.field: constraint for constraint in constraints[2]}
        self.assertFalse(np.array_equal(by_field["front"].points_k0_metres, by_field["leftLateral"].points_k0_metres))

    def test_unknown_or_inactive_slot_never_yields_a_constraint(self):
        with tempfile.TemporaryDirectory() as temporary:
            write_cloud(temporary, "front", "L-03")
            write_cloud(temporary, "leftLateral", "L-03")
            constraints, skipped = load_lidar_tooth_pose_constraints(Path(temporary), "capture", np.arange(14))

        self.assertEqual(constraints, {})
        self.assertEqual(skipped["L-03@front"], "unknown_or_inactive_slot")


if __name__ == "__main__":
    unittest.main()
