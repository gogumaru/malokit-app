import unittest
from pathlib import Path
from types import MethodType

import numpy as np

from const import PHOTO
from emopt5views_lidar import EMOpt5Views
from seg.lidar_ssm_constraints import (
    FixedLiDARCorrespondences,
    LiDARConstraintConfiguration,
    LiDARViewConstraint,
    arkit_points_from_em_camera,
    huber_point_to_surface_loss,
)
from seg.lidar_tooth_pose_constraints import (
    LiDARToothPoseConfiguration,
    LiDARToothPoseConstraint,
)


class LiDAREngineConstraintTests(unittest.TestCase):
    def test_baseline_engine_has_no_m7_shape_constraint_hooks(self):
        baseline_source = Path("emopt5views.py").read_text(encoding="utf-8")

        self.assertNotIn("lidar_tooth_shape", baseline_source)
        self.assertNotIn("LIDAR_TOOTH_SHAPE_CONSTRAINTS_JSON", baseline_source)

    def test_stage_zero_resets_stale_geometry_and_stage_one_is_idempotent(self):
        engine = EMOpt5Views.__new__(EMOpt5Views)
        engine.X_Mu = np.array([[[1.0, 2.0, 3.0]], [[4.0, 5.0, 6.0]]])
        engine.X_Mu_normals = np.array([[[0.0, 1.0, 0.0]], [[0.0, 1.0, 0.0]]])
        engine.X_trans = np.full_like(engine.X_Mu, 99.0)
        engine.X_trans_normals = np.full_like(engine.X_Mu_normals, 99.0)
        engine.X_deformed = engine.X_Mu.copy()
        engine.X_deformed_normals = engine.X_Mu_normals.copy()
        engine.RotMats = np.tile(np.eye(3), (2, 1, 1))
        engine.rowScaleXZ = np.array([2.0, 0.5])

        engine.updateAlignedPointCloudInWorldCoord(0, [0, 1])
        np.testing.assert_array_equal(engine.X_trans, engine.X_Mu)

        engine.updateAlignedPointCloudInWorldCoord(1, [0, 1])
        first = engine.X_trans.copy()
        engine.updateAlignedPointCloudInWorldCoord(1, [0, 1])

        np.testing.assert_array_equal(engine.X_trans, first)
        np.testing.assert_allclose(
            first,
            engine.X_Mu * np.array([2.0, 1.0, 0.5]),
        )

    def make_engine(self, *, point_count=120, cloud_offset=None, prepare=True):
        engine = object.__new__(EMOpt5Views)
        indices = np.arange(point_count, dtype=np.float64)
        model = np.column_stack((
            (indices % 12) * 1.5,
            (indices // 12) * 1.5,
            100.0 + (indices % 5) * 0.2,
        ))[None, :, :]
        engine.X_deformed = model.copy()
        engine.X_Mu_centroids = model.mean(axis=1)
        engine.Mask = np.array([True])
        engine.numUpperTooth = 1
        engine.visIdx = [np.array([0], dtype=np.intp) for _ in range(5)]
        engine.ul_sp = {PHOTO.LEFT.value: 1, PHOTO.RIGHT.value: 1, PHOTO.FRONTAL.value: 1}
        engine.rela_rxyz = np.zeros(3)
        engine.rela_txyz = np.zeros(3)
        engine.ex_rxyz = np.zeros((5, 3))
        engine.ex_txyz = np.zeros((5, 3))
        engine.rowScaleXZ = np.ones(2)
        engine.scales = np.ones(1)
        engine.rotVecXYZs = np.zeros((1, 3))
        engine.transVecXYZs = np.zeros((1, 3))
        target = arkit_points_from_em_camera(model.reshape(-1, 3), 0.001)
        if cloud_offset is not None:
            target = target + np.asarray(cloud_offset, dtype=np.float64)
        constraint = LiDARViewConstraint(
            photo_index=PHOTO.FRONTAL.value,
            field="front",
            points_k0_metres=target,
            contributing_keyframes=("K0", "K2", "K5"),
            configuration=LiDARConstraintConfiguration(),
        )
        engine.set_lidar_constraints({PHOTO.FRONTAL.value: constraint})
        if prepare:
            engine.prepare_lidar_correspondences()
        return engine

    def make_shape_engine(self, *, field_count=2, tooth_count=1):
        engine = self.make_engine()
        base = engine.X_deformed[0]
        models = [base + np.array([40.0 * index, 0.0, 0.0]) for index in range(tooth_count)]
        engine.X_Mu = np.asarray(models)
        engine.X_deformed = engine.X_Mu.copy()
        engine.X_Mu_centroids = engine.X_Mu.mean(axis=1)
        engine.Mask = np.ones(tooth_count, dtype=bool)
        engine.numTooth = tooth_count
        engine.numUpperTooth = tooth_count
        engine.numPoint = len(base)
        engine.numPC = 1
        engine.featureVec = np.zeros((tooth_count, 1, 1), dtype=np.float64)
        engine.SqrtEigVals = np.ones((tooth_count, 1, 1), dtype=np.float64)
        engine.SigmaT = np.zeros((tooth_count, 1, base.size), dtype=np.float64)
        deformation = np.zeros_like(base)
        deformation[:, 2] = np.linspace(-0.5, 0.5, len(base))
        engine.SigmaT[0, 0] = deformation.reshape(-1)
        engine.scales = np.ones(tooth_count)
        engine.rotVecXYZs = np.zeros((tooth_count, 3))
        engine.transVecXYZs = np.zeros((tooth_count, 3))

        target_feature = np.zeros_like(engine.featureVec)
        target_feature[0, 0, 0] = 1.0
        target_model = engine.updateDeformedPointPos(target_feature[[0]], np.array([0]))[0]
        configuration = LiDARToothPoseConfiguration(minimum_distinct_fields=2)
        fields = ((PHOTO.FRONTAL.value, "front"), (PHOTO.LEFT.value, "leftLateral"))
        constraints = []
        for photo_index, field in fields[:field_count]:
            constraint = LiDARToothPoseConstraint(
                original_tooth_index=0,
                slot_id="U-01",
                photo_index=photo_index,
                field=field,
                points_k0_metres=arkit_points_from_em_camera(target_model, 0.001),
                contributing_keyframes=("K0", "K2", "K5"),
                configuration=configuration,
                calibrated_rgb_depth=True,
            )
            constraints.append(constraint)
        engine.set_lidar_tooth_pose_constraints({0: tuple(constraints)})
        point_indices = np.arange(len(base), dtype=np.intp)
        engine.lidar_tooth_pose_correspondences = {
            (0, constraint.field): FixedLiDARCorrespondences(point_indices, point_indices)
            for constraint in constraints
        }
        engine.lidar_tooth_shape_activation_allowed = True
        engine.prepare_lidar_tooth_shape_correspondences()
        return engine

    def test_100mm_initial_offset_builds_bootstrap_pairs_and_nonzero_translation_gradient(self):
        offset = np.array([0.01, -0.02, -0.10])
        engine = self.make_engine(cloud_offset=offset, prepare=False)
        engine.prepare_lidar_correspondences()

        pairs = engine.lidar_correspondences[PHOTO.FRONTAL.value]
        alignment = engine.lidar_diagnostics["correspondenceAlignment"]["front"]
        self.assertEqual(len(pairs.model_indices), 120)
        self.assertEqual(alignment["mode"], "translation_bootstrap")
        self.assertEqual(alignment["rawPairCount"], 0)
        self.assertEqual(alignment["pairCount"], 120)
        np.testing.assert_allclose(alignment["translationMetres"], offset)
        self.assertFalse(engine.lidar_diagnostics["noInGateCorrespondences"])

        p_idx = {"ex_rxyz": 0, "ex_txyz": 15, "lidarMetricScale": 30}
        loss, gradient = engine.compute_lidar_coarse_loss_and_gradient(
            engine.ex_rxyz,
            engine.ex_txyz,
            engine.rowScaleXZ,
            0.001,
            p_idx,
            31,
            stage=0,
        )
        translation_start = p_idx["ex_txyz"] + 3 * PHOTO.FRONTAL.value
        desired_camera_translation = offset / np.array([0.001, -0.001, -0.001])
        self.assertGreater(loss, 0.0)
        self.assertLess(
            np.dot(gradient[translation_start : translation_start + 3], desired_camera_translation),
            0.0,
        )

    def test_bootstrap_does_not_mutate_ex_txyz_before_slsqp(self):
        engine = self.make_engine(cloud_offset=[0.01, -0.02, -0.10], prepare=False)
        before = engine.ex_txyz.copy()

        engine.prepare_lidar_correspondences()

        np.testing.assert_array_equal(engine.ex_txyz, before)

    def test_each_direct_field_gets_an_independent_bootstrap_translation(self):
        front_offset = np.array([0.01, -0.02, -0.10])
        left_offset = np.array([-0.04, 0.01, -0.08])
        engine = self.make_engine(cloud_offset=front_offset, prepare=False)
        left_camera, _ = engine._lidar_model_camera_points(
            PHOTO.LEFT.value,
            engine.ex_rxyz,
            engine.ex_txyz,
            engine.rowScaleXZ,
        )
        left_constraint = LiDARViewConstraint(
            photo_index=PHOTO.LEFT.value,
            field="leftLateral",
            points_k0_metres=arkit_points_from_em_camera(left_camera, 0.001) + left_offset,
            contributing_keyframes=("K0", "K2", "K5"),
            configuration=LiDARConstraintConfiguration(),
        )
        engine.set_lidar_constraints({
            PHOTO.FRONTAL.value: engine.lidar_constraints[PHOTO.FRONTAL.value],
            PHOTO.LEFT.value: left_constraint,
        })

        engine.prepare_lidar_correspondences()

        alignment = engine.lidar_diagnostics["correspondenceAlignment"]
        np.testing.assert_allclose(alignment["front"]["translationMetres"], front_offset)
        np.testing.assert_allclose(alignment["leftLateral"]["translationMetres"], left_offset)
        self.assertEqual(engine.lidar_diagnostics["pairCounts"]["front"], 120)
        self.assertEqual(engine.lidar_diagnostics["pairCounts"]["leftLateral"], 120)

    def test_final_coarse_diagnostics_record_before_and_after_surface_distances(self):
        offset = np.array([0.01, -0.02, -0.10])
        engine = self.make_engine(cloud_offset=offset, prepare=False)
        engine.prepare_lidar_correspondences()
        before = engine.lidar_diagnostics["photoOnlyMedianDistanceMillimetres"]
        engine.ex_txyz[PHOTO.FRONTAL.value] = offset / np.array(
            [0.001, -0.001, -0.001]
        )

        engine.finalize_lidar_diagnostics()

        self.assertGreater(before, 50.0)
        self.assertLess(engine.lidar_diagnostics["coarseLiDARMedianDistanceMillimetres"], 1e-6)
        self.assertLess(engine.lidar_diagnostics["coarseLiDARP95DistanceMillimetres"], 1e-6)
        self.assertEqual(engine.lidar_diagnostics["stage2PoseParameterDeltaFromCoarseLiDAR"], 0.0)
        self.assertEqual(engine.lidar_diagnostics["stage3FeatureVectorDeltaFromCoarseLiDAR"], 0.0)

    def test_photo_only_distance_is_not_overwritten_by_later_pair_refreshes(self):
        offset = np.array([0.01, -0.02, -0.10])
        engine = self.make_engine(cloud_offset=offset, prepare=False)
        engine.prepare_lidar_correspondences()
        initial = engine.lidar_diagnostics["photoOnlyMedianDistanceMillimetres"]
        engine.ex_txyz[PHOTO.FRONTAL.value] = offset / np.array(
            [0.001, -0.001, -0.001]
        )

        engine.prepare_lidar_correspondences()

        self.assertEqual(
            engine.lidar_diagnostics["photoOnlyMedianDistanceMillimetres"], initial
        )

    def test_fewer_than_100_bootstrap_pairs_leave_the_field_disabled(self):
        engine = self.make_engine(
            point_count=99,
            cloud_offset=[0.01, -0.02, -0.10],
            prepare=False,
        )

        engine.prepare_lidar_correspondences()

        pairs = engine.lidar_correspondences[PHOTO.FRONTAL.value]
        alignment = engine.lidar_diagnostics["correspondenceAlignment"]["front"]
        self.assertEqual(len(pairs.model_indices), 0)
        self.assertEqual(alignment["pairCount"], 0)
        self.assertEqual(alignment["rejectionReason"], "insufficient_bootstrap_pairs")
        self.assertTrue(engine.lidar_diagnostics["noInGateCorrespondences"])

    def test_over_250mm_offset_is_rejected_instead_of_forced(self):
        engine = self.make_engine(cloud_offset=[0.0, 0.0, -0.251], prepare=False)

        engine.prepare_lidar_correspondences()

        pairs = engine.lidar_correspondences[PHOTO.FRONTAL.value]
        alignment = engine.lidar_diagnostics["correspondenceAlignment"]["front"]
        self.assertEqual(len(pairs.model_indices), 0)
        self.assertEqual(alignment["rejectionReason"], "bootstrap_translation_exceeds_maximum")
        self.assertEqual(alignment["bootstrapPairCount"], 0)
        np.testing.assert_allclose(alignment["translationMetres"], [0.0, 0.0, -0.251])

    def test_tooth_pose_loss_changes_only_its_matching_translation_slice(self):
        engine = self.make_engine()
        configuration = LiDARToothPoseConfiguration(minimum_distinct_fields=1)
        target = arkit_points_from_em_camera(engine.X_deformed[0], 0.001)
        constraint = LiDARToothPoseConstraint(
            original_tooth_index=0,
            slot_id="U-01",
            photo_index=PHOTO.FRONTAL.value,
            field="front",
            points_k0_metres=target,
            contributing_keyframes=("K0", "K2", "K5"),
            configuration=configuration,
        )
        engine.set_lidar_tooth_pose_constraints({0: (constraint,)})
        engine.prepare_lidar_tooth_pose_correspondences()
        p_idx = {"tXYZs": 0, "rXYZs": 3}

        good_loss, good_gradient = engine.compute_lidar_tooth_pose_loss_and_gradient(
            np.ones(1), np.zeros((1, 3)), np.zeros((1, 3)), p_idx, 3, step=1
        )
        wrong_loss, wrong_gradient = engine.compute_lidar_tooth_pose_loss_and_gradient(
            np.ones(1), np.zeros((1, 3)), np.array([[5.0, 0.0, 0.0]]), p_idx, 3, step=1
        )

        self.assertLess(good_loss, wrong_loss)
        self.assertGreater(abs(wrong_gradient[0]), 0.0)
        np.testing.assert_array_equal(wrong_gradient[1:], np.zeros(2))

    def test_tooth_pose_uses_query_only_translation_bootstrap_when_raw_gate_is_empty(self):
        engine = self.make_engine()
        configuration = LiDARToothPoseConfiguration(
            minimum_distinct_fields=1,
            minimum_bootstrap_pair_count=30,
            maximum_bootstrap_translation_metres=0.02,
        )
        offset = np.array([0.0, 0.0, 0.008])
        constraint = LiDARToothPoseConstraint(
            original_tooth_index=0,
            slot_id="U-01",
            photo_index=PHOTO.FRONTAL.value,
            field="front",
            points_k0_metres=arkit_points_from_em_camera(engine.X_deformed[0], 0.001) + offset,
            contributing_keyframes=("K0", "K2", "K5"),
            configuration=configuration,
        )
        engine.set_lidar_tooth_pose_constraints({0: (constraint,)})

        engine.prepare_lidar_tooth_pose_correspondences()

        pair = engine.lidar_tooth_pose_correspondences[(0, "front")]
        diagnostic = engine.lidar_tooth_pose_diagnostics["correspondenceAlignment"]["U-01@front"]
        self.assertEqual(len(pair.model_indices), len(engine.X_deformed[0]))
        self.assertEqual(diagnostic["mode"], "translation_bootstrap")
        self.assertEqual(diagnostic["rawPairCount"], 0)
        np.testing.assert_allclose(diagnostic["translationMetres"], offset)

    def test_tooth_pose_bootstrap_rejects_translation_outside_stage_two_bounds(self):
        engine = self.make_engine()
        configuration = LiDARToothPoseConfiguration(
            minimum_distinct_fields=1,
            minimum_bootstrap_pair_count=30,
            maximum_bootstrap_translation_metres=0.012,
        )
        constraint = LiDARToothPoseConstraint(
            original_tooth_index=0,
            slot_id="U-01",
            photo_index=PHOTO.FRONTAL.value,
            field="front",
            points_k0_metres=arkit_points_from_em_camera(engine.X_deformed[0], 0.001)
            + np.array([0.0, 0.0, 0.013]),
            contributing_keyframes=("K0", "K2", "K5"),
            configuration=configuration,
        )
        engine.set_lidar_tooth_pose_constraints({0: (constraint,)})

        engine.prepare_lidar_tooth_pose_correspondences()

        pair = engine.lidar_tooth_pose_correspondences[(0, "front")]
        diagnostic = engine.lidar_tooth_pose_diagnostics["correspondenceAlignment"]["U-01@front"]
        self.assertEqual(len(pair.model_indices), 0)
        self.assertEqual(diagnostic["mode"], "disabled")
        self.assertEqual(diagnostic["rejectionReason"], "bootstrap_translation_exceeds_maximum")

    def test_tooth_pose_bootstrap_does_not_mutate_tooth_translation(self):
        engine = self.make_engine()
        before = engine.transVecXYZs.copy()
        configuration = LiDARToothPoseConfiguration(
            minimum_distinct_fields=1,
            minimum_bootstrap_pair_count=30,
            maximum_bootstrap_translation_metres=0.02,
        )
        constraint = LiDARToothPoseConstraint(
            original_tooth_index=0,
            slot_id="U-01",
            photo_index=PHOTO.FRONTAL.value,
            field="front",
            points_k0_metres=arkit_points_from_em_camera(engine.X_deformed[0], 0.001)
            + np.array([0.0, 0.0, 0.008]),
            contributing_keyframes=("K0", "K2", "K5"),
            configuration=configuration,
        )
        engine.set_lidar_tooth_pose_constraints({0: (constraint,)})

        engine.prepare_lidar_tooth_pose_correspondences()

        np.testing.assert_array_equal(engine.transVecXYZs, before)

    def test_final_tooth_pose_diagnostics_record_per_slot_pose_deltas_and_isolation(self):
        engine = self.make_engine()
        configuration = LiDARToothPoseConfiguration(minimum_distinct_fields=1)
        constraint = LiDARToothPoseConstraint(
            original_tooth_index=0,
            slot_id="U-01",
            photo_index=PHOTO.FRONTAL.value,
            field="front",
            points_k0_metres=arkit_points_from_em_camera(engine.X_deformed[0], 0.001),
            contributing_keyframes=("K0", "K2", "K5"),
            configuration=configuration,
        )
        engine.set_lidar_tooth_pose_constraints({0: (constraint,)})
        engine.begin_lidar_tooth_pose_diagnostics()
        engine.transVecXYZs[0] = [1.0, 2.0, 2.0]
        engine.rotVecXYZs[0] = [0.0, 0.0, 0.25]

        engine.finalize_lidar_tooth_pose_diagnostics()

        delta = engine.lidar_tooth_pose_diagnostics["poseDeltaNorms"]["U-01"]
        self.assertEqual(delta["translationSSMUnits"], 3.0)
        self.assertEqual(delta["rotationRadians"], 0.25)
        self.assertEqual(engine.lidar_tooth_pose_diagnostics["scaleParameterDeltaFromM6Loss"], 0.0)
        self.assertEqual(engine.lidar_tooth_pose_diagnostics["stage3FeatureVectorDeltaFromM6Loss"], 0.0)

    def test_photo_contour_diagnostics_keep_initial_and_final_losses(self):
        engine = self.make_engine()

        engine.set_lidar_photo_contour_diagnostics(1256.4876, 1091.3952)

        self.assertEqual(engine.lidar_diagnostics["photoContourLossBefore"], 1256.4876)
        self.assertEqual(engine.lidar_diagnostics["photoContourLossAfter"], 1091.3952)
        self.assertAlmostEqual(
            engine.lidar_diagnostics["photoContourLossChangePercent"],
            -13.1392,
            places=4,
        )

    def test_tooth_pose_rotation_is_stage_two_only(self):
        engine = self.make_engine()
        configuration = LiDARToothPoseConfiguration(minimum_distinct_fields=1)
        constraint = LiDARToothPoseConstraint(
            original_tooth_index=0,
            slot_id="U-01",
            photo_index=PHOTO.FRONTAL.value,
            field="front",
            points_k0_metres=arkit_points_from_em_camera(engine.X_deformed[0], 0.001),
            contributing_keyframes=("K0", "K2", "K5"),
            configuration=configuration,
        )
        engine.set_lidar_tooth_pose_constraints({0: (constraint,)})
        engine.prepare_lidar_tooth_pose_correspondences()
        p_idx = {"tXYZs": 0, "rXYZs": 0}

        rotation_loss, rotation_gradient = engine.compute_lidar_tooth_pose_loss_and_gradient(
            np.ones(1), np.array([[0.0, 0.0, 0.1]]), np.zeros((1, 3)), p_idx, 3, step=2
        )
        scale_loss, scale_gradient = engine.compute_lidar_tooth_pose_loss_and_gradient(
            np.ones(1), np.zeros((1, 3)), np.zeros((1, 3)), p_idx, 3, step=3
        )

        self.assertGreater(rotation_loss, 0.0)
        self.assertGreater(np.linalg.norm(rotation_gradient), 0.0)
        self.assertEqual(scale_loss, 0.0)
        np.testing.assert_array_equal(scale_gradient, np.zeros(3))

    def test_lidar_loss_is_global_stage_only_and_prefers_correct_scale(self):
        engine = self.make_engine()
        p_idx = {"ex_rxyz": 0, "ex_txyz": 15, "rowScaleXZ": 58, "lidarMetricScale": 60}
        good_loss, good_gradient = engine.compute_lidar_coarse_loss_and_gradient(
            engine.ex_rxyz, engine.ex_txyz, np.ones(2), 0.001, p_idx, 61, stage=1
        )
        wrong_loss, wrong_gradient = engine.compute_lidar_coarse_loss_and_gradient(
            engine.ex_rxyz, engine.ex_txyz, np.ones(2), 0.0005, p_idx, 61, stage=1
        )
        stage_two_loss, stage_two_gradient = engine.compute_lidar_coarse_loss_and_gradient(
            engine.ex_rxyz, engine.ex_txyz, np.ones(2), 0.0005, p_idx, 61, stage=2
        )
        stage_three_loss, stage_three_gradient = engine.compute_lidar_coarse_loss_and_gradient(
            engine.ex_rxyz, engine.ex_txyz, np.ones(2), 0.0005, p_idx, 61, stage=3
        )

        self.assertLess(good_loss, wrong_loss)
        self.assertGreater(abs(wrong_gradient[p_idx["lidarMetricScale"]]), 0.0)
        self.assertEqual(stage_two_loss, 0.0)
        np.testing.assert_array_equal(stage_two_gradient, np.zeros(61))
        self.assertEqual(stage_three_loss, 0.0)
        np.testing.assert_array_equal(stage_three_gradient, np.zeros(61))
        self.assertNotIn("bootstrap", p_idx)

    def test_coarse_lidar_weight_uses_millimetre_squared_units_like_the_ssm(self):
        engine = self.make_engine(cloud_offset=[0.005, 0.0, 0.0])
        p_idx = {"ex_rxyz": 0, "ex_txyz": 15, "lidarMetricScale": 30}

        loss, _ = engine.compute_lidar_coarse_loss_and_gradient(
            engine.ex_rxyz,
            engine.ex_txyz,
            engine.rowScaleXZ,
            0.001,
            p_idx,
            31,
            stage=0,
        )

        self.assertAlmostEqual(
            loss,
            engine.lidar_diagnostics["lastLossMetresSquared"] * 1_000_000.0 * 0.05,
            places=8,
        )

    def test_tooth_pose_lidar_weight_uses_millimetre_squared_units(self):
        engine = self.make_engine()
        configuration = LiDARToothPoseConfiguration(minimum_distinct_fields=1)
        constraint = LiDARToothPoseConstraint(
            original_tooth_index=0,
            slot_id="U-01",
            photo_index=PHOTO.FRONTAL.value,
            field="front",
            points_k0_metres=arkit_points_from_em_camera(engine.X_deformed[0], 0.001)
            + np.array([0.005, 0.0, 0.0]),
            contributing_keyframes=("K0", "K2", "K5"),
            configuration=configuration,
        )
        engine.set_lidar_tooth_pose_constraints({0: (constraint,)})
        engine.prepare_lidar_tooth_pose_correspondences()

        loss, _ = engine.compute_lidar_tooth_pose_loss_and_gradient(
            np.ones(1),
            np.zeros((1, 3)),
            np.zeros((1, 3)),
            {"tXYZs": 0},
            3,
            step=1,
        )

        self.assertAlmostEqual(
            loss,
            engine.lidar_tooth_pose_diagnostics["lastLossMetresSquared"]
            * 1_000_000.0
            * 0.02,
            places=8,
        )

    def test_tooth_shape_prefers_the_matching_pca_coefficient(self):
        engine = self.make_shape_engine()
        p_idx = {"featureVec": 0}

        good_loss, _ = engine.compute_lidar_tooth_shape_loss_and_gradient(
            np.array([[[1.0]]]), p_idx, 1, stage=3
        )
        wrong_loss, _ = engine.compute_lidar_tooth_shape_loss_and_gradient(
            np.array([[[0.0]]]), p_idx, 1, stage=3
        )

        self.assertLess(good_loss, wrong_loss)

    def test_tooth_shape_lidar_weight_uses_millimetre_squared_units(self):
        engine = self.make_shape_engine()
        candidate = np.array([[[0.0]]])
        constraint = engine.lidar_tooth_shape_constraints[0][0]
        camera, _ = engine._lidar_tooth_camera_points(
            constraint,
            engine.scales,
            engine.rotVecXYZs,
            engine.transVecXYZs,
            deformed_points=engine.updateDeformedPointPos(candidate, np.array([0]))[0],
        )
        pair = engine.lidar_tooth_shape_correspondences[(0, constraint.field)]
        raw_loss, _ = huber_point_to_surface_loss(
            arkit_points_from_em_camera(camera[pair.model_indices], engine.lidar_metric_scale),
            constraint.points_k0_metres[pair.lidar_indices],
            constraint.configuration.huber_delta_metres,
        )

        loss, _ = engine.compute_lidar_tooth_shape_loss_and_gradient(
            candidate, {"featureVec": 0}, 1, stage=3
        )

        self.assertAlmostEqual(loss, raw_loss * 1_000_000.0 * 0.002, places=8)

    def test_tooth_shape_gradient_matches_central_difference(self):
        engine = self.make_shape_engine()
        p_idx = {"featureVec": 0}
        candidate = np.array([[[0.25]]])
        _, gradient = engine.compute_lidar_tooth_shape_loss_and_gradient(
            candidate, p_idx, 1, stage=3
        )
        epsilon = 1e-5
        plus, _ = engine.compute_lidar_tooth_shape_loss_and_gradient(
            candidate + epsilon, p_idx, 1, stage=3
        )
        minus, _ = engine.compute_lidar_tooth_shape_loss_and_gradient(
            candidate - epsilon, p_idx, 1, stage=3
        )

        self.assertAlmostEqual(gradient[0], (plus - minus) / (2.0 * epsilon), places=8)

    def test_tooth_shape_gradient_changes_only_the_constrained_tooth_slice(self):
        engine = self.make_shape_engine(tooth_count=2)
        p_idx = {"featureVec": 0}

        loss, gradient = engine.compute_lidar_tooth_shape_loss_and_gradient(
            np.zeros((2, 1, 1)), p_idx, 2, stage=3
        )

        self.assertGreater(loss, 0.0)
        self.assertGreater(abs(gradient[0]), 0.0)
        self.assertEqual(gradient[1], 0.0)

    def test_tooth_shape_requires_two_nonzero_m6_fields_and_stage_three(self):
        engine = self.make_shape_engine(field_count=1)
        p_idx = {"featureVec": 0}

        self.assertFalse(engine.lidar_tooth_shape_diagnostics["enabled"])
        self.assertEqual(
            engine.lidar_tooth_shape_diagnostics["reason"],
            "fewer_than_two_fields_with_m6_pairs",
        )
        for stage in (0, 1, 2):
            loss, gradient = engine.compute_lidar_tooth_shape_loss_and_gradient(
                np.zeros((1, 1, 1)), p_idx, 1, stage=stage
            )
            self.assertEqual(loss, 0.0)
            np.testing.assert_array_equal(gradient, np.zeros(1))

    def test_tooth_shape_does_not_activate_before_stage_two_boundary(self):
        engine = self.make_shape_engine()
        engine.lidar_tooth_shape_activation_allowed = False

        engine.prepare_lidar_tooth_shape_correspondences()

        self.assertFalse(engine.lidar_tooth_shape_diagnostics["enabled"])
        self.assertEqual(
            engine.lidar_tooth_shape_diagnostics["reason"], "stage_two_not_complete"
        )

    def test_tooth_shape_keeps_m5_rejection_reason_during_stage_three(self):
        engine = self.make_shape_engine()
        engine.lidar_tooth_shape_activation_allowed = False
        engine.lidar_constraints = {}
        engine.lidar_diagnostics = {"fallbackApplied": True}

        engine.prepare_lidar_tooth_shape_correspondences()

        self.assertFalse(engine.lidar_tooth_shape_diagnostics["enabled"])
        self.assertEqual(
            engine.lidar_tooth_shape_diagnostics["reason"], "m5_candidate_rejected"
        )

    def test_tooth_shape_rejects_uncalibrated_m6_provenance(self):
        engine = self.make_shape_engine()
        uncalibrated = tuple(
            LiDARToothPoseConstraint(
                original_tooth_index=value.original_tooth_index,
                slot_id=value.slot_id,
                photo_index=value.photo_index,
                field=value.field,
                points_k0_metres=value.points_k0_metres,
                contributing_keyframes=value.contributing_keyframes,
                configuration=value.configuration,
                calibrated_rgb_depth=False,
            )
            for value in engine.lidar_tooth_pose_constraints[0]
        )
        engine.lidar_tooth_pose_constraints = {0: uncalibrated}

        engine.prepare_lidar_tooth_shape_correspondences()

        self.assertFalse(engine.lidar_tooth_shape_diagnostics["enabled"])
        self.assertEqual(
            engine.lidar_tooth_shape_diagnostics["reason"],
            "fewer_than_two_fields_with_m6_pairs",
        )

    def test_shape_only_optimizer_keeps_neighboring_feature_slices_fixed(self):
        engine = object.__new__(EMOpt5Views)
        engine.Mask = np.array([True, True])
        engine.numTooth = 2
        engine.numPC = 1
        engine.featureVec = np.array([[[0.0]], [[3.0]]])
        engine.lidar_tooth_shape_constraints = {0: (object(),)}
        engine.update_lidar_tooth_shape_diagnostics = MethodType(
            lambda self: None, engine
        )

        def parameters(self, stage, step):
            return np.array([10.0, 20.0, 0.0, 3.0]), {"featureVec": 2}

        def bounds(self, values, p_idx, stage, step):
            return [(value, value) for value in values[:2]] + [(-5.0, 5.0)] * 2

        def loss(self, values, p_idx, stage, step, verbose, return_grad=False):
            objective = (values[2] - 1.0) ** 2 + (values[3] - 9.0) ** 2
            if not return_grad:
                return objective
            gradient = np.zeros_like(values)
            gradient[2] = 2.0 * (values[2] - 1.0)
            gradient[3] = 2.0 * (values[3] - 9.0)
            return objective, gradient

        engine.getCurrentGlobalParamsOf5Views_as_x0 = MethodType(parameters, engine)
        engine.getParamBounds = MethodType(bounds, engine)
        engine.MStepLoss = MethodType(loss, engine)

        engine.maximization_lidar_tooth_shape_only(maxiter=20)

        self.assertAlmostEqual(engine.featureVec[0, 0, 0], 1.0, places=5)
        self.assertEqual(engine.featureVec[1, 0, 0], 3.0)


if __name__ == "__main__":
    unittest.main()
