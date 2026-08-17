import json
import tempfile
import unittest
from pathlib import Path

import h5py

from seg.lidar_constraint_diagnostics import (
    assess_coarse_lidar_candidate,
    build_lidar_diagnostic_payload,
    persist_lidar_diagnostic_json,
    write_lidar_h5_diagnostics,
)


class LiDARConstraintDiagnosticTests(unittest.TestCase):
    def test_accepts_only_a_surface_improvement_without_photo_regression(self):
        decision = assess_coarse_lidar_candidate(
            photo_only_median_millimetres=4.0,
            photo_only_p95_millimetres=8.0,
            coarse_median_millimetres=3.0,
            coarse_p95_millimetres=7.5,
            photo_contour_loss_before=100.0,
            photo_contour_loss_after=102.0,
            pair_count=120,
        )

        self.assertTrue(decision.accepted)
        self.assertEqual(decision.reason, "coarse_lidar_improved")

    def test_rejects_and_requests_photo_fallback_when_surface_distance_worsens(self):
        decision = assess_coarse_lidar_candidate(
            photo_only_median_millimetres=50.25,
            photo_only_p95_millimetres=96.71,
            coarse_median_millimetres=53.57,
            coarse_p95_millimetres=98.71,
            photo_contour_loss_before=61.09,
            photo_contour_loss_after=45.55,
            pair_count=79_991,
        )

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "coarse_surface_distance_not_improved")

    def test_rejects_photo_regression_over_eight_percent_even_if_surface_improves(self):
        decision = assess_coarse_lidar_candidate(
            photo_only_median_millimetres=4.0,
            photo_only_p95_millimetres=8.0,
            coarse_median_millimetres=3.0,
            coarse_p95_millimetres=7.0,
            photo_contour_loss_before=100.0,
            photo_contour_loss_after=108.01,
            pair_count=120,
        )

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "photo_contour_regression_exceeds_eight_percent")

    def test_accepts_photo_regression_up_to_eight_percent(self):
        decision = assess_coarse_lidar_candidate(
            photo_only_median_millimetres=4.0,
            photo_only_p95_millimetres=8.0,
            coarse_median_millimetres=3.0,
            coarse_p95_millimetres=7.0,
            photo_contour_loss_before=100.0,
            photo_contour_loss_after=107.0,
            pair_count=120,
        )

        self.assertTrue(decision.accepted)

    def test_accepts_surface_distance_within_the_small_tolerance_window(self):
        decision = assess_coarse_lidar_candidate(
            photo_only_median_millimetres=50.0,
            photo_only_p95_millimetres=100.0,
            coarse_median_millimetres=51.0,  # 1mm worse: within the 1.5mm tolerance
            coarse_p95_millimetres=102.5,  # 2.5mm worse: within the 3.0mm tolerance
            photo_contour_loss_before=100.0,
            photo_contour_loss_after=100.0,
            pair_count=120,
        )

        self.assertTrue(decision.accepted)

    def test_rejects_surface_distance_beyond_the_small_tolerance_window(self):
        decision = assess_coarse_lidar_candidate(
            photo_only_median_millimetres=50.0,
            photo_only_p95_millimetres=100.0,
            coarse_median_millimetres=53.0,  # 3mm worse: exceeds the 1.5mm tolerance
            coarse_p95_millimetres=100.0,
            photo_contour_loss_before=100.0,
            photo_contour_loss_after=100.0,
            pair_count=120,
        )

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "coarse_surface_distance_not_improved")

    def test_rejects_missing_pairs_or_nonfinite_metrics(self):
        no_pairs = assess_coarse_lidar_candidate(
            photo_only_median_millimetres=4.0,
            photo_only_p95_millimetres=8.0,
            coarse_median_millimetres=3.0,
            coarse_p95_millimetres=7.0,
            photo_contour_loss_before=100.0,
            photo_contour_loss_after=99.0,
            pair_count=0,
        )
        invalid = assess_coarse_lidar_candidate(
            photo_only_median_millimetres=float("nan"),
            photo_only_p95_millimetres=8.0,
            coarse_median_millimetres=3.0,
            coarse_p95_millimetres=7.0,
            photo_contour_loss_before=100.0,
            photo_contour_loss_after=99.0,
            pair_count=120,
        )

        self.assertEqual(no_pairs.reason, "no_in_gate_correspondences")
        self.assertEqual(invalid.reason, "coarse_diagnostics_nonfinite")

    def diagnostic_payload(self):
        return build_lidar_diagnostic_payload(
            coarse={
                "enabled": True,
                "eligibleViews": ["front"],
                "pairCounts": {"front": 120},
                "photoOnlyMedianDistanceMillimetres": 100.0,
                "photoOnlyP95DistanceMillimetres": 101.0,
                "coarseLiDARMedianDistanceMillimetres": 1.5,
                "coarseLiDARP95DistanceMillimetres": 2.0,
                "stage2PoseParameterDeltaFromCoarseLiDAR": 0.0,
                "stage3FeatureVectorDeltaFromCoarseLiDAR": 0.0,
            },
            tooth_pose={"enabled": False, "reason": "no_eligible_constraint"},
            tooth_shape={"enabled": False, "reason": "fewer_than_two_fields_with_m6_pairs"},
        )

    def test_writes_atomic_json_with_all_milestone_diagnostics(self):
        payload = self.diagnostic_payload()
        with tempfile.TemporaryDirectory() as temporary:
            path = persist_lidar_diagnostic_json(Path(temporary), "tag-123", payload)
            decoded = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(decoded["schemaVersion"], 1)
        self.assertEqual(decoded["coarse"]["pairCounts"]["front"], 120)
        self.assertEqual(decoded["toothPose"]["reason"], "no_eligible_constraint")
        self.assertEqual(decoded["toothShape"]["reason"], "fewer_than_two_fields_with_m6_pairs")

    def test_writes_m5_dataset_without_changing_existing_mesh_datasets(self):
        payload = self.diagnostic_payload()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "diagnostics.h5"
            with h5py.File(path, "w") as file:
                group = file.create_group("EMOPT")
                group.create_dataset("UPPER_PRED", data=[1.0, 2.0])
                write_lidar_h5_diagnostics(group, payload)
            with h5py.File(path, "r") as file:
                group = file["EMOPT"]
                encoded = group["LIDAR_COARSE_DIAGNOSTICS"][()]
                if isinstance(encoded, bytes):
                    encoded = encoded.decode("utf-8")
                decoded = json.loads(encoded)
                upper = group["UPPER_PRED"][:]

        self.assertEqual(decoded["coarseLiDARMedianDistanceMillimetres"], 1.5)
        self.assertEqual(upper.tolist(), [1.0, 2.0])


if __name__ == "__main__":
    unittest.main()
