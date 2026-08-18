"""Strict loading and robust metric residuals for the LiDAR-only SSM engine.

The functions in this module deliberately have no EM or Flask dependency.  That
makes the capture-quality gate independently testable and prevents depth data
from reaching the upload-only reconstruction path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
from scipy.spatial import cKDTree


FIELD_TO_PHOTO_INDEX = {
    "maxillary": 0,
    "mandibular": 1,
    "leftLateral": 2,
    "rightLateral": 3,
    "front": 4,
}
DIRECT_FIELDS = ("mandibular", "leftLateral", "rightLateral", "front")


@dataclass(frozen=True)
class LiDARConstraintConfiguration:
    minimum_voxel_count: int = 500
    minimum_keyframe_count: int = 3
    metres_per_ssm_unit_initial: float = 0.001
    metres_per_ssm_unit_bounds: Tuple[float, float] = (0.0005, 0.0015)
    huber_delta_metres: float = 0.004
    correspondence_gate_metres: float = 0.012
    minimum_bootstrap_pair_count: int = 100
    maximum_bootstrap_translation_metres: float = 0.25
    maximum_bootstrap_rotation_radians: float = 0.785398  # 45 degrees
    weight: float = 0.05


@dataclass(frozen=True)
class LiDARViewConstraint:
    photo_index: int
    field: str
    points_k0_metres: np.ndarray
    contributing_keyframes: Tuple[str, ...]
    configuration: LiDARConstraintConfiguration


@dataclass(frozen=True)
class FixedLiDARCorrespondences:
    model_indices: np.ndarray
    lidar_indices: np.ndarray


@dataclass(frozen=True)
class LiDARBootstrapTranslation:
    translation_metres: np.ndarray
    model_median_metres: np.ndarray
    lidar_median_metres: np.ndarray


@dataclass(frozen=True)
class LiDARBootstrapRigidTransform:
    rotation: np.ndarray  # (3, 3)
    translation_metres: np.ndarray  # (3,)
    pair_count: int


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _metadata_is_eligible(metadata: dict) -> bool:
    return (
        metadata.get("schemaVersion") == 4
        and metadata.get("isDirectView") is True
        and metadata.get("ssmDepthEligible") is True
        and metadata.get("trackingState") == "normal"
        and metadata.get("matrixLayout") == "column-major"
        and metadata.get("coordinateSystem") == "ARKit camera-to-world"
        and isinstance(metadata.get("cameraToReferenceTransform"), list)
        and len(metadata["cameraToReferenceTransform"]) == 16
    )


def _contributing_keyframes(payload: dict) -> Tuple[str, ...] | None:
    per_keyframe = payload.get("perKeyframe")
    if not isinstance(per_keyframe, dict):
        return None
    accepted = []
    for keyframe_id, summary in per_keyframe.items():
        if not isinstance(summary, dict):
            return None
        count = summary.get("acceptedPointCount")
        if not isinstance(count, int) or count < 0:
            return None
        if count > 0:
            accepted.append(str(keyframe_id))
    return tuple(sorted(accepted))


def _load_one_constraint(
    view_directory: Path,
    field: str,
    configuration: LiDARConstraintConfiguration,
) -> tuple[LiDARViewConstraint | None, str | None]:
    json_path = view_directory / "dental_cloud.json"
    npz_path = view_directory / "dental_cloud.npz"
    if not json_path.is_file():
        return None, "missing_cloud"
    payload = _read_json(json_path)
    if payload is None or payload.get("schemaVersion") != 1:
        return None, "malformed_cloud"
    point_count = payload.get("pointCount")
    contributing = _contributing_keyframes(payload)
    if not isinstance(point_count, int) or point_count < 0 or contributing is None:
        return None, "malformed_cloud"

    # Check metadata before opening NPZ: a mirror/non-normal capture must never
    # become usable merely because it happens to contain plausible coordinates.
    metadata = []
    for keyframe_id in contributing:
        item = _read_json(view_directory / f"{keyframe_id}.metadata.json")
        if item is None:
            return None, "invalid_keyframe_metadata"
        metadata.append(item)
    if any(not _metadata_is_eligible(item) for item in metadata):
        return None, "mirror_or_ineligible_view"
    if len(contributing) < configuration.minimum_keyframe_count or "K0" not in contributing:
        return None, "insufficient_multiview_coverage"
    if point_count < configuration.minimum_voxel_count:
        return None, "insufficient_points"
    if not npz_path.is_file():
        return None, "missing_cloud"

    try:
        with np.load(npz_path, allow_pickle=False) as cloud:
            points = np.asarray(cloud["pointK0"], dtype=np.float64)
    except (OSError, KeyError, TypeError, ValueError):
        return None, "malformed_cloud"
    if points.ndim != 2 or points.shape[1:] != (3,) or len(points) != point_count:
        return None, "malformed_cloud"
    if not np.isfinite(points).all():
        return None, "malformed_cloud"
    return LiDARViewConstraint(
        photo_index=FIELD_TO_PHOTO_INDEX[field],
        field=field,
        points_k0_metres=points,
        contributing_keyframes=contributing,
        configuration=configuration,
    ), None


def load_lidar_view_constraints(
    lidar_root: Path,
    capture_tag: str,
    configuration: LiDARConstraintConfiguration = LiDARConstraintConfiguration(),
) -> tuple[Dict[int, LiDARViewConstraint], Dict[str, str]]:
    """Load only independently eligible direct K0-space clouds.

    Results remain keyed by reconstruction photo index, but no coordinates are
    ever fused or transformed across fields here.
    """

    constraints: Dict[int, LiDARViewConstraint] = {}
    skipped: Dict[str, str] = {}
    root = Path(lidar_root) / capture_tag
    for field in DIRECT_FIELDS:
        view_directory = root / field
        if not view_directory.is_dir():
            continue
        constraint, reason = _load_one_constraint(view_directory, field, configuration)
        if constraint is None:
            skipped[field] = reason or "malformed_cloud"
        else:
            constraints[constraint.photo_index] = constraint
    return constraints, skipped


def arkit_points_from_em_camera(
    em_camera_points: np.ndarray, metres_per_ssm_unit: float
) -> np.ndarray:
    """Convert EM camera millimetres to ARKit camera metres."""

    points = np.asarray(em_camera_points, dtype=np.float64)
    scale = float(metres_per_ssm_unit)
    if points.ndim != 2 or points.shape[1:] != (3,) or not np.isfinite(points).all():
        raise ValueError("em_camera_points must be a finite (N, 3) array")
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("metres_per_ssm_unit must be finite and positive")
    return points * np.array([1.0, -1.0, -1.0]) * scale


def estimate_correspondence_bootstrap_translation(
    em_camera_points: np.ndarray,
    lidar_points_metres: np.ndarray,
    metres_per_ssm_unit: float,
    maximum_translation_metres: float = 0.25,
) -> LiDARBootstrapTranslation | None:
    """Estimate a robust query-only translation between model and cloud medians."""

    try:
        model = arkit_points_from_em_camera(em_camera_points, metres_per_ssm_unit)
        lidar = np.asarray(lidar_points_metres, dtype=np.float64)
        maximum = float(maximum_translation_metres)
    except (TypeError, ValueError):
        return None
    if (
        len(model) == 0
        or lidar.ndim != 2
        or lidar.shape[1:] != (3,)
        or len(lidar) == 0
        or not np.isfinite(lidar).all()
        or not np.isfinite(maximum)
        or maximum <= 0
    ):
        return None
    model_median = np.median(model, axis=0)
    lidar_median = np.median(lidar, axis=0)
    translation = lidar_median - model_median
    if not np.isfinite(translation).all() or np.linalg.norm(translation) > maximum:
        return None
    return LiDARBootstrapTranslation(
        translation_metres=translation,
        model_median_metres=model_median,
        lidar_median_metres=lidar_median,
    )


def estimate_lidar_seeded_view_depths(
    constraints: Dict[int, "LiDARViewConstraint"],
    minimum_point_count: int = 30,
    plausible_range_ssm_units: Tuple[float, float] = (30.0, 200.0),
) -> Dict[int, float]:
    """Robust per-view camera depth (SSM/mm units) from raw K0 LiDAR points.

    The optimizer's hardcoded initial depth (70/120mm) is a guess unrelated
    to how any given capture was actually taken; a wrong guess there is why
    photo-only reconstruction converges 55-100mm off in depth even though
    lateral position is fine. Seeding from the real LiDAR median instead
    gives the optimizer a starting point close to the truth. Out-of-range or
    sparse views are omitted (not clamped) so the caller keeps the existing
    hardcoded default for that view rather than trusting a bad guess.
    """

    seeded = {}
    for photo_index, constraint in constraints.items():
        points = np.asarray(constraint.points_k0_metres, dtype=np.float64)
        if len(points) < minimum_point_count:
            continue
        median_z_metres = float(np.median(points[:, 2]))
        scale = float(constraint.configuration.metres_per_ssm_unit_initial)
        if not np.isfinite(median_z_metres) or not np.isfinite(scale) or scale <= 0:
            continue
        # Inverse of arkit_points_from_em_camera's `* [1, -1, -1] * scale`.
        depth_ssm_units = -median_z_metres / scale
        low, high = plausible_range_ssm_units
        if not low <= depth_ssm_units <= high:
            continue
        seeded[int(photo_index)] = depth_ssm_units
    return seeded


def kabsch_rigid_transform(
    model_points: np.ndarray, target_points: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Closed-form optimal rotation+translation minimizing sum |R@P_i + t - Q_i|^2."""

    model = np.asarray(model_points, dtype=np.float64)
    target = np.asarray(target_points, dtype=np.float64)
    model_centroid = model.mean(axis=0)
    target_centroid = target.mean(axis=0)
    covariance = (model - model_centroid).T @ (target - target_centroid)
    u, _, vt = np.linalg.svd(covariance)
    reflection = np.sign(np.linalg.det(vt.T @ u.T)) or 1.0
    rotation = vt.T @ np.diag([1.0, 1.0, reflection]) @ u.T
    translation = target_centroid - rotation @ model_centroid
    return rotation, translation


def estimate_correspondence_bootstrap_rigid_transform(
    em_camera_points: np.ndarray,
    lidar_points_metres: np.ndarray,
    metres_per_ssm_unit: float,
    configuration: LiDARConstraintConfiguration,
    bootstrap_gate_metres: float = 0.030,
    max_iterations: int = 4,
    trim_fraction: float = 0.7,
) -> LiDARBootstrapRigidTransform | None:
    """Trimmed coarse ICP: seed with the median-translation guess, then
    alternate nearest-neighbour matching at `bootstrap_gate_metres` (looser
    than the final `correspondence_gate_metres` safety filter used
    downstream) with a Kabsch rigid-transform refit computed on only the
    closest `trim_fraction` of in-gate matches each round.

    The trim step matters: the median-based translation-only bootstrap this
    complements is deliberately robust to outlier/incorrect correspondences.
    Plain (untrimmed) Kabsch is not — with rotation as an extra free
    parameter, it can fit noise in a handful of wrong matches instead of the
    true correction. Discarding the worst-residual fraction each iteration
    (standard "trimmed ICP") restores that robustness.
    """

    seed = estimate_correspondence_bootstrap_translation(
        em_camera_points,
        lidar_points_metres,
        metres_per_ssm_unit,
        configuration.maximum_bootstrap_translation_metres,
    )
    if seed is None:
        return None
    try:
        model = arkit_points_from_em_camera(em_camera_points, metres_per_ssm_unit)
        lidar = np.asarray(lidar_points_metres, dtype=np.float64)
        gate = float(bootstrap_gate_metres)
        trim = float(trim_fraction)
    except (TypeError, ValueError):
        return None
    if (
        not np.isfinite(gate) or gate <= 0
        or int(max_iterations) <= 0
        or not np.isfinite(trim) or not (0.0 < trim <= 1.0)
    ):
        return None

    rotation = np.eye(3)
    translation = seed.translation_metres
    lidar_tree = cKDTree(lidar)
    pair_count = 0
    for _ in range(int(max_iterations)):
        transformed = model @ rotation.T + translation
        distances, lidar_indices = lidar_tree.query(transformed, k=1)
        accepted = np.flatnonzero(distances <= gate)
        pair_count = int(len(accepted))
        if pair_count < configuration.minimum_bootstrap_pair_count:
            return None
        trimmed_count = max(
            configuration.minimum_bootstrap_pair_count, int(pair_count * trim)
        )
        closest_first = accepted[np.argsort(distances[accepted])]
        fit_indices = closest_first[:trimmed_count]
        rotation, translation = kabsch_rigid_transform(
            model[fit_indices], lidar[lidar_indices[fit_indices]]
        )

    if not np.isfinite(rotation).all() or not np.isfinite(translation).all():
        return None
    if np.linalg.norm(translation) > configuration.maximum_bootstrap_translation_metres:
        return None
    rotation_angle = np.arccos(np.clip((np.trace(rotation) - 1.0) / 2.0, -1.0, 1.0))
    if not np.isfinite(rotation_angle) or rotation_angle > configuration.maximum_bootstrap_rotation_radians:
        return None
    return LiDARBootstrapRigidTransform(
        rotation=rotation,
        translation_metres=translation,
        pair_count=pair_count,
    )


def build_fixed_correspondences(
    em_camera_points: np.ndarray,
    constraint: LiDARViewConstraint,
    metres_per_ssm_unit: float,
    query_translation_metres: np.ndarray | None = None,
    query_rotation: np.ndarray | None = None,
) -> FixedLiDARCorrespondences:
    """Nearest cloud matches within the configured gate, frozen for an M-step.

    `query_rotation` (if given) is applied before `query_translation_metres`,
    i.e. the query points searched are `aligned @ query_rotation.T +
    query_translation_metres`. Omitting `query_rotation` reproduces the
    original translation-only behaviour exactly (identity rotation).
    """

    aligned = arkit_points_from_em_camera(em_camera_points, metres_per_ssm_unit)
    if len(aligned) == 0 or len(constraint.points_k0_metres) == 0:
        empty = np.empty(0, dtype=np.intp)
        return FixedLiDARCorrespondences(empty, empty)
    query_points = aligned
    if query_rotation is not None:
        rotation = np.asarray(query_rotation, dtype=np.float64)
        if rotation.shape != (3, 3) or not np.isfinite(rotation).all():
            raise ValueError("query_rotation must be a finite (3, 3) matrix")
        query_points = query_points @ rotation.T
    if query_translation_metres is not None:
        translation = np.asarray(query_translation_metres, dtype=np.float64)
        if translation.shape != (3,) or not np.isfinite(translation).all():
            raise ValueError("query_translation_metres must be a finite 3-vector")
        query_points = query_points + translation
    distances, lidar_indices = cKDTree(constraint.points_k0_metres).query(query_points, k=1)
    accepted = np.flatnonzero(distances <= constraint.configuration.correspondence_gate_metres)
    return FixedLiDARCorrespondences(
        model_indices=accepted.astype(np.intp, copy=False),
        lidar_indices=np.asarray(lidar_indices[accepted], dtype=np.intp),
    )


def huber_point_to_surface_loss(
    aligned_model_points_metres: np.ndarray,
    lidar_points_metres: np.ndarray,
    delta_metres: float,
) -> tuple[float, np.ndarray]:
    """Mean Huber residual and its analytic point-coordinate gradient."""

    model = np.asarray(aligned_model_points_metres, dtype=np.float64)
    lidar = np.asarray(lidar_points_metres, dtype=np.float64)
    delta = float(delta_metres)
    if model.ndim != 2 or model.shape[1:] != (3,) or model.shape != lidar.shape:
        raise ValueError("model and LiDAR points must have matching (N, 3) shapes")
    if not np.isfinite(model).all() or not np.isfinite(lidar).all() or not np.isfinite(delta) or delta <= 0:
        raise ValueError("points and delta must be finite; delta must be positive")
    gradient = np.zeros_like(model)
    if len(model) == 0:
        return 0.0, gradient
    residual = model - lidar
    distance = np.linalg.norm(residual, axis=1)
    quadratic = distance <= delta
    losses = np.where(quadratic, 0.5 * distance**2, delta * (distance - 0.5 * delta))
    nonzero = distance > 0
    scale = np.zeros_like(distance)
    scale[quadratic] = 1.0
    scale[~quadratic & nonzero] = delta / distance[~quadratic & nonzero]
    gradient = residual * scale[:, None] / len(model)
    return float(np.mean(losses)), gradient
