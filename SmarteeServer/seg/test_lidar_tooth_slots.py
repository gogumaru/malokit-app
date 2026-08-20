import unittest

import numpy as np

from const import VISIBLE_MASKS
from seg.lidar_tooth_slots import assign_keyframe_slots, propagate_k0_slots


def instance(local_id, x, y, confidence=0.9):
    return {
        "localId": local_id,
        "normalizedCentroidXY": [x, y],
        "confidence": confidence,
    }


def surface_records(keyframe_id, instance_id, origin, count=30, detector=0.9, depth=2):
    origin = np.asarray(origin, dtype=np.float64)
    offsets = np.asarray(
        [[x * 0.0002, y * 0.0002, 0.0] for y in range(5) for x in range(6)],
        dtype=np.float64,
    )[:count]
    return [
        {
            "keyframeID": keyframe_id,
            "instanceID": instance_id,
            "slotID": None,
            "detectorConfidence": detector,
            "depthConfidence": depth,
            "pointK0": (origin + offset).tolist(),
            "rejectionReason": None,
        }
        for offset in offsets
    ]


class LiDARToothSlotTests(unittest.TestCase):
    def test_k0_anchor_propagates_to_two_unique_overlapping_later_instances(self):
        records = (
            surface_records("K0", "anchor", (0.0, 0.0, 0.0))
            + surface_records("K1", "later-one", (0.001, 0.0, 0.0))
            + surface_records("K5", "later-five", (0.0, 0.001, 0.0))
            + surface_records("K1", "far", (0.030, 0.0, 0.0))
        )

        assignments, diagnostics = propagate_k0_slots(records, {"anchor": "U-04"})

        self.assertEqual(assignments["K0"], {"anchor": "U-04"})
        self.assertEqual(assignments["K1"], {"later-one": "U-04"})
        self.assertEqual(assignments["K5"], {"later-five": "U-04"})
        self.assertEqual(diagnostics["K1"]["later-one"]["reason"], "matched_k0_anchor")
        self.assertEqual(diagnostics["K1"]["far"]["reason"], "insufficient_surface_overlap")

    def test_k0_anchor_rejects_two_nearly_equal_later_candidates(self):
        records = (
            surface_records("K0", "anchor", (0.0, 0.0, 0.0))
            + surface_records("K2", "candidate-a", (0.0010, 0.0, 0.0))
            + surface_records("K2", "candidate-b", (0.0011, 0.0, 0.0))
        )

        assignments, diagnostics = propagate_k0_slots(records, {"anchor": "U-04"})

        self.assertEqual(assignments["K2"], {})
        self.assertEqual(
            {value["reason"] for value in diagnostics["K2"].values()},
            {"ambiguous_k0_surface_match"},
        )

    def test_later_instance_rejects_two_nearly_equal_k0_anchors(self):
        records = (
            surface_records("K0", "anchor-a", (0.0, 0.0, 0.0))
            + surface_records("K0", "anchor-b", (0.0, 0.0, 0.0011))
            + surface_records("K3", "later", (0.0, 0.0, 0.0005))
        )

        assignments, diagnostics = propagate_k0_slots(
            records, {"anchor-a": "U-04", "anchor-b": "U-05"}
        )

        self.assertEqual(assignments["K3"], {})
        self.assertEqual(
            diagnostics["K3"]["later"]["reason"], "ambiguous_k0_surface_match"
        )

    def test_match_rejects_too_few_points_low_confidence_and_distance_over_gate(self):
        records = (
            surface_records("K0", "anchor", (0.0, 0.0, 0.0))
            + surface_records("K1", "too-few", (0.001, 0.0, 0.0), count=14)
            + surface_records("K2", "low-detector", (0.001, 0.0, 0.0), detector=0.79)
            + surface_records("K3", "low-depth", (0.001, 0.0, 0.0), depth=1)
            + surface_records("K4", "too-far", (0.006, 0.0, 0.0))
        )

        assignments, diagnostics = propagate_k0_slots(records, {"anchor": "U-04"})

        self.assertFalse(any(assignments[key] for key in ("K1", "K2", "K3", "K4")))
        self.assertEqual(diagnostics["K1"]["too-few"]["reason"], "insufficient_high_confidence_points")
        self.assertEqual(diagnostics["K2"]["low-detector"]["reason"], "insufficient_high_confidence_points")
        self.assertEqual(diagnostics["K3"]["low-depth"]["reason"], "insufficient_high_confidence_points")
        self.assertEqual(diagnostics["K4"]["too-far"]["reason"], "insufficient_surface_overlap")

    def test_propagation_never_returns_a_slot_absent_from_k0(self):
        records = surface_records("K0", "unassigned", (0.0, 0.0, 0.0)) + surface_records(
            "K1", "later", (0.001, 0.0, 0.0)
        )

        assignments, diagnostics = propagate_k0_slots(records, {})

        self.assertEqual(assignments, {"K0": {}, "K1": {}})
        self.assertEqual(diagnostics["K1"]["later"]["reason"], "missing_k0_slot_anchor")

    def test_complete_lower_row_assigns_each_high_confidence_instance_to_one_l_slot(self):
        instances = [
            instance(f"i-{index}", (index - 0.5) / 14.0, 0.5)
            for index in range(1, 15)
        ]

        assignments, rejected = assign_keyframe_slots(
            instances=instances, photo_index=1, active_original_indices=np.arange(28)
        )

        self.assertEqual(rejected, {})
        self.assertEqual(
            assignments,
            {
                **{f"i-{index}": f"L-{index:02d}" for index in range(1, 8)},
                **{f"i-{index}": f"L-{22 - index:02d}" for index in range(8, 15)},
            },
        )

    def test_lateral_row_uses_only_its_visible_mask_candidate_slots(self):
        upper_count = int(np.count_nonzero(VISIBLE_MASKS[2][:14]))
        lower_count = int(np.count_nonzero(VISIBLE_MASKS[2][14:]))
        instances = [
            instance("upper-left", 0.5 / upper_count, 0.25),
            instance("upper-next", 1.5 / upper_count, 0.25),
            instance("lower-left", 0.5 / lower_count, 0.75),
            instance("lower-next", 1.5 / lower_count, 0.75),
        ]

        assignments, _ = assign_keyframe_slots(
            instances=instances, photo_index=2, active_original_indices=np.arange(28)
        )

        self.assertEqual(assignments["upper-left"], "U-01")
        self.assertEqual(assignments["lower-left"], "L-01")

    def test_front_upper_candidates_follow_screen_order_across_the_midline(self):
        upper_count = int(np.count_nonzero(VISIBLE_MASKS[4][:14]))
        instances = [
            instance(f"upper-{index}", (index + 0.5) / upper_count, 0.35)
            for index in range(upper_count)
        ] + [
            instance("lower-left", 0.25, 0.75),
            instance("lower-right", 0.75, 0.75),
        ]

        assignments, _ = assign_keyframe_slots(
            instances=instances, photo_index=4, active_original_indices=np.arange(28)
        )

        self.assertEqual(
            [assignments[f"upper-{index}"] for index in range(upper_count)],
            ["U-06", "U-05", "U-04", "U-03", "U-02", "U-01",
             "U-08", "U-09", "U-10", "U-11", "U-12", "U-13"],
        )

    def test_right_lateral_upper_candidates_follow_projected_screen_order(self):
        upper_count = int(np.count_nonzero(VISIBLE_MASKS[3][:14]))
        lower_count = int(np.count_nonzero(VISIBLE_MASKS[3][14:]))
        instances = [
            instance(f"upper-{index}", (index + 0.5) / upper_count, 0.30)
            for index in range(upper_count)
        ] + [
            instance(f"lower-{index}", (index + 0.5) / lower_count, 0.70)
            for index in range(lower_count)
        ]

        assignments, _ = assign_keyframe_slots(
            instances=instances, photo_index=3, active_original_indices=np.arange(28)
        )

        self.assertEqual(
            [assignments[f"upper-{index}"] for index in range(upper_count)],
            ["U-06", "U-05", "U-04", "U-03", "U-02", "U-01", "U-08"],
        )

    def test_dominant_sub_12_percent_gap_is_accepted_as_two_arch_rows(self):
        upper_count = int(np.count_nonzero(VISIBLE_MASKS[2][:14]))
        lower_count = int(np.count_nonzero(VISIBLE_MASKS[2][14:]))
        instances = [
            instance("u1", 0.5 / upper_count, 0.40),
            instance("u2", 1.5 / upper_count, 0.42),
            instance("l1", 0.5 / lower_count, 0.51),
            instance("l2", 1.5 / lower_count, 0.53),
        ]

        assignments, rejected = assign_keyframe_slots(
            instances=instances, photo_index=2, active_original_indices=np.arange(28)
        )

        self.assertEqual(rejected, {})
        self.assertEqual(assignments["u1"], "U-01")
        self.assertEqual(assignments["l1"], "L-01")

    def test_sub_12_percent_gap_is_rejected_when_two_gaps_are_comparable(self):
        instances = [
            instance("one", 0.1, 0.36),
            instance("two", 0.3, 0.45),
            instance("three", 0.7, 0.54),
            instance("four", 0.9, 0.56),
        ]

        assignments, rejected = assign_keyframe_slots(
            instances=instances, photo_index=4, active_original_indices=np.arange(28)
        )

        self.assertEqual(assignments, {})
        self.assertEqual(set(rejected.values()), {"ambiguous_arch_rows"})

    def test_gap_below_five_percent_is_rejected_even_when_dominant(self):
        instances = [
            instance("one", 0.1, 0.40),
            instance("two", 0.3, 0.42),
            instance("three", 0.7, 0.46),
            instance("four", 0.9, 0.48),
        ]

        assignments, rejected = assign_keyframe_slots(
            instances=instances, photo_index=4, active_original_indices=np.arange(28)
        )

        self.assertEqual(assignments, {})
        self.assertEqual(set(rejected.values()), {"ambiguous_arch_rows"})

    def test_exact_five_percent_gap_is_accepted_despite_float_rounding(self):
        upper_count = int(np.count_nonzero(VISIBLE_MASKS[2][:14]))
        lower_count = int(np.count_nonzero(VISIBLE_MASKS[2][14:]))
        instances = [
            instance("u1", 0.5 / upper_count, 0.38),
            instance("u2", 1.5 / upper_count, 0.40),
            instance("l1", 0.5 / lower_count, 0.45),
            instance("l2", 1.5 / lower_count, 0.47),
        ]

        assignments, rejected = assign_keyframe_slots(
            instances=instances, photo_index=2, active_original_indices=np.arange(28)
        )

        self.assertEqual(rejected, {})
        self.assertEqual(assignments["u1"], "U-01")
        self.assertEqual(assignments["l1"], "L-01")

    def test_exact_1_15x_dominance_is_accepted_despite_float_rounding(self):
        upper_count = int(np.count_nonzero(VISIBLE_MASKS[2][:14]))
        lower_count = int(np.count_nonzero(VISIBLE_MASKS[2][14:]))
        instances = [
            instance("u1", 0.5 / upper_count, 0.30),
            instance("u2", 1.5 / upper_count, 0.335),
            instance("l1", 0.5 / lower_count, 0.415),
            instance("l2", 1.5 / lower_count, 0.45),
        ]

        assignments, rejected = assign_keyframe_slots(
            instances=instances, photo_index=2, active_original_indices=np.arange(28)
        )

        self.assertEqual(rejected, {})
        self.assertEqual(assignments["u1"], "U-01")
        self.assertEqual(assignments["l1"], "L-01")

    def test_real_capture_near_tie_split_now_succeeds(self):
        # Reproduces the exact real near-miss that motivated loosening these
        # thresholds: 15 high-confidence detections with one stray instance
        # near the arch midline, producing two comparable gaps (0.0615 and
        # 0.0523, only 1.17x apart) instead of one dominant one.
        upper_ys = [0.4242, 0.4315, 0.4337, 0.4367, 0.4491, 0.4498, 0.4538]
        stray_y = 0.5061
        lower_ys = [0.5676, 0.5702, 0.5748, 0.5777, 0.5781, 0.5811, 0.5849]
        all_points = [(y, f"u{i}") for i, y in enumerate(upper_ys)]
        all_points.append((stray_y, "stray"))
        all_points += [(y, f"l{i}") for i, y in enumerate(lower_ys)]
        instances = [
            instance(name, (index + 0.5) / len(all_points), y)
            for index, (y, name) in enumerate(all_points)
        ]

        _assignments, rejected = assign_keyframe_slots(
            instances=instances, photo_index=3, active_original_indices=np.arange(28)
        )

        # The row split itself must succeed (not the old blanket
        # "ambiguous_arch_rows" rejection this exact gap/dominance used to
        # trigger) — downstream per-instance DP alignment confidence is a
        # separate concern, already covered by other tests using realistic
        # mask-based x-positions.
        self.assertNotIn("ambiguous_arch_rows", rejected.values())

    def test_single_stray_instance_is_excluded_not_the_whole_field(self):
        # Reproduces a real device capture (fe5cae58abf4, front@K0): 6 clean
        # upper teeth, one lone stray sitting between the arches, 6 clean
        # lower teeth. The stray splits one real gap into two comparable
        # ones (1.10x, under even the loosened 1.15x dominance bar) -- but
        # only the stray itself is actually ambiguous.
        upper_ys = [0.4225, 0.4276, 0.4333, 0.4365, 0.4495, 0.4558]
        stray_y = 0.5187
        lower_ys = [0.5759, 0.5790, 0.5803, 0.5826, 0.5887, 0.5917]
        all_points = [(y, f"u{i}") for i, y in enumerate(upper_ys)]
        all_points.append((stray_y, "stray"))
        all_points += [(y, f"l{i}") for i, y in enumerate(lower_ys)]
        instances = [
            instance(name, (index + 0.5) / len(all_points), y)
            for index, (y, name) in enumerate(all_points)
        ]

        _assignments, rejected = assign_keyframe_slots(
            instances=instances, photo_index=4, active_original_indices=np.arange(28)
        )

        # The row split itself must recover (only "stray" is genuinely
        # ambiguous); downstream per-instance DP x-alignment confidence is a
        # separate concern already covered elsewhere with realistic
        # mask-based x-positions (same caveat as
        # test_real_capture_near_tie_split_now_succeeds above).
        self.assertEqual(rejected.get("stray"), "ambiguous_row_membership")
        for name in [f"u{i}" for i in range(6)] + [f"l{i}" for i in range(6)]:
            self.assertNotEqual(rejected.get(name), "ambiguous_arch_rows")

    def test_two_stray_instances_still_reject_the_whole_field(self):
        # Ambiguity spanning more than one instance (the two largest gaps
        # aren't adjacent) is wider than the single-stray recovery is meant
        # for -- must still fall back to full rejection, not guess.
        ys = [0.30, 0.40, 0.41, 0.50, 0.51, 0.60]
        instances = [
            instance(f"i{index}", (index + 0.5) / len(ys), y)
            for index, y in enumerate(ys)
        ]

        assignments, rejected = assign_keyframe_slots(
            instances=instances, photo_index=4, active_original_indices=np.arange(28)
        )

        self.assertEqual(assignments, {})
        for index in range(len(ys)):
            self.assertEqual(rejected.get(f"i{index}"), "ambiguous_arch_rows")

    def test_ambiguous_arch_rows_return_no_assignment_and_an_explicit_reason(self):
        instances = [instance("one", 0.1, 0.45), instance("two", 0.9, 0.50)]

        assignments, rejected = assign_keyframe_slots(
            instances=instances, photo_index=4, active_original_indices=np.arange(28)
        )

        self.assertEqual(assignments, {})
        self.assertEqual(rejected, {"one": "ambiguous_arch_rows", "two": "ambiguous_arch_rows"})

    def test_low_detector_confidence_is_excluded_not_force_assigned(self):
        assignments, rejected = assign_keyframe_slots(
            instances=[instance("low", 0.5, 0.5, confidence=0.79)],
            photo_index=1,
            active_original_indices=np.arange(28),
        )

        self.assertEqual(assignments, {})
        self.assertEqual(rejected, {"low": "low_detector_confidence"})

    def test_missing_tooth_gap_does_not_shift_later_confirmed_slots(self):
        instances = [
            instance("one", (1 - 0.5) / 14.0, 0.5),
            instance("two", (2 - 0.5) / 14.0, 0.5),
            instance("four", (4 - 0.5) / 14.0, 0.5),
        ]

        assignments, _ = assign_keyframe_slots(
            instances=instances, photo_index=1, active_original_indices=np.arange(28)
        )

        self.assertEqual(assignments["one"], "L-01")
        self.assertEqual(assignments["two"], "L-02")
        self.assertEqual(assignments["four"], "L-04")

    def test_inactive_original_ssm_index_is_never_returned_as_a_slot(self):
        assignments, rejected = assign_keyframe_slots(
            instances=[instance("only", 0.5, 0.5)],
            photo_index=1,
            active_original_indices=np.arange(14),
        )

        self.assertEqual(assignments, {})
        self.assertEqual(rejected, {"only": "inactive_ssm_slot"})


if __name__ == "__main__":
    unittest.main()
