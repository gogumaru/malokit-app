import unittest

import numpy as np

from const import PHOTO
import emopt5views
import emopt5views_lidar

ENGINE_MODULES = {
    "emopt5views": emopt5views.EMOpt5Views,
    "emopt5views_lidar": emopt5views_lidar.EMOpt5Views,
}


def make_two_tooth_engine(engine_cls, photo_type, *, rela_txyz=(1.0, 2.0, 3.0)):
    """Minimal engine exercising computePixelResidualError for one view.

    Two "teeth": index 0 sits above the ul_sp split (upper, never touched
    by the bite transform), index 1 sits below it (lower, transformed by
    rela_R/rela_txyz when the view is wired into bite registration).
    """
    engine = object.__new__(engine_cls)
    ph = photo_type.value

    tooth_upper = np.array([[-1.0, 0.0, 100.0], [0.0, 1.0, 101.0], [1.0, 0.0, 100.0]])
    tooth_lower = np.array([[-1.0, -2.0, 100.0], [0.0, -1.0, 101.0], [1.0, -2.0, 100.0]])
    # xy components must be nonzero: jacobs_hatni_wrt_gn divides by the
    # camera-space normal's xy norm, so a purely-z normal produces NaN
    # (which would make a "gradient reaches rela pose" assertion vacuously
    # true regardless of whether the gating fix is applied).
    normals = np.tile(np.array([0.2, 0.3, 1.0]), (3, 1))

    engine.X_deformed_pred = {ph: [tooth_upper, tooth_lower]}
    engine.X_deformed_pred_normals = {ph: [normals.copy(), normals.copy()]}
    engine.visIdx = {ph: np.array([0, 1], dtype=np.intp)}
    engine.corre_pred_idx = {ph: np.arange(6)}
    engine.ul_sp = {ph: 1}
    engine.P_true_99_percentile = {ph: np.zeros((6, 2))}
    engine.weight_point2point = 0.04
    engine.weight_point2plane = 2.0
    engine.dpix = {ph: 0.1}

    extr_view_mat = engine.updateExtrinsicViewMatrix(
        np.zeros(3), np.array([0.0, 0.0, 200.0])
    )
    intr_proj_mat = engine.updateIntrinsicProjectionMatrix(100.0, 0.1, 400.0, 300.0)
    rela_R = engine.updateRelaRotMat(np.array([0.05, 0.0, 0.0]))

    return engine, extr_view_mat, intr_proj_mat, rela_R, np.array(rela_txyz)


class BiteRegistrationOcclusalGradientTests(unittest.TestCase):
    def _assert_gradient_reaches_rela_params(self, engine_cls, photo_type, msg):
        engine, extr_view_mat, intr_proj_mat, rela_R, rela_txyz = make_two_tooth_engine(
            engine_cls, photo_type
        )

        _, grad = engine.computePixelResidualError(
            photo_type,
            featureVec=None,
            scales=None,
            rotVecXYZs=None,
            transVecXYZs=None,
            extrViewMat=extr_view_mat,
            intrProjMat=intr_proj_mat,
            rela_R=rela_R,
            rela_txyz=rela_txyz,
            stage=1,
            return_grad=True,
        )

        # stage=1 appends 2 extra rowScaleXZ gradient entries after
        # rela_relat, so rela_relar/rela_relat aren't the very last 6.
        grad_relar = grad[-8:-5]
        grad_relat = grad[-5:-2]
        self.assertTrue(np.any(grad_relar != 0) or np.any(grad_relat != 0), msg)

    def test_occlusal_view_gradient_reaches_rela_pose_params(self):
        for name, engine_cls in ENGINE_MODULES.items():
            with self.subTest(module=name):
                self._assert_gradient_reaches_rela_params(
                    engine_cls,
                    PHOTO.UPPER,
                    "occlusal (UPPER) residual should influence rela_rxyz/rela_txyz gradient",
                )

    def test_lateral_view_gradient_still_reaches_rela_pose_params(self):
        for name, engine_cls in ENGINE_MODULES.items():
            with self.subTest(module=name):
                self._assert_gradient_reaches_rela_params(
                    engine_cls,
                    PHOTO.FRONTAL,
                    "frontal residual should still influence rela_rxyz/rela_txyz gradient (no regression)",
                )


class BiteRotationSearchSpaceTests(unittest.TestCase):
    """rela_rxyz has no grid search today, only a tight (+/-0.05 rad) local
    SLSQP refinement around [0,0,0] - too narrow to find a real crossbite
    rotation. gridSearchRelativePoseParams must add a rotation entry per
    axis, scored against the occlusal views (the ones that most directly
    show a left/right crossbite), with candidates wider than that bound.
    """

    SLSQP_LOCAL_BOUND_RAD = 0.05

    def test_rotation_entries_are_scored_by_occlusal_views_beyond_local_bound(self):
        for name, engine_cls in ENGINE_MODULES.items():
            with self.subTest(module=name):
                engine = object.__new__(engine_cls)
                engine.rela_txyz_default = np.array([0.0, -5.0, 0.0])
                engine.rela_rxyz_default = np.array([0.0, 0.0, 0.0])

                search_space = engine.relativePoseParamSearchSpace()

                for axis in ("x", "y", "z"):
                    key = f"rela.r.{axis}"
                    self.assertIn(key, search_space)
                    candidates, views = search_space[key]
                    self.assertEqual(set(views), {PHOTO.UPPER, PHOTO.LOWER})
                    self.assertTrue(
                        np.any(np.abs(candidates) > self.SLSQP_LOCAL_BOUND_RAD),
                        f"{key} candidates must reach beyond the SLSQP local "
                        "bound or a real crossbite rotation is never searched",
                    )


class LowerArchSplitIndexTests(unittest.TestCase):
    """An occlusal photo shows only ONE arch, unlike frontal/lateral photos
    which show both. ul_sp ("where do lower-arch points start in this
    view's visible-tooth list") must handle that instead of crashing.

    Reproduces the on-device crash: "zero-size array to reduction
    operation minimum which has no identity" when every visible tooth in
    an UPPER (occlusal) photo is upper-arch, so no index satisfies
    `visIdx >= numUpperTooth` and the old `.min()` call had nothing to
    reduce.
    """

    def test_all_upper_arch_visible_returns_no_lower_points_split(self):
        for name, engine_cls in ENGINE_MODULES.items():
            with self.subTest(module=name):
                visible = np.array([0, 1, 2], dtype=np.intp)
                split = engine_cls._lower_arch_split_index(visible, num_upper_tooth=5)
                self.assertEqual(split, len(visible))

    def test_all_lower_arch_visible_returns_zero_split(self):
        for name, engine_cls in ENGINE_MODULES.items():
            with self.subTest(module=name):
                visible = np.array([5, 6, 7], dtype=np.intp)
                split = engine_cls._lower_arch_split_index(visible, num_upper_tooth=5)
                self.assertEqual(split, 0)

    def test_mixed_arch_visible_returns_first_lower_index(self):
        for name, engine_cls in ENGINE_MODULES.items():
            with self.subTest(module=name):
                visible = np.array([0, 1, 5, 6], dtype=np.intp)
                split = engine_cls._lower_arch_split_index(visible, num_upper_tooth=5)
                self.assertEqual(split, 2)


class RenderPredictedEdgeMaskBoundsTests(unittest.TestCase):
    """Reproduces the on-device crash surfaced once occlusal (UPPER/LOWER)
    photos started actually taking part in bite fitting: predicted points
    for a still-converging occlusal pose can land outside the ground-truth
    edge mask's pixel bounds, and renderPredictedEdgeMask indexed them
    unclipped -> "index 543 is out of bounds for axis 0 with size 533".
    """

    def test_out_of_bounds_predicted_point_does_not_crash(self):
        for name, engine_cls in ENGINE_MODULES.items():
            with self.subTest(module=name):
                engine = object.__new__(engine_cls)
                ph = PHOTO.UPPER.value
                engine.edgeMask = {ph: np.zeros((10, 10))}
                # second point is out of bounds on both axes
                engine.P_pred = {ph: np.array([[9.0, 9.0], [15.0, 20.0]])}

                mask = engine.renderPredictedEdgeMask(PHOTO.UPPER, dilate=False)

                self.assertEqual(mask.shape, (10, 10))
                self.assertGreater(mask[9, 9], 0)


if __name__ == "__main__":
    unittest.main()
