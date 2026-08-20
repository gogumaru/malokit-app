import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

from main import (
    apply_coarse_lidar_acceptance_gate,
    build_argument_parser,
    configure_reconstruction_random_seed,
    run_gated_m7_shape_experiment,
    run_global_emopt_stages,
    resolve_reconstruction_image_path,
    select_best_coarse_lidar_candidate,
    validate_lidar_milestone_ceiling,
)


class FakeLiDAREngine:
    def __init__(self):
        self.lidar_constraints = {4: object()}
        self.lidar_tooth_pose_constraints = {0: (object(), object())}
        self.lidar_diagnostics = {
            "enabled": True,
            "photoOnlyMedianDistanceMillimetres": 50.25,
            "photoOnlyP95DistanceMillimetres": 96.71,
            "coarseLiDARMedianDistanceMillimetres": 53.57,
            "coarseLiDARP95DistanceMillimetres": 98.71,
            "photoContourLossBefore": 61.09,
            "photoContourLossAfter": 45.55,
            "pairCounts": {"front": 25_999},
        }
        self.lidar_tooth_pose_diagnostics = {"enabled": True}
        self.lidar_tooth_shape_constraints = {0: (object(),)}
        self.lidar_tooth_shape_correspondences = {(0, "front"): object()}
        self.lidar_tooth_shape_diagnostics = {"enabled": True}
        self.loaded = None
        self.prepared_bootstrap_modes = []

    def load_e_step_result_from_dict(self, parameters):
        self.loaded = parameters

    def prepare_lidar_correspondences(self, bootstrap_mode="translation"):
        self.prepared_bootstrap_modes.append(bootstrap_mode)


class CoarseLiDARStageAcceptanceTests(unittest.TestCase):
    def test_worse_surface_candidate_restores_photo_state_but_leaves_m6_m7_a_fair_shot(self):
        engine = FakeLiDAREngine()
        photo_parameters = {"state": "photo-only"}
        original_tooth_pose_constraints = engine.lidar_tooth_pose_constraints
        original_tooth_shape_constraints = engine.lidar_tooth_shape_constraints
        original_tooth_shape_correspondences = engine.lidar_tooth_shape_correspondences

        accepted = apply_coarse_lidar_acceptance_gate(engine, photo_parameters)

        self.assertFalse(accepted)
        self.assertIs(engine.loaded, photo_parameters)
        # M5's own whole-jaw candidate is discarded...
        self.assertEqual(engine.lidar_constraints, {})
        self.assertFalse(engine.lidar_diagnostics["enabled"])
        self.assertTrue(engine.lidar_diagnostics["inputEligible"])
        self.assertEqual(
            engine.lidar_diagnostics["reason"],
            "coarse_surface_distance_not_improved",
        )
        # ...but M6/M7's own per-tooth state is left untouched so Stage 2's
        # unconditional correspondence rebuild and M7's own distinct-fields
        # gate still get a fair, independently-validated shot at the
        # fallback pose.
        self.assertIs(engine.lidar_tooth_pose_constraints, original_tooth_pose_constraints)
        self.assertIs(engine.lidar_tooth_shape_constraints, original_tooth_shape_constraints)
        self.assertIs(engine.lidar_tooth_shape_correspondences, original_tooth_shape_correspondences)
        self.assertEqual(engine.lidar_tooth_pose_diagnostics, {"enabled": True})
        self.assertEqual(engine.lidar_tooth_shape_diagnostics, {"enabled": True})


    def test_improving_candidate_is_retained(self):
        engine = FakeLiDAREngine()
        engine.lidar_diagnostics.update(
            {
                "coarseLiDARMedianDistanceMillimetres": 40.0,
                "coarseLiDARP95DistanceMillimetres": 90.0,
                "photoContourLossAfter": 62.0,
            }
        )

        accepted = apply_coarse_lidar_acceptance_gate(
            engine, {"state": "photo-only"}
        )

        self.assertTrue(accepted)
        self.assertIsNone(engine.loaded)
        self.assertTrue(engine.lidar_diagnostics["enabled"])
        self.assertTrue(engine.lidar_diagnostics["accepted"])
        self.assertEqual(engine.lidar_diagnostics["reason"], "coarse_lidar_improved")


def _candidate_diagnostics(*, coarse_median, coarse_p95=90.0, photo_only_median=50.0, photo_only_p95=100.0):
    return {
        "photoOnlyMedianDistanceMillimetres": photo_only_median,
        "photoOnlyP95DistanceMillimetres": photo_only_p95,
        "coarseLiDARMedianDistanceMillimetres": coarse_median,
        "coarseLiDARP95DistanceMillimetres": coarse_p95,
        "photoContourLossBefore": 100.0,
        "photoContourLossAfter": 100.0,
        "pairCounts": {"front": 25_999},
    }


class SelectBestCoarseLiDARCandidateTests(unittest.TestCase):
    def test_both_failing_falls_back_to_photo_only(self):
        engine = FakeLiDAREngine()
        photo_parameters = {"state": "photo-only"}
        candidates = [
            {
                "label": "translation",
                "parameters": {"state": "translation"},
                "diagnostics": _candidate_diagnostics(coarse_median=55.0),
            },
            {
                "label": "rigid",
                "parameters": {"state": "rigid"},
                "diagnostics": _candidate_diagnostics(coarse_median=60.0),
            },
        ]

        accepted, winning_label = select_best_coarse_lidar_candidate(
            engine, candidates, photo_parameters
        )

        self.assertFalse(accepted)
        self.assertIsNone(winning_label)
        self.assertIs(engine.loaded, photo_parameters)
        self.assertFalse(engine.lidar_diagnostics["enabled"])
        self.assertEqual(
            engine.lidar_diagnostics["reason"], "coarse_surface_distance_not_improved"
        )

    def test_one_passing_is_selected(self):
        engine = FakeLiDAREngine()
        candidates = [
            {
                "label": "translation",
                "parameters": {"state": "translation"},
                "diagnostics": _candidate_diagnostics(coarse_median=55.0),  # fails
            },
            {
                "label": "rigid",
                "parameters": {"state": "rigid"},
                "diagnostics": _candidate_diagnostics(coarse_median=40.0),  # passes
            },
        ]

        accepted, winning_label = select_best_coarse_lidar_candidate(
            engine, candidates, {"state": "photo-only"}
        )

        self.assertTrue(accepted)
        self.assertEqual(winning_label, "rigid")
        self.assertIs(engine.loaded, candidates[1]["parameters"])
        self.assertTrue(engine.lidar_diagnostics["accepted"])
        self.assertEqual(engine.lidar_diagnostics["selectedBootstrapMode"], "rigid")
        self.assertEqual(engine.prepared_bootstrap_modes, ["rigid"])

    def test_both_passing_selects_the_lower_median(self):
        engine = FakeLiDAREngine()
        candidates = [
            {
                "label": "translation",
                "parameters": {"state": "translation"},
                "diagnostics": _candidate_diagnostics(coarse_median=42.0),  # passes
            },
            {
                "label": "rigid",
                "parameters": {"state": "rigid"},
                "diagnostics": _candidate_diagnostics(coarse_median=38.0),  # passes, lower
            },
        ]

        accepted, winning_label = select_best_coarse_lidar_candidate(
            engine, candidates, {"state": "photo-only"}
        )

        self.assertTrue(accepted)
        self.assertEqual(winning_label, "rigid")
        self.assertEqual(
            engine.lidar_diagnostics["coarseLiDARMedianDistanceMillimetres"], 38.0
        )


class MutableGlobalEngine:
    """Small optimizer double whose result dictionaries alias live arrays."""

    def __init__(self):
        self.state = {"value": np.array([10.0])}
        self.rowScaleXZ = np.ones((2,))
        self.loss_maximization_step = 0.0
        self._stage_zero_trials = iter((8.0, 5.0, 7.0))

    def expectation_step_5Views(self, stage, verbose):
        del stage, verbose

    def get_e_loss(self):
        return float(self.state["value"][0])

    def get_current_e_step_result(self):
        return self.state

    def load_e_step_result_from_dict(self, parameters):
        self.state = {"value": parameters["value"].copy()}

    def maximization_step_5Views(self, stage, **kwargs):
        del kwargs
        next_loss = next(self._stage_zero_trials) if stage == 0 else 10.0
        self.state["value"][0] = next_loss
        self.loss_maximization_step = next_loss


class GlobalStageSelectionTests(unittest.TestCase):
    def test_stage_zero_best_snapshot_survives_later_in_place_mutation(self):
        result = run_global_emopt_stages(MutableGlobalEngine())

        self.assertEqual(result["loss"], 5.0)
        np.testing.assert_allclose(result["parameters"]["value"], [5.0])


class FakeM7Engine:
    def __init__(self):
        self.lidar_diagnostics = {"accepted": True}
        self.lidar_tooth_pose_constraints = {0: (object(), object())}
        self.lidar_tooth_shape_constraints = {0: (object(), object())}
        self.lidar_tooth_shape_correspondences = {(0, "front"): object()}
        self.lidar_tooth_shape_activation_allowed = False
        self.lidar_tooth_shape_diagnostics = {"enabled": True}
        self.calls = []

    def prepare_lidar_tooth_pose_correspondences(self):
        self.calls.append("prepare_pose")

    def prepare_lidar_tooth_shape_correspondences(self):
        self.calls.append("prepare_shape")

    def maximization_lidar_tooth_shape_only(self, maxiter, verbose):
        self.calls.append(("optimize_shape", maxiter, verbose))

    def expectation_step_5Views(self, stage, verbose):
        self.calls.append(("expectation", stage, verbose))


class M7ComparisonBoundaryTests(unittest.TestCase):
    def test_m6_only_mode_skips_shape_work_and_records_reason(self):
        engine = FakeM7Engine()

        activated = run_gated_m7_shape_experiment(
            engine, maxiter=20, verbose=False, enabled=False
        )

        self.assertFalse(activated)
        self.assertEqual(engine.calls, [])
        self.assertEqual(engine.lidar_tooth_shape_constraints, {})
        self.assertEqual(engine.lidar_tooth_shape_correspondences, {})
        self.assertFalse(engine.lidar_tooth_shape_activation_allowed)
        self.assertEqual(
            engine.lidar_tooth_shape_diagnostics,
            {"enabled": False, "reason": "disabled_by_comparison_mode"},
        )

    def test_default_mode_runs_existing_gated_shape_path(self):
        engine = FakeM7Engine()

        activated = run_gated_m7_shape_experiment(
            engine, maxiter=20, verbose=False, enabled=True
        )

        self.assertTrue(activated)
        self.assertEqual(
            engine.calls,
            [
                "prepare_pose",
                "prepare_shape",
                ("optimize_shape", 20, False),
                ("expectation", 3, False),
            ],
        )

    def test_runs_gated_shape_path_even_when_m5_was_rejected(self):
        # M7 no longer requires M5's own accept/reject decision -- it relies
        # on its own distinct-fields-with-pairs gate (inside
        # prepare_lidar_tooth_shape_correspondences) instead.
        engine = FakeM7Engine()
        engine.lidar_diagnostics = {"accepted": False, "fallbackApplied": True}

        activated = run_gated_m7_shape_experiment(
            engine, maxiter=20, verbose=False, enabled=True
        )

        self.assertTrue(activated)
        self.assertEqual(
            engine.calls,
            [
                "prepare_pose",
                "prepare_shape",
                ("optimize_shape", 20, False),
                ("expectation", 3, False),
            ],
        )

    def test_cli_defaults_to_m7_and_accepts_m6_control(self):
        parser = build_argument_parser()

        self.assertEqual(parser.parse_args([]).lidar_max_milestone, 7)
        self.assertEqual(
            parser.parse_args(["sample", "--engine", "lidar", "--lidar-max-milestone", "6"]).lidar_max_milestone,
            6,
        )

    def test_m6_control_is_rejected_for_baseline_engine(self):
        with self.assertRaisesRegex(ValueError, "requires --engine lidar"):
            validate_lidar_milestone_ceiling("baseline", 6)

    def test_image_source_tag_reuses_exact_source_without_changing_output_tag(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "capture-4.png"
            source.write_bytes(b"image")
            with patch("main.PHOTO_DIR", root):
                resolved = resolve_reconstruction_image_path(
                    output_tag="capture-m6",
                    photo_value=4,
                    image_source_tag="capture",
                )

        self.assertEqual(resolved, str(source))

    def test_comparison_seed_reproduces_optimizer_initialization(self):
        configure_reconstruction_random_seed(4815)
        first = np.random.random(5)
        configure_reconstruction_random_seed(4815)
        second = np.random.random(5)

        np.testing.assert_array_equal(first, second)


if __name__ == "__main__":
    unittest.main()
