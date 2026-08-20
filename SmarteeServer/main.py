import argparse
import functools
import glob
import json
import os
import subprocess
import warnings
from pathlib import Path

# Suppress numpy warnings about divide by zero (expected in optimization)
warnings.filterwarnings('ignore', category=RuntimeWarning)

os.environ["CUDA_VISIBLE_DEVICES"] = "-1"  # run on CPU
# ponytail: single-threaded OpenMP avoids the multi-libomp crash on macOS/arm64
# (open3d, sklearn, skimage each bundle their own libomp.dylib; open3d's Poisson
# mesh reconstruction segfaults in __kmp_invoke_microtask when they collide).
# Must be set before open3d is imported below. Drop the OMP_NUM_THREADS=1 line
# only if you consolidate to a single OpenMP runtime.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import sys

import h5py
import matplotlib.pyplot as plt
import numpy as np
import skimage.io
import skimage.transform
import open3d as o3d
import psutil
import ray

import pcd_mesh_utils as pm_util
import recons_eval_metric as metric
from const import *
from emopt5views import EMOpt5Views
from seg.edge_backends import (
    EDGE_BACKENDS,
    predict_automatic_edge_predictions,
    resolve_edge_backend,
)
from seg.instance_artifacts import write_instance_bundle
from seg.prediction_types import EdgePrediction
from seg.seg_const import IMG_SHAPE
from seg.seg_model import ASPP_UNet
from seg.rfdetr_bridge import predict_rfdetr_predictions
from seg.utils import predict_teeth_contour
from patient_texture import colorize_reconstructed_meshes
from seg.optimization_selection import BestOptimizationState
from seg.lidar_constraint_diagnostics import (
    assess_coarse_lidar_candidate,
    build_lidar_diagnostic_payload,
    persist_lidar_diagnostic_json,
)

TEMP_DIR = r"./demo/_temp/"
os.makedirs(TEMP_DIR, exist_ok=True)

NUM_CPUS = psutil.cpu_count(logical=False)
print = functools.partial(print, flush=True)


def _assess_lidar_diagnostics(diagnostic):
    """Run the documented M5 acceptance gate against an already-computed
    `lidar_diagnostics` dict (does not mutate it)."""

    pair_count = sum(int(value) for value in diagnostic.get("pairCounts", {}).values())
    return assess_coarse_lidar_candidate(
        photo_only_median_millimetres=diagnostic.get(
            "photoOnlyMedianDistanceMillimetres", float("nan")
        ),
        photo_only_p95_millimetres=diagnostic.get(
            "photoOnlyP95DistanceMillimetres", float("nan")
        ),
        coarse_median_millimetres=diagnostic.get(
            "coarseLiDARMedianDistanceMillimetres", float("nan")
        ),
        coarse_p95_millimetres=diagnostic.get(
            "coarseLiDARP95DistanceMillimetres", float("nan")
        ),
        photo_contour_loss_before=diagnostic.get(
            "photoContourLossBefore", float("nan")
        ),
        photo_contour_loss_after=diagnostic.get(
            "photoContourLossAfter", float("nan")
        ),
        pair_count=pair_count,
    )


def apply_coarse_lidar_acceptance_gate(emopt, photo_only_parameters):
    """Keep M5 only when its final candidate passes the documented validation gate."""

    diagnostic = emopt.lidar_diagnostics
    decision = _assess_lidar_diagnostics(diagnostic)
    diagnostic["accepted"] = decision.accepted
    diagnostic["reason"] = decision.reason
    if decision.accepted:
        return True

    retained = dict(diagnostic)
    retained["inputEligible"] = bool(emopt.lidar_constraints)
    retained["enabled"] = False
    retained["fallbackApplied"] = True
    emopt.load_e_step_result_from_dict(photo_only_parameters)
    emopt.lidar_constraints = {}
    emopt.lidar_correspondences = {}
    emopt.lidar_diagnostics = retained
    # lidar_tooth_pose_constraints/lidar_tooth_shape_* are deliberately left
    # untouched here: M5's coarse whole-jaw candidate failed its own
    # photo-contour check, but that doesn't mean per-tooth LiDAR evidence is
    # bad. Stage 2 already unconditionally rebuilds M6 correspondence pairs
    # against whichever pose ends up loaded (emopt5views_lidar.py:2522,
    # :2634), re-validated by M6's own strict gates (bootstrap distance,
    # distinct-field count) every time. M7 does the same via its own
    # 2-distinct-fields-with-pairs check. Wiping them here only threw away a
    # fair shot at those independent, already-strict checks.
    return False


def select_best_coarse_lidar_candidate(emopt, candidates, photo_only_parameters):
    """Evaluate multiple M5 LiDAR candidates (each already run through Stage
    0/1 from the same grid-search state, with `emopt.lidar_diagnostics`
    snapshotted right after `finalize_lidar_diagnostics()` +
    `set_lidar_photo_contour_diagnostics()` for that candidate) against the
    documented acceptance gate, and keep whichever passes with the lowest
    coarse median surface distance. Falls back to photo-only — via the same
    tested rejection bookkeeping as `apply_coarse_lidar_acceptance_gate` —
    when none pass, so a weaker candidate can never do worse than today.

    `candidates` is a list of dicts: {"label": str, "parameters": dict,
    "diagnostics": dict}.

    Returns (accepted: bool, winning_label: str | None).
    """

    passing = [
        candidate
        for candidate in candidates
        if _assess_lidar_diagnostics(candidate["diagnostics"]).accepted
    ]
    if not passing:
        emopt.lidar_diagnostics = dict(candidates[0]["diagnostics"])
        apply_coarse_lidar_acceptance_gate(emopt, photo_only_parameters)
        return False, None

    winner = min(
        passing,
        key=lambda candidate: candidate["diagnostics"]["coarseLiDARMedianDistanceMillimetres"],
    )
    decision = _assess_lidar_diagnostics(winner["diagnostics"])
    emopt.load_e_step_result_from_dict(winner["parameters"])
    emopt.lidar_diagnostics = dict(winner["diagnostics"])
    emopt.lidar_diagnostics["accepted"] = True
    emopt.lidar_diagnostics["reason"] = decision.reason
    emopt.lidar_diagnostics["selectedBootstrapMode"] = winner["label"]
    emopt.prepare_lidar_correspondences(bootstrap_mode=winner["label"])
    return True, winner["label"]


EDGE_MASK_DIR = r"./demo/edge_masks"  # optional hand-edited masks: ./demo/edge_masks/<tag>/<tag>-<i>.png
INSTANCE_MASK_DIR = os.path.join(TEMP_DIR, "instance_masks")
LIDAR_DIAGNOSTIC_DIR = os.path.join(TEMP_DIR, "lidar_constraints")
RFDETR_PHOTO_VALUES = tuple(photo_type.value for photo_type in PHOTO_TYPES)


def load_edge_mask(maskfile, imgfile):
    """Load a hand-edited edge mask as a 2D binary array at the size the
    predictor would produce, so the optimizer's camera geometry is unchanged."""
    m = skimage.io.imread(maskfile)
    if m.ndim == 3:
        m = m[..., :3].max(axis=-1)  # white line on black -> lit; ignore alpha
    mask = m > 127
    h, w = skimage.io.imread(imgfile).shape[:2]
    scale = RECONS_IMG_WIDTH / w
    target = (int(scale * h), int(scale * w))
    if mask.shape != target:  # only if edited at a different resolution
        mask = skimage.transform.resize(mask.astype(float), target, order=0) > 0.5
    return (mask * 255).astype(np.uint8)


def getToothIndex(f):
    return int(os.path.basename(f).split(".")[0].split("_")[-1])


def loadMuEigValSigma(ssmDir, numPC):
    """Mu.shape=(28,1500,3), sqrtEigVals.shape=(28,1,100), Sigma.shape=(28,4500,100)"""
    muNpys = glob.glob(os.path.join(ssmDir, "meanAlignedPG_*.npy"))
    muNpys = sorted(muNpys, key=lambda x: getToothIndex(x))
    Mu = np.array([np.load(x) for x in muNpys])
    eigValNpys = glob.glob(os.path.join(ssmDir, "eigVal_*.npy"))
    eigValNpys = sorted(eigValNpys, key=lambda x: getToothIndex(x))
    sqrtEigVals = np.sqrt(np.array([np.load(x) for x in eigValNpys]))
    eigVecNpys = glob.glob(os.path.join(ssmDir, "eigVec_*.npy"))
    eigVecNpys = sorted(eigVecNpys, key=lambda x: getToothIndex(x))
    Sigma = np.array([np.load(x) for x in eigVecNpys])
    return Mu, sqrtEigVals[:, np.newaxis, :numPC], Sigma[..., :numPC]


def run_global_emopt_stages(emopt: EMOpt5Views, verbose: bool = False):
    """Run Stage 0/1 and return a deep-copied selected state before Stage 2."""

    emopt.expectation_step_5Views(-1, verbose)
    min_e_loss = emopt.get_e_loss()
    initial_photo_contour_loss = min_e_loss
    stage0_best = BestOptimizationState(
        min_e_loss, emopt.get_current_e_step_result()
    )

    # stage0initMatFile = os.path.join(TEMP_DIR, "E-step-result-stage0-init.mat")
    # stage0finalMatFile = os.path.join(TEMP_DIR, "E-step-result-stage0-final.mat")

    # emopt.save_expectation_step_result(stage0initMatFile) # save checkpoint

    maxiter = 20
    stageIter = [10, 5, 10]
    # stage 0 & 1 optimization

    print("-" * 100)
    print("Start Stage 0.")
    stage = 0

    # # Continue from checkpoint "E-step-result-stage0-init.mat"
    # emopt.load_expectation_step_result(stage0initMatFile, stage)
    # emopt.expectation_step_5Views(stage, verbose)

    E_loss = []
    for it in range(stageIter[0]):
        emopt.maximization_step_5Views(stage, step=-1, maxiter=maxiter, verbose=False)
        print("M-step loss: {:.4f}".format(emopt.loss_maximization_step))
        emopt.expectation_step_5Views(stage, verbose)
        e_loss = emopt.get_e_loss()
        stage0_best.consider(e_loss, emopt.get_current_e_step_result())
        min_e_loss = stage0_best.loss
        print("Sum of expectation step loss: {:.4f}".format(e_loss))
        if len(E_loss) >= 2 and e_loss >= np.mean(E_loss[-2:]):
            print(
                "Early stop with last 3 e-step loss {:.4f}, {:.4f}, {:.4f}".format(
                    E_loss[-2], E_loss[-1], e_loss
                )
            )
            E_loss.append(e_loss)
            break
        else:
            E_loss.append(e_loss)

    # Load best result of stage 0
    emopt.load_e_step_result_from_dict(stage0_best.parameters)
    emopt.expectation_step_5Views(stage, verbose)
    E_loss.append(min_e_loss)

    # emopt.save_expectation_step_result(stage0finalMatFile)  # save checkpoint

    skipStage1Flag = False
    print("-" * 100)
    print("Start Stage 1.")

    stage = 1
    stage1_best = BestOptimizationState(E_loss[-1], emopt.get_current_e_step_result())
    for it in range(stageIter[1]):
        emopt.maximization_step_5Views(stage, step=-1, maxiter=maxiter, verbose=False)
        print("M-step loss: {:.4f}".format(emopt.loss_maximization_step))
        emopt.expectation_step_5Views(stage, verbose)
        e_loss = emopt.get_e_loss()
        print("Sum of expectation step loss: {:.4f}".format(e_loss))
        stage1_best.consider(e_loss, emopt.get_current_e_step_result())
        if e_loss >= E_loss[-1]:
            if it == 0:
                skipStage1Flag = True  # first optimization with rowScaleXZ gets worse result compared with optimziaiton without rowScaleXZ
            print(
                "Early stop with last 3 e-step loss {:.4f}, {:.4f}, {:.4f}".format(
                    E_loss[-2], E_loss[-1], e_loss
                )
            )
            break
        else:
            E_loss.append(e_loss)

    # whether to skip stage1 to avoid extreme deformation
    if skipStage1Flag == True:
        print("Skip Stage 1; Reverse to Stage 0 final result.")
        emopt.rowScaleXZ = np.ones((2,))
        emopt.load_e_step_result_from_dict(stage0_best.parameters)
        # # Continue from checkpoint "E-step-result-stage0-final.mat"
        # emopt.load_expectation_step_result(stage0finalMatFile, stage=2)
    else:
        emopt.load_e_step_result_from_dict(stage1_best.parameters)
        print("Accept Stage 1.")
        print("emopt.rowScaleXZ: ", emopt.rowScaleXZ)
        print("approx tooth scale: ", np.prod(emopt.rowScaleXZ) ** (1 / 3))

    # Measure the selected state while rowScaleXZ still represents Stage 1.
    emopt.expectation_step_5Views(stage, verbose)
    selected_loss = emopt.get_e_loss()
    selected = BestOptimizationState(
        selected_loss, emopt.get_current_e_step_result()
    )
    return {
        "parameters": selected.parameters,
        "loss": selected.loss,
        "initialLoss": float(initial_photo_contour_loss),
    }


def run_gated_m7_shape_experiment(
    emopt, *, maxiter: int, verbose: bool, enabled: bool
) -> bool:
    """Run M7 whenever M6 evidence clears its own gates, or record a control run."""

    if not enabled:
        emopt.lidar_tooth_shape_constraints = {}
        emopt.lidar_tooth_shape_correspondences = {}
        emopt.lidar_tooth_shape_activation_allowed = False
        emopt.lidar_tooth_shape_diagnostics = {
            "enabled": False,
            "reason": "disabled_by_comparison_mode",
        }
        return False

    # No separate check on M5's accept/reject here: M7 has its own strict
    # 2-distinct-fields-with-pairs gate below (in
    # prepare_lidar_tooth_shape_correspondences), which re-validates
    # correctness regardless of which pose (M5-accepted or photo-only
    # fallback) is currently loaded.
    if emopt.lidar_tooth_pose_constraints:
        emopt.prepare_lidar_tooth_pose_correspondences()
    emopt.lidar_tooth_shape_activation_allowed = True
    emopt.prepare_lidar_tooth_shape_correspondences()
    if not emopt.lidar_tooth_shape_constraints:
        return False
    emopt.maximization_lidar_tooth_shape_only(maxiter=maxiter, verbose=False)
    emopt.expectation_step_5Views(stage=3, verbose=verbose)
    return True


def run_emopt(
    emopt: EMOpt5Views,
    verbose: bool = False,
    enable_m7_shape_experiment: bool = True,
):
    # 3d teeth reconstruction by optimization
    print("-" * 100)
    print("Start optimization.")

    print("-" * 100)
    print("Start Grid Search.")
    emopt.searchDefaultRelativePoseParams()
    emopt.gridSearchExtrinsicParams()
    emopt.gridSearchRelativePoseParams()

    has_m5_candidate = bool(
        getattr(emopt, "lidar_constraints", {})
    ) and hasattr(emopt, "finalize_lidar_diagnostics")
    if has_m5_candidate:
        grid_state = BestOptimizationState(
            0.0, emopt.get_current_e_step_result()
        ).parameters
        lidar_constraints = emopt.lidar_constraints

        # Establish the real photo-only counterfactual from the exact same
        # grid-search state. It is retained only if the M5 candidate fails.
        emopt.lidar_constraints = {}
        emopt.lidar_correspondences = {}
        print("-" * 100)
        print("Evaluate photo-only global reference.")
        photo_global = run_global_emopt_stages(emopt, verbose)

        emopt.lidar_constraints = lidar_constraints
        emopt.load_e_step_result_from_dict(photo_global["parameters"])
        emopt.prepare_lidar_correspondences()
        emopt.lidar_diagnostics.pop("photoOnlyMedianDistanceMillimetres", None)
        emopt.lidar_diagnostics.pop("photoOnlyP95DistanceMillimetres", None)
        emopt._record_lidar_distance_diagnostics(prefix="photoOnly")

        # Evaluate both bootstrap methods from the same grid-search state and
        # let the acceptance gate keep whichever verifies best — trying an
        # extra candidate can only be discarded by the gate, never make the
        # result worse than the single-candidate path it replaces.
        candidates = []
        for bootstrap_mode in ("translation", "rigid"):
            emopt.load_e_step_result_from_dict(grid_state)
            print("-" * 100)
            print(f"Evaluate M5 global candidate ({bootstrap_mode} bootstrap).")
            emopt.prepare_lidar_correspondences(bootstrap_mode=bootstrap_mode)
            lidar_global = run_global_emopt_stages(emopt, verbose)
            emopt.load_e_step_result_from_dict(lidar_global["parameters"])
            emopt.prepare_lidar_correspondences(bootstrap_mode=bootstrap_mode)
            emopt.finalize_lidar_diagnostics()
            emopt.set_lidar_photo_contour_diagnostics(
                photo_global["loss"], lidar_global["loss"]
            )
            candidates.append({
                "label": bootstrap_mode,
                "parameters": lidar_global["parameters"],
                "loss": lidar_global["loss"],
                "diagnostics": dict(emopt.lidar_diagnostics),
            })

        accepted, winning_mode = select_best_coarse_lidar_candidate(
            emopt, candidates, photo_global["parameters"]
        )
        selected_global = (
            next(c for c in candidates if c["label"] == winning_mode)
            if accepted
            else photo_global
        )
        print(
            "M5 final acceptance: "
            + ("accepted" if accepted else "photo-only fallback")
            + f" ({emopt.lidar_diagnostics.get('reason')})"
            + (f" [{winning_mode} bootstrap]" if accepted else "")
        )
    else:
        selected_global = run_global_emopt_stages(emopt, verbose)

    emopt.load_e_step_result_from_dict(selected_global["parameters"])
    emopt.anistropicRowScale2ScalesAndTransVecs()
    emopt.expectation_step_5Views(stage=1, verbose=verbose)
    min_e_loss = float(selected_global["loss"])
    stage23_best = BestOptimizationState(
        min_e_loss, emopt.get_current_e_step_result()
    )
    maxiter = 20
    stageIter = [10, 5, 10]

    # Stage = 2 and 3
    print("-" * 100)
    print("Start Stage 2 and 3.")
    stage = 2
    E_loss = [
        min_e_loss,
    ]
    for it in range(stageIter[2]):
        emopt.maximization_step_5Views(stage, step=2, maxiter=maxiter, verbose=False)
        emopt.maximization_step_5Views(stage, step=3, maxiter=maxiter, verbose=False)
        emopt.maximization_step_5Views(stage=3, step=-1, maxiter=maxiter, verbose=False)
        emopt.maximization_step_5Views(stage, step=1, maxiter=maxiter, verbose=False)
        print("M-step loss: {:.4f}".format(emopt.loss_maximization_step))
        emopt.expectation_step_5Views(stage=3, verbose=verbose)
        e_loss = emopt.get_e_loss()
        stage23_best.consider(e_loss, emopt.get_current_e_step_result())
        min_e_loss = stage23_best.loss
        print("Sum of expectation step loss: {:.4f}".format(e_loss))
        if len(E_loss) >= 2 and (e_loss >= np.mean(E_loss[-2:])):
            print(
                "Early stop with last 3 e-step loss {:.4f}, {:.4f}, {:.4f}".format(
                    E_loss[-2], E_loss[-1], e_loss
                )
            )
            break
        else:
            E_loss.append(e_loss)

    # Load best result of stage 2 and 3
    emopt.load_e_step_result_from_dict(stage23_best.parameters)
    emopt.expectation_step_5Views(stage=3, verbose=verbose)

    # The LiDAR engine's M7 experiment runs once from the selected final pose.
    # Rebuild M6 pairs at that pose, then activate shape only if one calibrated
    # tooth still has positive pairs in at least two direct fields.
    if hasattr(emopt, "lidar_tooth_shape_activation_allowed"):
        run_gated_m7_shape_experiment(
            emopt,
            maxiter=maxiter,
            verbose=verbose,
            enabled=enable_m7_shape_experiment,
        )

    return emopt


def evaluation(h5File, X_Ref_Upper, X_Ref_Lower):
    """
    h5file: emopt result saved in h5 format
    X_Ref_Upper, X_Ref_Lower: List of numpy arrays
    """
    with h5py.File(h5File, "r") as f:
        grp = f["EMOPT"]
        X_Pred_Upper = grp["UPPER_PRED"][:]
        X_Pred_Lower = grp["LOWER_PRED"][:]

    _X_Ref = X_Ref_Upper + X_Ref_Lower  # List concat
    print(
        "Compare prediction shape aligned by similarity registration with ground truth."
    )
    with_scale = True
    TX_Upper = pm_util.getAlignedSrcPointCloud(
        X_Pred_Upper.reshape(-1, 3), np.concatenate(X_Ref_Upper), with_scale=with_scale
    )
    TX_Lower = pm_util.getAlignedSrcPointCloud(
        X_Pred_Lower.reshape(-1, 3), np.concatenate(X_Ref_Lower), with_scale=with_scale
    )

    TX_Pred_Upper = TX_Upper.reshape(-1, NUM_POINT, 3)
    TX_Pred_Lower = TX_Lower.reshape(-1, NUM_POINT, 3)
    _TX_Pred = np.concatenate([TX_Pred_Upper, TX_Pred_Lower])

    RMSD_T_pred = metric.computeRMSD(_X_Ref, _TX_Pred)
    ASSD_T_pred = metric.computeASSD(_X_Ref, _TX_Pred)
    HD_T_pred = metric.computeHD(_X_Ref, _TX_Pred)
    CD_T_pred = metric.computeChamferDistance(_X_Ref, _TX_Pred)
    print("[RMSD] Root Mean Squared surface Distance (mm): {:.4f}".format(RMSD_T_pred))
    print("[ASSD] average symmetric surface distance (mm): {:.4f}".format(ASSD_T_pred))
    print("[HD] Hausdorff distance (mm): {:.4f}".format(HD_T_pred))
    print("[CD] Chamfer distance (mm^2): {:.4f}".format(CD_T_pred))

    Dice_VOE_lst = [
        metric.computeDiceAndVOE(_x_ref, _x_pred, pitch=0.2)
        for _x_ref, _x_pred in zip(_X_Ref, _TX_Pred)
    ]
    avg_Dice, avg_VOE = np.array(Dice_VOE_lst).mean(axis=0)
    print("[DC] Volume Dice Coefficient: {:.4f}".format(avg_Dice))
    print("[VOE] Volumetric Overlap Error: {:.2f} %".format(100.0 * avg_VOE))


def create_mesh_from_emopt_h5File(h5File, meshDir, save_name):
    with h5py.File(h5File, "r") as f:
        grp = f["EMOPT"]
        X_Pred_Upper = grp["UPPER_PRED"][:]
        X_Pred_Lower = grp["LOWER_PRED"][:]
        RELA_R = grp["RELA_R"][:]
        RELA_T = grp["RELA_T"][:]

    # UPPER_PRED/LOWER_PRED are each arch's own independent optimization
    # frame; RELA_R/RELA_T is the bite relative pose fit against the
    # frontal/lateral photo edge masks (emopt5views.updateEdgePrediction).
    # Apply it here so the exported meshes actually meet in the bite
    # position the photos show, instead of each arch's raw local frame.
    X_Pred_Lower = X_Pred_Lower @ RELA_R + RELA_T

    X_Pred_Upper_Meshes = [
        pm_util.surfaceVertices2WatertightO3dMesh(pg) for pg in X_Pred_Upper
    ]
    X_Pred_Lower_Meshes = [
        pm_util.surfaceVertices2WatertightO3dMesh(pg) for pg in X_Pred_Lower
    ]
    Pred_Upper_Mesh = pm_util.mergeO3dTriangleMeshes(X_Pred_Upper_Meshes)
    Pred_Lower_Mesh = pm_util.mergeO3dTriangleMeshes(X_Pred_Lower_Meshes)

    demoMeshDir = os.path.join(meshDir, "{}/".format(save_name))
    os.makedirs(demoMeshDir, exist_ok=True)

    pm_util.exportTriMeshObj(
        np.asarray(Pred_Upper_Mesh.vertices),
        np.asarray(Pred_Upper_Mesh.triangles),
        os.path.join(demoMeshDir, "Pred_Upper_Mesh_Tag={}.obj".format(save_name)),
    )
    pm_util.exportTriMeshObj(
        np.asarray(Pred_Lower_Mesh.vertices),
        np.asarray(Pred_Lower_Mesh.triangles),
        os.path.join(demoMeshDir, "Pred_Lower_Mesh_Tag={}.obj".format(save_name)),
    )


def build_mesh_with_retries(
    h5File, meshDir, tag, retries=8, attempt_timeout_seconds=120
):
    """Run the open3d mesh build in a throwaway subprocess, retrying on crash.

    open3d 0.16.0 Poisson reconstruction segfaults intermittently on macOS/arm64;
    isolating it means a single crash doesn't lose the completed optimization
    (already saved to h5File), we just re-run the cheap mesh step.
    """
    worker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_mesh.py")
    env = {**os.environ, "OMP_NUM_THREADS": "1"}
    outputs = [
        os.path.join(meshDir, tag, f"Pred_Upper_Mesh_Tag={tag}.obj"),
        os.path.join(meshDir, tag, f"Pred_Lower_Mesh_Tag={tag}.obj"),
    ]
    for attempt in range(1, retries + 1):
        print(f"Building mesh (attempt {attempt}/{retries})...")
        output_mtimes_before = {
            path: os.path.getmtime(path) if os.path.exists(path) else None
            for path in outputs
        }
        try:
            result = subprocess.run(
                [sys.executable, worker, h5File, meshDir, tag],
                env=env,
                timeout=attempt_timeout_seconds,
                check=False,
            )
            rc = result.returncode
            reason = f"exited with code {rc}" if rc != 0 else "exited 0 but wrote no .obj"
        except subprocess.TimeoutExpired:
            rc = None
            reason = f"timed out after {attempt_timeout_seconds}s"
        # open3d can exit 0 yet write nothing (Poisson "failed to close loop"),
        # so verify the .obj files actually exist before declaring success.
        fresh_outputs = all(
            os.path.exists(path)
            and (
                output_mtimes_before[path] is None
                or os.path.getmtime(path) > output_mtimes_before[path]
            )
            for path in outputs
        )
        if rc == 0 and fresh_outputs:
            print("Mesh build succeeded.")
            return
        print(f"Mesh build {reason}; retrying.")
    raise RuntimeError(f"Mesh build failed after {retries} attempts")


def validate_lidar_milestone_ceiling(engine: str, lidar_max_milestone: int) -> None:
    if lidar_max_milestone not in (6, 7):
        raise ValueError("lidar_max_milestone must be 6 or 7")
    if engine != "lidar" and lidar_max_milestone != 7:
        raise ValueError("--lidar-max-milestone 6 requires --engine lidar")


def resolve_reconstruction_image_path(
    *, output_tag: str, photo_value: int, image_source_tag: str = None
) -> str:
    source_tag = image_source_tag or output_tag
    matches = glob.glob(os.path.join(PHOTO_DIR, f"{source_tag}-{photo_value}.png"))
    if len(matches) != 1:
        raise FileNotFoundError(
            f"Expected one reconstruction image for {source_tag}-{photo_value}.png, "
            f"found {len(matches)}"
        )
    return matches[0]


def configure_reconstruction_random_seed(seed: int = None) -> None:
    if seed is not None:
        np.random.seed(seed)


def main(
    tag="0",
    edge_backend=None,
    num_pc=NUM_PC,
    shape_regularization=1.0,
    edge_mask_source_tag=None,
    engine="baseline",
    lidar_capture_tag=None,
    lidar_max_milestone=7,
    image_source_tag=None,
    random_seed=None,
):
    # Which reconstruction engine class to use — kept as a local import (not
    # a module-level one) so "lidar" only ever loads emopt5views_lidar.py,
    # the fork the Take-5-Pictures LiDAR trial-and-error happens in, and
    # never touches emopt5views.py (used by Upload 5 Photos).
    if engine == "lidar":
        from emopt5views_lidar import EMOpt5Views
    elif engine == "baseline":
        from emopt5views import EMOpt5Views
    else:
        raise ValueError(f"Unknown engine: {engine!r}")
    validate_lidar_milestone_ceiling(engine, lidar_max_milestone)
    configure_reconstruction_random_seed(random_seed)

    edge_backend = resolve_edge_backend(edge_backend)
    if num_pc <= 0:
        raise ValueError("num_pc must be positive")
    if shape_regularization < 0:
        raise ValueError("shape_regularization must be non-negative")
    Mu, SqrtEigVals, Sigma = loadMuEigValSigma(SSM_DIR, numPC=num_pc)
    if SqrtEigVals.shape[-1] != num_pc:
        raise ValueError(
            f"Requested {num_pc} PCA components, but the SSM only provides "
            f"{SqrtEigVals.shape[-1]}"
        )
    Mu_normals = EMOpt5Views.computePointNormals(Mu)

    transVecStd = 1.1463183505325343  # obtained by SSM
    rotVecStd = 0.13909168140778128  # obtained by SSM
    PoseCovMats = np.load(
        os.path.join(REGIS_PARAM_DIR, "PoseCovMats.npy")
    )  # Covariance matrix of tooth pose for each tooth, shape=(28,6,6)
    ScaleCovMat = np.load(
        os.path.join(REGIS_PARAM_DIR, "ScaleCovMat.npy")
    )  # Covariance matrix of scales for each tooth, shape=(28,28)

    tooth_exist_mask = TOOTH_EXIST_MASK[tag]
    LogFile = os.path.join(TEMP_DIR, "Tag={}.log".format(tag))
    if os.path.exists(LogFile):
        os.remove(LogFile)
    # Line buffered so server.py's /progress endpoint can read stage markers
    # while the run is still going, instead of after an 8KB block flushes.
    log = open(LogFile, "a", encoding="utf-8", buffering=1)
    _orig_stdout = sys.stdout
    sys.stdout = log

    # teeth boundary in each photo: use a hand-edited mask if one exists in
    # ./demo/edge_masks/<tag>/, otherwise use the selected automatic backend.
    print(f"Requested edge-mask backend: {edge_backend}")
    print(f"SSM PCA components: {num_pc}")
    print(f"Shape regularization: {shape_regularization}")
    predictions_by_photo = {}
    automatic_inputs = []
    image_files_by_photo = {}
    # Computed masks are otherwise only held in memory for this process and
    # never written anywhere; save them here so callers (server.py) can read
    # back what was actually used to build the model.
    edge_mask_out_dir = os.path.join(TEMP_DIR, "edge_masks", tag)
    os.makedirs(edge_mask_out_dir, exist_ok=True)
    for phtype in PHOTO_TYPES:
        imgfile = resolve_reconstruction_image_path(
            output_tag=tag,
            photo_value=phtype.value,
            image_source_tag=image_source_tag,
        )
        image_files_by_photo[phtype] = imgfile
        if edge_mask_source_tag is not None:
            maskfile = os.path.join(
                TEMP_DIR,
                "edge_masks",
                edge_mask_source_tag,
                f"{edge_mask_source_tag}-{phtype.value}.png",
            )
            if not os.path.exists(maskfile):
                raise FileNotFoundError(f"Reusable edge mask not found: {maskfile}")
        else:
            maskfile = os.path.join(EDGE_MASK_DIR, tag, f"{tag}-{phtype.value}.png")
        if os.path.exists(maskfile):
            edge_mask = load_edge_mask(maskfile, imgfile)
            source = "reused" if edge_mask_source_tag is not None else "hand-edited"
            predictions_by_photo[phtype] = EdgePrediction(
                edge_mask=edge_mask,
                source=source,
            )
            print(f"Using {source} edge mask: {maskfile}")
        else:
            automatic_inputs.append((phtype, imgfile))

    def predict_h5(image_paths):
        weight_ckpt = r"./seg/weights/weights-teeth-boundary-model.h5"
        model = ASPP_UNet(IMG_SHAPE, filters=[16, 32, 64, 128, 256])
        model.load_weights(weight_ckpt)
        return [
            predict_teeth_contour(model, imgfile, resized_width=RECONS_IMG_WIDTH)
            for imgfile in image_paths
        ]

    automatic_predictions, fallback_reasons = predict_automatic_edge_predictions(
        automatic_inputs,
        edge_backend,
        RFDETR_PHOTO_VALUES,
        lambda image_paths: predict_rfdetr_predictions(
            image_paths, resized_width=RECONS_IMG_WIDTH
        ),
        predict_h5,
    )
    predictions_by_photo.update(automatic_predictions)
    for phtype, reason in fallback_reasons.items():
        print(f"RF-DETR unavailable for {phtype}; falling back to .h5: {reason}")
    for phtype, imgfile in automatic_inputs:
        prediction = predictions_by_photo[phtype]
        print(f"{prediction.source} predicted edge mask for: {imgfile}")

    artifact_views = {}
    for phtype in PHOTO_TYPES:
        prediction = predictions_by_photo[phtype]
        artifact_views[phtype.value] = {
            "prediction": prediction,
            "sourceImage": image_files_by_photo[phtype],
            "checkpoint": phtype.name.lower(),
            "keyframe": None,
            "fallbackReason": fallback_reasons.get(phtype),
        }
    write_instance_bundle(Path(INSTANCE_MASK_DIR) / tag, tag, artifact_views)

    edgeMasks = []
    for phtype in PHOTO_TYPES:
        edge_mask = predictions_by_photo[phtype].edge_mask
        edgeMasks.append(edge_mask)
        skimage.io.imsave(
            os.path.join(edge_mask_out_dir, f"{tag}-{phtype.value}.png"), edge_mask
        )

    # del model # to release memory

    # run deformation-based 3d reconstruction
    emopt = EMOpt5Views(
        edgeMasks,
        PHOTO_TYPES,
        VISIBLE_MASKS,
        tooth_exist_mask,
        Mu,
        Mu_normals,
        SqrtEigVals,
        Sigma,
        PoseCovMats,
        ScaleCovMat,
        transVecStd,
        rotVecStd,
        shape_regularization=shape_regularization,
    )
    if engine == "lidar":
        # Kept inside the LiDAR engine branch so Upload 5 Photos never reads a
        # capture cloud.  An absent/ineligible capture simply leaves the
        # optimizer on its existing photo-only parameter path.
        from seg.lidar_ssm_constraints import (
            LiDARConstraintConfiguration,
            estimate_lidar_seeded_view_depths,
            load_lidar_view_constraints,
        )
        from seg.lidar_tooth_pose_constraints import load_lidar_tooth_pose_constraints

        constraints, skipped = ({}, {})
        if lidar_capture_tag:
            constraints, skipped = load_lidar_view_constraints(
                Path("seg/valid/lidar"), lidar_capture_tag, LiDARConstraintConfiguration()
            )
        emopt.set_lidar_constraints(constraints, skipped)
        # Photo-only reconstruction has no absolute depth signal, so its
        # hardcoded 70/120mm initial camera depth is often 55-100mm off the
        # real distance (monocular depth ambiguity). Seed it from the real
        # LiDAR median before grid search/optimization runs, rather than
        # only correcting a wrong-by-construction pose afterward via the
        # (tight-gated) coarse LiDAR alignment below.
        seeded_depths = estimate_lidar_seeded_view_depths(constraints)
        for photo_index, depth_ssm_units in seeded_depths.items():
            emopt.ex_txyz_default[PHOTO(photo_index)][2] = depth_ssm_units
        print(
            "LiDAR camera-depth seeding: "
            + json.dumps({str(k): v for k, v in seeded_depths.items()}, sort_keys=True)
        )
        tooth_pose_constraints, tooth_pose_skipped = ({}, {})
        if lidar_capture_tag and constraints:
            tooth_pose_constraints, tooth_pose_skipped = load_lidar_tooth_pose_constraints(
                Path("seg/valid/lidar"), lidar_capture_tag, np.flatnonzero(tooth_exist_mask)
            )
            eligible_fields = {constraint.field for constraint in constraints.values()}
            tooth_pose_constraints = {
                tooth_index: tuple(
                    constraint for constraint in values if constraint.field in eligible_fields
                )
                for tooth_index, values in tooth_pose_constraints.items()
            }
            tooth_pose_constraints = {
                tooth_index: values for tooth_index, values in tooth_pose_constraints.items() if len(values) >= 2
            }
        emopt.set_lidar_tooth_pose_constraints(tooth_pose_constraints, tooth_pose_skipped)
        print("LiDAR constraint diagnostics: " + json.dumps(emopt.lidar_diagnostics, sort_keys=True))
        print("LiDAR tooth-pose diagnostics: " + json.dumps(emopt.lidar_tooth_pose_diagnostics, sort_keys=True))
    emopt = run_emopt(
        emopt,
        enable_m7_shape_experiment=(lidar_max_milestone >= 7),
    )
    if engine == "lidar":
        emopt.finalize_lidar_tooth_pose_diagnostics()
        emopt.update_lidar_tooth_shape_diagnostics()
        if emopt.lidar_tooth_shape_constraints:
            emopt.compute_lidar_tooth_shape_loss_and_gradient(
                emopt.featureVec,
                {"featureVec": 0},
                emopt.numTooth * emopt.numPC,
                stage=3,
            )
        print(
            "LiDAR tooth-shape diagnostics: "
            + json.dumps(emopt.lidar_tooth_shape_diagnostics, sort_keys=True)
        )
        persist_lidar_diagnostic_json(
            Path(LIDAR_DIAGNOSTIC_DIR),
            tag,
            build_lidar_diagnostic_payload(
                emopt.lidar_diagnostics,
                emopt.lidar_tooth_pose_diagnostics,
                emopt.lidar_tooth_shape_diagnostics,
            ),
        )
    demoh5File = os.path.join(
        RECONSTRUCTION_DATA_DIR, f"demo-tag={tag}.h5"
    )
    emopt.saveDemo2H5(demoh5File)

    # Reprojected-edge overlay for alignment QA: where the fitted 3D teeth
    # (bite-registered via RELA_R/RELA_T, now fit against all 5 views
    # including the occlusal UPPER/LOWER photos) actually land in each
    # photo's own pixel space, saved alongside the ground-truth edge mask so
    # a client can overlay it on the real photo and visually confirm the
    # reconstruction matches what the photo shows.
    bite_registration_qa = {}
    for phtype in (PHOTO.UPPER, PHOTO.LOWER, PHOTO.FRONTAL, PHOTO.LEFT, PHOTO.RIGHT):
        predicted_mask = emopt.renderPredictedEdgeMask(phtype)
        skimage.io.imsave(
            os.path.join(edge_mask_out_dir, f"{tag}-{phtype.value}-predicted.png"),
            predicted_mask,
        )
        bite_registration_qa[phtype.value] = float(
            emopt.loss_expectation_step[phtype.value]
        )
    with open(
        os.path.join(edge_mask_out_dir, f"{tag}-bite-registration-qa.json"), "w"
    ) as f:
        json.dump(bite_registration_qa, f, sort_keys=True)

    sys.stdout = _orig_stdout  # restore console before the (retrying) mesh build
    log.close()

    # open3d Poisson mesh build runs in a retrying subprocess (see the function);
    # this is why create_mesh_from_emopt_h5File above is no longer called directly.
    build_mesh_with_retries(demoh5File, DEMO_MESH_DIR, tag)
    colorize_reconstructed_meshes(
        demoh5File,
        DEMO_MESH_DIR,
        tag,
        photo_source_tag=image_source_tag,
    )


def build_argument_parser():
    parser = argparse.ArgumentParser(description="Reconstruct teeth from five photos.")
    parser.add_argument("tag", nargs="?", default="5", help="patient/photo tag")
    parser.add_argument(
        "--edge-backend",
        choices=EDGE_BACKENDS,
        default=None,
        help="automatic edge-mask backend (default: SMARTEE_EDGE_BACKEND or h5)",
    )
    parser.add_argument(
        "--num-pc",
        type=int,
        default=NUM_PC,
        help=f"number of SSM PCA shape components (default: {NUM_PC})",
    )
    parser.add_argument(
        "--shape-regularization",
        type=float,
        default=1.0,
        help="penalty on standardized SSM shape coefficients (default: 1.0)",
    )
    parser.add_argument(
        "--edge-mask-source-tag",
        default=None,
        help="reuse computed edge masks from another tag for a controlled comparison",
    )
    parser.add_argument(
        "--image-source-tag",
        default=None,
        help="reuse the exact five input PNGs from another tag for a controlled comparison",
    )
    parser.add_argument(
        "--engine",
        choices=["baseline", "lidar"],
        default="baseline",
        help="reconstruction engine: 'baseline' (emopt5views.py) or 'lidar' (emopt5views_lidar.py)",
    )
    parser.add_argument(
        "--lidar-capture-tag",
        default=None,
        help="persisted Figure-8 capture tag used only by the lidar engine",
    )
    parser.add_argument(
        "--lidar-max-milestone",
        type=int,
        choices=(6, 7),
        default=7,
        help="validation ceiling for the LiDAR engine (default: 7)",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=None,
        help="fix optimizer initialization for a reproducible controlled comparison",
    )
    return parser


def execute_reconstruction_cli(args) -> int:
    original_stdout = sys.stdout
    edge_backend = resolve_edge_backend(args.edge_backend)
    print("\n" + "="*70)
    print("🦷 3D TEETH RECONSTRUCTION - STARTING")
    print("="*70 + "\n")

    # Ray no longer used for parallel processing (bypassed to fix segfault on macOS arm64)
    exit_code = 0
    ray.init(num_cpus=1, num_gpus=0, ignore_reinit_error=True)
    # ponytail: tag now comes from argv (server.py invokes `python main.py <tag>`
    # per request) with the old hardcoded value as the default for manual runs.
    tag = args.tag

    print(f"Processing Patient ID: {tag}")
    print(f"Input images: seg/valid/image/{tag}-*.png")
    print(f"Edge-mask backend: {edge_backend}")
    print(f"SSM PCA components: {args.num_pc}")
    print(f"Shape regularization: {args.shape_regularization}")
    print(f"Output folder: demo/mesh/{tag}/\n")

    try:
        main(
            tag,
            edge_backend=edge_backend,
            num_pc=args.num_pc,
            shape_regularization=args.shape_regularization,
            edge_mask_source_tag=args.edge_mask_source_tag,
            image_source_tag=args.image_source_tag,
            engine=args.engine,
            lidar_capture_tag=args.lidar_capture_tag,
            lidar_max_milestone=args.lidar_max_milestone,
            random_seed=args.random_seed,
        )

        print("\n" + "="*70)
        print("✅ 3D RECONSTRUCTION COMPLETE!")
        print("="*70)
        print(f"\n📁 Results saved to: demo/mesh/{tag}/")
        print(f"   - Pred_Upper_Mesh_Tag={tag}.obj")
        print(f"   - Pred_Lower_Mesh_Tag={tag}.obj")
        print("\n🎉 DONE! You can now view the 3D models.\n")
    except Exception as e:
        exit_code = 1
        if sys.stdout is not original_stdout:
            redirected_stdout = sys.stdout
            sys.stdout = original_stdout
            redirected_stdout.close()
        print(f"\n❌ Error occurred: {e}")
        print(f"Check log file: demo/_temp/Tag={tag}.log")
    finally:
        sys.stdout = original_stdout
        ray.shutdown()
    return exit_code


if __name__ == "__main__":
    parser = build_argument_parser()
    args = parser.parse_args()
    try:
        validate_lidar_milestone_ceiling(args.engine, args.lidar_max_milestone)
    except ValueError as error:
        parser.error(str(error))
    sys.exit(execute_reconstruction_cli(args))
