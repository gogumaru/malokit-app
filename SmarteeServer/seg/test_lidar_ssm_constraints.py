import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from seg.lidar_ssm_constraints import (
    LiDARConstraintConfiguration,
    LiDARViewConstraint,
    arkit_points_from_em_camera,
    build_fixed_correspondences,
    estimate_correspondence_bootstrap_rigid_transform,
    estimate_correspondence_bootstrap_translation,
    estimate_lidar_seeded_view_depths,
    huber_point_to_surface_loss,
    kabsch_rigid_transform,
    load_lidar_view_constraints,
)


def constraint_with_depth(photo_index, depth_metres, *, count=40, configuration=None):
    points = np.column_stack(
        (np.zeros(count), np.zeros(count), np.full(count, depth_metres))
    )
    return LiDARViewConstraint(
        photo_index=photo_index,
        field="front",
        points_k0_metres=points,
        contributing_keyframes=("K0", "K2", "K5"),
        configuration=configuration or LiDARConstraintConfiguration(),
    )


def metadata(keyframe_id, *, direct=True, depth_eligible=True, tracking="normal"):
    return {
        "schemaVersion": 4,
        "figure8KeyframeID": keyframe_id,
        "isDirectView": direct,
        "ssmDepthEligible": depth_eligible,
        "trackingState": tracking,
        "matrixLayout": "column-major",
        "coordinateSystem": "ARKit camera-to-world",
        "cameraToReferenceTransform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
    }


def write_cloud(root, field, *, keyframes=("K0", "K2", "K5"), points=None, metadata_overrides=None):
    view = Path(root) / "capture" / field
    view.mkdir(parents=True)
    points = np.asarray(
        points if points is not None else np.column_stack((np.arange(500), np.zeros(500), np.ones(500))) * 0.001,
        dtype=np.float32,
    )
    counts = {keyframe_id: {"acceptedPointCount": 1} for keyframe_id in keyframes}
    counts[keyframes[0]]["acceptedPointCount"] = len(points) - len(keyframes) + 1
    (view / "dental_cloud.json").write_text(json.dumps({
        "schemaVersion": 1,
        "pointCount": len(points),
        "perKeyframe": counts,
    }))
    np.savez_compressed(view / "dental_cloud.npz", pointK0=points)
    metadata_overrides = metadata_overrides or {}
    for keyframe_id in keyframes:
        values = metadata(keyframe_id)
        values.update(metadata_overrides.get(keyframe_id, {}))
        (view / f"{keyframe_id}.metadata.json").write_text(json.dumps(values))
    return points


class LiDARSSMConstraintLoaderTests(unittest.TestCase):
    def test_accepts_direct_cloud_with_k0_and_two_later_keyframes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            points = write_cloud(root, "front")
            constraints, skipped = load_lidar_view_constraints(root, "capture", LiDARConstraintConfiguration())

        self.assertEqual(skipped, {})
        self.assertEqual(set(constraints), {4})
        self.assertEqual(constraints[4].field, "front")
        np.testing.assert_array_equal(constraints[4].points_k0_metres, points.astype(np.float64))
        self.assertEqual(constraints[4].contributing_keyframes, ("K0", "K2", "K5"))

    def test_rejects_k0_only_cloud_as_insufficient_multiview_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            write_cloud(Path(temporary), "front", keyframes=("K0",))
            constraints, skipped = load_lidar_view_constraints(Path(temporary), "capture", LiDARConstraintConfiguration())

        self.assertEqual(constraints, {})
        self.assertEqual(skipped, {"front": "insufficient_multiview_coverage"})

    def test_rejects_mirror_or_non_normal_metadata_without_loading_npz(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            view = root / "capture" / "front"
            view.mkdir(parents=True)
            (view / "dental_cloud.json").write_text(json.dumps({"schemaVersion": 1, "pointCount": 500, "perKeyframe": {"K0": {"acceptedPointCount": 500}, "K2": {"acceptedPointCount": 1}, "K5": {"acceptedPointCount": 1}}}))
            for keyframe_id in ("K0", "K2", "K5"):
                values = metadata(keyframe_id, direct=False)
                (view / f"{keyframe_id}.metadata.json").write_text(json.dumps(values))

            constraints, skipped = load_lidar_view_constraints(root, "capture", LiDARConstraintConfiguration())

        self.assertEqual(constraints, {})
        self.assertEqual(skipped, {"front": "mirror_or_ineligible_view"})

    def test_keeps_front_left_right_and_mandibular_reference_frames_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = {}
            for index, field in enumerate(("front", "leftLateral", "rightLateral", "mandibular")):
                expected[field] = write_cloud(root, field, points=np.full((500, 3), index + 1, dtype=np.float32))
            constraints, skipped = load_lidar_view_constraints(root, "capture", LiDARConstraintConfiguration())

        self.assertEqual(skipped, {})
        self.assertEqual(set(constraint.field for constraint in constraints.values()), set(expected))
        for constraint in constraints.values():
            np.testing.assert_array_equal(constraint.points_k0_metres, expected[constraint.field].astype(np.float64))


class LiDARSSMConstraintResidualTests(unittest.TestCase):
    def constraint(self, points):
        return LiDARViewConstraint(
            photo_index=4,
            field="front",
            points_k0_metres=np.asarray(points, dtype=np.float64),
            contributing_keyframes=("K0", "K2", "K5"),
            configuration=LiDARConstraintConfiguration(),
        )

    def test_em_camera_axes_map_to_arkit_x_negative_y_negative_z(self):
        actual = arkit_points_from_em_camera(np.array([[10.0, 20.0, -30.0]]), 0.001)
        np.testing.assert_allclose(actual, [[0.01, -0.02, 0.03]])

    def test_bootstrap_recovers_a_known_100mm_camera_translation(self):
        model = np.array([
            [-20.0, 0.0, 100.0],
            [0.0, 5.0, 110.0],
            [20.0, -5.0, 120.0],
        ])
        aligned = arkit_points_from_em_camera(model, 0.001)
        expected = np.array([0.01, -0.02, -0.10])

        result = estimate_correspondence_bootstrap_translation(
            model,
            aligned + expected,
            0.001,
        )

        self.assertIsNotNone(result)
        np.testing.assert_allclose(result.translation_metres, expected)
        np.testing.assert_allclose(result.model_median_metres, np.median(aligned, axis=0))
        np.testing.assert_allclose(result.lidar_median_metres, np.median(aligned + expected, axis=0))

    def test_bootstrap_median_is_stable_with_one_far_cloud_outlier(self):
        model = np.repeat([[4.0, -2.0, 100.0]], repeats=5, axis=0)
        expected = np.array([-0.015, 0.008, -0.1])
        cloud = arkit_points_from_em_camera(model, 0.001) + expected
        cloud[-1] = [8.0, -9.0, 7.0]

        result = estimate_correspondence_bootstrap_translation(model, cloud, 0.001)

        self.assertIsNotNone(result)
        np.testing.assert_allclose(result.translation_metres, expected)

    def test_correspondence_lookup_uses_translation_but_does_not_modify_input_points(self):
        model = np.array([
            [-2.0, 0.0, 100.0],
            [0.0, 0.0, 100.0],
            [2.0, 0.0, 100.0],
        ])
        translation = np.array([0.0, 0.0, -0.1])
        cloud = arkit_points_from_em_camera(model, 0.001) + translation
        constraint = self.constraint(cloud)
        model_before = model.copy()
        cloud_before = cloud.copy()

        raw = build_fixed_correspondences(model, constraint, 0.001)
        translated = build_fixed_correspondences(
            model,
            constraint,
            0.001,
            query_translation_metres=translation,
        )

        self.assertEqual(len(raw.model_indices), 0)
        np.testing.assert_array_equal(translated.model_indices, [0, 1, 2])
        np.testing.assert_array_equal(model, model_before)
        np.testing.assert_array_equal(cloud, cloud_before)

    def test_bootstrap_rejects_empty_nonfinite_or_over_250mm_translation(self):
        valid_model = np.array([[0.0, 0.0, 100.0]])
        valid_cloud = arkit_points_from_em_camera(valid_model, 0.001)

        invalid_cases = (
            (np.empty((0, 3)), valid_cloud),
            (np.array([[np.nan, 0.0, 100.0]]), valid_cloud),
            (valid_model, np.array([[np.inf, 0.0, -0.1]])),
            (valid_model, valid_cloud + np.array([0.0, 0.0, -0.251])),
        )
        for model, cloud in invalid_cases:
            with self.subTest(model=model, cloud=cloud):
                self.assertIsNone(
                    estimate_correspondence_bootstrap_translation(model, cloud, 0.001)
                )

    def test_correct_metric_scale_has_lower_loss_than_half_scale(self):
        model = np.array([[0.0, 0.0, 10.0], [2.0, 0.0, 10.0], [0.0, 2.0, 10.0], [2.0, 2.0, 10.0]])
        constraint = self.constraint(arkit_points_from_em_camera(model, 0.001))
        correct = build_fixed_correspondences(model, constraint, 0.001)
        half = build_fixed_correspondences(model, constraint, 0.0005)
        correct_loss, _ = huber_point_to_surface_loss(
            arkit_points_from_em_camera(model[correct.model_indices], 0.001),
            constraint.points_k0_metres[correct.lidar_indices], 0.004,
        )
        half_loss, _ = huber_point_to_surface_loss(
            arkit_points_from_em_camera(model[half.model_indices], 0.0005),
            constraint.points_k0_metres[half.lidar_indices], 0.004,
        )
        self.assertLess(correct_loss, half_loss)

    def test_correspondence_gate_excludes_a_far_cloud_outlier(self):
        model = np.array([[0.0, 0.0, 100.0], [2.0, 0.0, 100.0], [100.0, 0.0, 100.0]])
        constraint = self.constraint([[0.0, 0.0, -0.1], [0.002, 0.0, -0.1]])
        pairs = build_fixed_correspondences(model, constraint, 0.001)
        np.testing.assert_array_equal(pairs.model_indices, [0, 1])
        np.testing.assert_array_equal(pairs.lidar_indices, [0, 1])

    def test_huber_gradient_matches_central_difference_for_one_point(self):
        model = np.array([[0.003, 0.0, 0.0]])
        lidar = np.array([[0.0, 0.0, 0.0]])
        loss, gradient = huber_point_to_surface_loss(model, lidar, 0.004)
        epsilon = 1e-6
        shifted = model.copy()
        shifted[0, 0] += epsilon
        shifted_loss, _ = huber_point_to_surface_loss(shifted, lidar, 0.004)
        self.assertGreater(loss, 0.0)
        self.assertAlmostEqual(gradient[0, 0], (shifted_loss - loss) / epsilon, delta=1e-5)


class LiDARRigidBootstrapTests(unittest.TestCase):
    @staticmethod
    def _rotation_about_z(degrees):
        angle = np.radians(degrees)
        cos_a, sin_a = np.cos(angle), np.sin(angle)
        return np.array([
            [cos_a, -sin_a, 0.0],
            [sin_a, cos_a, 0.0],
            [0.0, 0.0, 1.0],
        ])

    def test_kabsch_recovers_a_known_rotation_and_translation(self):
        rng = np.random.default_rng(3)
        model = rng.uniform(-0.05, 0.05, size=(30, 3))
        rotation_true = self._rotation_about_z(30.0)
        translation_true = np.array([0.02, -0.03, 0.01])
        target = model @ rotation_true.T + translation_true

        rotation, translation = kabsch_rigid_transform(model, target)

        np.testing.assert_allclose(rotation, rotation_true, atol=1e-8)
        np.testing.assert_allclose(translation, translation_true, atol=1e-8)

    def test_kabsch_handles_reflection_case(self):
        # A planar triangle related to its mirror image: no proper rotation
        # reproduces this exactly, so the naive (uncorrected) SVD solution
        # would be a reflection (det < 0). The correction term must still
        # return a proper rotation.
        model = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        target = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, -1.0, 0.0]])

        rotation, _ = kabsch_rigid_transform(model, target)

        self.assertGreater(np.linalg.det(rotation), 0.0)
        np.testing.assert_allclose(rotation @ rotation.T, np.eye(3), atol=1e-8)

    def test_rigid_bootstrap_iterates_toward_better_alignment_than_translation_only(self):
        rng = np.random.default_rng(7)
        model_em = rng.uniform(-40.0, 40.0, size=(150, 3))
        model_em[:, 2] += 100.0
        aligned = arkit_points_from_em_camera(model_em, 0.001)
        rotation_true = self._rotation_about_z(20.0)
        translation_true = np.array([0.03, -0.02, -0.09])
        lidar = aligned @ rotation_true.T + translation_true
        configuration = LiDARConstraintConfiguration()

        translation_only = estimate_correspondence_bootstrap_translation(
            model_em, lidar, 0.001, configuration.maximum_bootstrap_translation_metres
        )
        self.assertIsNotNone(translation_only)
        translation_only_residual = np.linalg.norm(
            (aligned + translation_only.translation_metres) - lidar, axis=1
        ).mean()

        rigid = estimate_correspondence_bootstrap_rigid_transform(
            model_em, lidar, 0.001, configuration, bootstrap_gate_metres=0.05
        )

        self.assertIsNotNone(rigid)
        rigid_residual = np.linalg.norm(
            (aligned @ rigid.rotation.T + rigid.translation_metres) - lidar, axis=1
        ).mean()
        self.assertLess(rigid_residual, translation_only_residual * 0.3)

    def test_rigid_bootstrap_rejects_translation_exceeding_maximum(self):
        rng = np.random.default_rng(13)
        model_em = rng.uniform(-40.0, 40.0, size=(150, 3))
        model_em[:, 2] += 100.0
        aligned = arkit_points_from_em_camera(model_em, 0.001)
        lidar = aligned + np.array([0.0, 0.0, -0.26])

        result = estimate_correspondence_bootstrap_rigid_transform(
            model_em, lidar, 0.001, LiDARConstraintConfiguration()
        )

        self.assertIsNone(result)

    def test_rigid_bootstrap_rejects_rotation_exceeding_maximum(self):
        rng = np.random.default_rng(11)
        model_em = rng.uniform(-40.0, 40.0, size=(150, 3))
        model_em[:, 2] += 100.0
        aligned = arkit_points_from_em_camera(model_em, 0.001)
        rotation_true = self._rotation_about_z(10.0)
        translation_true = np.array([0.01, -0.01, -0.05])
        lidar = aligned @ rotation_true.T + translation_true
        strict_configuration = dataclasses.replace(
            LiDARConstraintConfiguration(), maximum_bootstrap_rotation_radians=0.01
        )

        result = estimate_correspondence_bootstrap_rigid_transform(
            model_em, lidar, 0.001, strict_configuration, bootstrap_gate_metres=0.05
        )

        self.assertIsNone(result)

    def test_build_fixed_correspondences_applies_rotation_before_translation(self):
        model = np.array([[10.0, 0.0, 100.0]])
        aligned = arkit_points_from_em_camera(model, 0.001)[0]
        rotation_90_about_z = np.array([
            [0.0, -1.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0],
        ])
        rotated = rotation_90_about_z @ aligned
        constraint = LiDARViewConstraint(
            photo_index=4,
            field="front",
            points_k0_metres=np.array([rotated]),
            contributing_keyframes=("K0", "K2", "K5"),
            configuration=LiDARConstraintConfiguration(),
        )

        without_rotation = build_fixed_correspondences(model, constraint, 0.001)
        with_rotation = build_fixed_correspondences(
            model, constraint, 0.001, query_rotation=rotation_90_about_z
        )

        self.assertEqual(len(without_rotation.model_indices), 0)
        np.testing.assert_array_equal(with_rotation.model_indices, [0])


class EstimateLiDARSeededViewDepthsTests(unittest.TestCase):
    def test_computes_depth_matching_arkit_points_from_em_camera_convention(self):
        # A view captured 70mm in front of the camera round-trips through
        # arkit_points_from_em_camera to arkit z = -0.070m at scale=0.001.
        em_point = np.array([[0.0, 0.0, 70.0]])
        arkit_z = arkit_points_from_em_camera(em_point, 0.001)[0, 2]
        constraint = constraint_with_depth(4, arkit_z)

        seeded = estimate_lidar_seeded_view_depths({4: constraint})

        self.assertAlmostEqual(seeded[4], 70.0, places=6)

    def test_omits_a_view_with_too_few_points(self):
        constraint = constraint_with_depth(4, -0.070, count=5)
        seeded = estimate_lidar_seeded_view_depths({4: constraint})
        self.assertEqual(seeded, {})

    def test_omits_a_view_outside_the_plausible_depth_range(self):
        constraint = constraint_with_depth(4, -0.500)  # 500mm, implausible
        seeded = estimate_lidar_seeded_view_depths({4: constraint})
        self.assertEqual(seeded, {})

    def test_empty_constraints_yields_empty_result(self):
        self.assertEqual(estimate_lidar_seeded_view_depths({}), {})

    def test_seeds_only_the_view_with_confident_evidence(self):
        confident = constraint_with_depth(4, -0.080)
        sparse = constraint_with_depth(2, -0.080, count=5)
        seeded = estimate_lidar_seeded_view_depths({4: confident, 2: sparse})
        self.assertEqual(set(seeded), {4})


if __name__ == "__main__":
    unittest.main()
