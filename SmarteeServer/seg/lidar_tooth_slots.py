"""Conservative mapping from LiDAR keyframe masks to original SSM tooth slots."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy.spatial import cKDTree

from const import VISIBLE_MASKS


@dataclass(frozen=True)
class LiDARSlotConfiguration:
    minimum_detector_confidence: float = 0.80
    minimum_assignment_confidence: float = 0.80
    # Loosened from 0.08/3.0 after real captures showed a legitimate row
    # split (0.0615 gap, 1.17x dominance) rejected outright by one stray
    # near-midline detection sitting between two otherwise-clean arch rows.
    # This trades away most of the anti-ambiguity margin — a real risk of
    # mislabeling a tooth's arch row, accepted deliberately since unlike
    # M5's gate there's no downstream check that catches a bad split.
    minimum_arch_row_gap: float = 0.05
    minimum_arch_row_gap_dominance: float = 1.15


@dataclass(frozen=True)
class K0SlotPropagationConfiguration:
    minimum_detector_confidence: float = 0.80
    minimum_depth_confidence: int = 2
    minimum_point_count: int = 15
    maximum_median_distance_metres: float = 0.005
    overlap_distance_metres: float = 0.005
    minimum_overlap_fraction: float = 0.50
    maximum_uniqueness_ratio: float = 0.75


def slot_id_for_original_index(index: int) -> str:
    index = int(index)
    if not 0 <= index < 28:
        raise ValueError("original tooth index must be in [0, 27]")
    return f"{'U' if index < 14 else 'L'}-{(index % 14) + 1:02d}"


def _screen_ordered_candidates(candidates: np.ndarray) -> np.ndarray:
    """Order original SSM slots from image left to image right."""

    candidates = np.asarray(candidates, dtype=np.intp)
    upper = set(int(value) for value in candidates if int(value) < 14)
    lower = set(int(value) for value in candidates if int(value) >= 14)
    # The SSM stores each arch as two centre-to-posterior halves rather than
    # one screen-left-to-right sequence. Lower uses the opposite first half.
    upper_order = list(range(6, -1, -1)) + list(range(7, 14))
    lower_order = list(range(14, 21)) + list(range(27, 20, -1))
    ordered = [value for value in upper_order if value in upper]
    ordered.extend(value for value in lower_order if value in lower)
    return np.asarray(ordered, dtype=np.intp)


def _centroid(instance: dict) -> tuple[float, float]:
    value = instance.get("normalizedCentroidXY")
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError("instance is missing normalizedCentroidXY")
    x, y = float(value[0]), float(value[1])
    if not np.isfinite([x, y]).all() or not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
        raise ValueError("instance normalizedCentroidXY must be finite and within [0, 1]")
    return x, y


def _instance_id(instance: dict) -> str:
    value = instance.get("localId")
    if value is None or not str(value):
        raise ValueError("instance is missing localId")
    return str(value)


def _propagation_point(record: dict) -> tuple[np.ndarray, float, int] | None:
    if record.get("rejectionReason") is not None:
        return None
    try:
        detector_confidence = float(record["detectorConfidence"])
        depth_confidence = int(record["depthConfidence"])
        point = np.asarray(record["pointK0"], dtype=np.float64)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if (
        not np.isfinite(detector_confidence)
        or point.shape != (3,)
        or not np.isfinite(point).all()
    ):
        return None
    return point, detector_confidence, depth_confidence


def _is_unique_best(best: float, competing: Sequence[float], maximum_ratio: float) -> bool:
    if not competing:
        return True
    second = min(float(value) for value in competing)
    return best <= maximum_ratio * second


def propagate_k0_slots(
    records: Sequence[dict],
    k0_assignments: dict[str, str],
    configuration: K0SlotPropagationConfiguration = K0SlotPropagationConfiguration(),
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, dict[str, object]]]]:
    """Propagate authoritative K0 slots through unique metric surface overlap."""

    grouped = defaultdict(list)
    observed_instances = defaultdict(set)
    for record in records:
        keyframe_id = str(record.get("keyframeID", ""))
        instance_id = str(record.get("instanceID", ""))
        if not keyframe_id or not instance_id:
            continue
        observed_instances[keyframe_id].add(instance_id)
        parsed = _propagation_point(record)
        if parsed is None:
            continue
        point, detector_confidence, depth_confidence = parsed
        if (
            detector_confidence >= configuration.minimum_detector_confidence
            and depth_confidence >= configuration.minimum_depth_confidence
        ):
            grouped[(keyframe_id, instance_id)].append(point)

    assignments = {keyframe_id: {} for keyframe_id in sorted(observed_instances)}
    diagnostics = {keyframe_id: {} for keyframe_id in sorted(observed_instances)}
    assignments.setdefault("K0", {})
    diagnostics.setdefault("K0", {})

    anchor_points = {}
    for instance_id, slot_id in sorted(k0_assignments.items()):
        if instance_id not in observed_instances.get("K0", set()):
            continue
        assignments["K0"][instance_id] = str(slot_id)
        points = np.asarray(grouped.get(("K0", instance_id), ()), dtype=np.float64).reshape((-1, 3))
        if len(points) >= configuration.minimum_point_count:
            anchor_points[instance_id] = points
            reason = "k0_slot_anchor"
        else:
            reason = "insufficient_high_confidence_points"
        diagnostics["K0"][instance_id] = {
            "reason": reason,
            "slotID": str(slot_id),
            "highConfidencePointCount": int(len(points)),
        }

    anchor_trees = {
        instance_id: cKDTree(points) for instance_id, points in anchor_points.items()
    }
    for keyframe_id in sorted(observed_instances):
        if keyframe_id == "K0":
            continue
        eligible_later = {}
        for instance_id in sorted(observed_instances[keyframe_id]):
            points = np.asarray(
                grouped.get((keyframe_id, instance_id), ()), dtype=np.float64
            ).reshape((-1, 3))
            if len(points) < configuration.minimum_point_count:
                diagnostics[keyframe_id][instance_id] = {
                    "reason": "insufficient_high_confidence_points",
                    "highConfidencePointCount": int(len(points)),
                }
            else:
                eligible_later[instance_id] = points

        if not anchor_trees:
            for instance_id, points in eligible_later.items():
                diagnostics[keyframe_id][instance_id] = {
                    "reason": "missing_k0_slot_anchor",
                    "highConfidencePointCount": int(len(points)),
                }
            continue

        scores = {}
        for anchor_id, tree in anchor_trees.items():
            for later_id, points in eligible_later.items():
                distances = np.asarray(tree.query(points, k=1)[0], dtype=np.float64)
                scores[(anchor_id, later_id)] = {
                    "median": float(np.median(distances)),
                    "overlap": float(
                        np.mean(distances <= configuration.overlap_distance_metres)
                    ),
                }

        best_later_for_anchor = {}
        for anchor_id in anchor_trees:
            available = [
                (value["median"], later_id)
                for (candidate_anchor, later_id), value in scores.items()
                if candidate_anchor == anchor_id
            ]
            if available:
                best_later_for_anchor[anchor_id] = min(available)[1]
        best_anchor_for_later = {}
        for later_id in eligible_later:
            available = [
                (value["median"], anchor_id)
                for (anchor_id, candidate_later), value in scores.items()
                if candidate_later == later_id
            ]
            if available:
                best_anchor_for_later[later_id] = min(available)[1]

        for later_id, points in eligible_later.items():
            anchor_id = best_anchor_for_later[later_id]
            score = scores[(anchor_id, later_id)]
            diagnostic = {
                "slotID": str(k0_assignments[anchor_id]),
                "k0InstanceID": anchor_id,
                "highConfidencePointCount": int(len(points)),
                "medianDistanceMetres": score["median"],
                "overlapFraction": score["overlap"],
            }
            passes_overlap = (
                score["median"] <= configuration.maximum_median_distance_metres
                and score["overlap"] >= configuration.minimum_overlap_fraction
            )
            mutual_best = best_later_for_anchor.get(anchor_id) == later_id
            anchor_competitors = [
                value["median"]
                for (candidate_anchor, candidate_later), value in scores.items()
                if candidate_anchor == anchor_id and candidate_later != later_id
            ]
            later_competitors = [
                value["median"]
                for (candidate_anchor, candidate_later), value in scores.items()
                if candidate_later == later_id and candidate_anchor != anchor_id
            ]
            unique = (
                _is_unique_best(
                    score["median"], anchor_competitors,
                    configuration.maximum_uniqueness_ratio,
                )
                and _is_unique_best(
                    score["median"], later_competitors,
                    configuration.maximum_uniqueness_ratio,
                )
            )
            if passes_overlap and mutual_best and unique:
                assignments[keyframe_id][later_id] = str(k0_assignments[anchor_id])
                diagnostic["reason"] = "matched_k0_anchor"
            elif passes_overlap:
                diagnostic["reason"] = "ambiguous_k0_surface_match"
            else:
                diagnostic["reason"] = "insufficient_surface_overlap"
            diagnostics[keyframe_id][later_id] = diagnostic

    return assignments, diagnostics


def _row_assignments(instances: Sequence[dict], candidates: np.ndarray, configuration: LiDARSlotConfiguration):
    if not instances:
        return {}, {}
    if len(candidates) == 0:
        return {}, {_instance_id(instance): "inactive_ssm_slot" for instance in instances}

    ordered = sorted(instances, key=lambda value: _centroid(value)[0])
    expected_x = (np.arange(len(candidates), dtype=np.float64) + 0.5) / len(candidates)
    count_instances, count_slots = len(ordered), len(candidates)
    costs = np.full((count_instances + 1, count_slots + 1), np.inf)
    path_counts = np.zeros((count_instances + 1, count_slots + 1), dtype=np.int64)
    moves = np.full((count_instances + 1, count_slots + 1), "", dtype=object)
    costs[0, 0], path_counts[0, 0] = 0.0, 1

    def update(next_i, next_j, cost, move, paths):
        previous = costs[next_i, next_j]
        if cost < previous - 1e-12:
            costs[next_i, next_j] = cost
            path_counts[next_i, next_j] = paths
            moves[next_i, next_j] = move
        elif abs(cost - previous) <= 1e-12:
            path_counts[next_i, next_j] += paths

    for i in range(count_instances + 1):
        for j in range(count_slots + 1):
            if not np.isfinite(costs[i, j]):
                continue
            if j < count_slots:
                update(i, j + 1, costs[i, j] + 0.18, "skip_slot", path_counts[i, j])
            if i < count_instances:
                update(i + 1, j, costs[i, j] + 0.35, "skip_instance", path_counts[i, j])
            if i < count_instances and j < count_slots:
                confidence = float(ordered[i]["confidence"])
                match_cost = abs(_centroid(ordered[i])[0] - expected_x[j]) + 0.25 * (1.0 - confidence)
                update(i + 1, j + 1, costs[i, j] + match_cost, "match", path_counts[i, j])

    if path_counts[count_instances, count_slots] != 1:
        return {}, {_instance_id(instance): "ambiguous_slot_alignment" for instance in ordered}

    matched = []
    i, j = count_instances, count_slots
    while i or j:
        move = moves[i, j]
        if move == "match":
            instance = ordered[i - 1]
            confidence = float(instance["confidence"])
            match_cost = abs(_centroid(instance)[0] - expected_x[j - 1]) + 0.25 * (1.0 - confidence)
            matched.append((instance, int(candidates[j - 1]), match_cost))
            i, j = i - 1, j - 1
        elif move == "skip_slot":
            j -= 1
        elif move == "skip_instance":
            i -= 1
        else:
            raise RuntimeError("invalid slot-assignment path")

    assignments, rejections = {}, {}
    for instance, original_index, match_cost in matched:
        confidence = max(0.0, 1.0 - match_cost / 0.20)
        local_id = _instance_id(instance)
        if confidence >= configuration.minimum_assignment_confidence:
            assignments[local_id] = slot_id_for_original_index(original_index)
        else:
            rejections[local_id] = "ambiguous_slot_alignment"
    return assignments, rejections


def _evaluate_row_split(
    ordered: Sequence[dict], configuration: LiDARSlotConfiguration
) -> tuple[bool, int, list[float]]:
    """Check whether `ordered` (sorted by Y) splits into two confident rows."""

    gaps = [
        _centroid(right)[1] - _centroid(left)[1]
        for left, right in zip(ordered, ordered[1:])
    ]
    split_index, largest_gap = max(enumerate(gaps), key=lambda item: item[1])
    second_largest_gap = sorted(gaps, reverse=True)[1] if len(gaps) > 1 else 0.0
    upper, lower = ordered[: split_index + 1], ordered[split_index + 1 :]
    comparison_tolerance = 1e-12
    ok = not (
        largest_gap + comparison_tolerance < configuration.minimum_arch_row_gap
        or largest_gap + comparison_tolerance
        < configuration.minimum_arch_row_gap_dominance * second_largest_gap
        or len(upper) < 2
        or len(lower) < 2
    )
    return ok, split_index, gaps


def assign_keyframe_slots(
    *, instances: Sequence[dict], photo_index: int, active_original_indices: np.ndarray,
    configuration: LiDARSlotConfiguration = LiDARSlotConfiguration(),
) -> tuple[dict[str, str], dict[str, str]]:
    """Return safe local-instance-to-slot assignments and explicit rejections."""

    if not 0 <= int(photo_index) < len(VISIBLE_MASKS):
        raise ValueError("photo_index must identify one of the five reconstruction views")
    active = np.asarray(active_original_indices, dtype=np.intp)
    if active.ndim != 1 or np.any(active < 0) or np.any(active >= 28):
        raise ValueError("active_original_indices must contain original SSM indices in [0, 27]")
    active_set = set(int(value) for value in active)
    high_confidence, rejected = [], {}
    for instance in instances:
        local_id = _instance_id(instance)
        _centroid(instance)
        confidence = float(instance.get("confidence", -1))
        if not np.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError("instance confidence must be finite and in [0, 1]")
        if confidence < configuration.minimum_detector_confidence:
            rejected[local_id] = "low_detector_confidence"
        else:
            high_confidence.append(instance)
    if not high_confidence:
        return {}, rejected

    visible = np.flatnonzero(np.asarray(VISIBLE_MASKS[int(photo_index)], dtype=bool))
    candidates = _screen_ordered_candidates(
        np.asarray([index for index in visible if int(index) in active_set], dtype=np.intp)
    )
    if len(candidates) == 0:
        rejected.update({_instance_id(instance): "inactive_ssm_slot" for instance in high_confidence})
        return {}, rejected

    if photo_index in (0, 1):
        assignments, row_rejections = _row_assignments(high_confidence, candidates, configuration)
        rejected.update(row_rejections)
        return assignments, rejected

    ordered_y = sorted(high_confidence, key=lambda value: _centroid(value)[1])
    if len(ordered_y) < 4:
        rejected.update({_instance_id(instance): "ambiguous_arch_rows" for instance in high_confidence})
        return {}, rejected

    ok, split_index, gaps = _evaluate_row_split(ordered_y, configuration)
    if not ok:
        # A single stray detection sitting between two otherwise-clean
        # clusters splits one real gap into two comparable ones, failing the
        # dominance check for the whole field even though only that one
        # instance is actually ambiguous. If exactly one instance sits
        # between the two largest competing gaps, exclude only that
        # instance and retry — never guessing its row, just not punishing
        # the rest of the field for its uncertainty. Anything wider than
        # one stray instance still falls back to full rejection below.
        excluded = None
        top_two = sorted(range(len(gaps)), key=lambda i: gaps[i], reverse=True)[:2]
        if len(top_two) == 2 and abs(top_two[0] - top_two[1]) == 1:
            stray_index = max(top_two)
            candidate = ordered_y[:stray_index] + ordered_y[stray_index + 1 :]
            retry_ok, retry_split_index, _ = _evaluate_row_split(candidate, configuration)
            if retry_ok:
                excluded = ordered_y[stray_index]
                ordered_y = candidate
                ok, split_index = retry_ok, retry_split_index
        if not ok:
            rejected.update({_instance_id(instance): "ambiguous_arch_rows" for instance in high_confidence})
            return {}, rejected
        rejected[_instance_id(excluded)] = "ambiguous_row_membership"

    upper, lower = ordered_y[: split_index + 1], ordered_y[split_index + 1 :]
    assignments = {}
    for row, row_candidates in ((upper, candidates[candidates < 14]), (lower, candidates[candidates >= 14])):
        row_assignments, row_rejections = _row_assignments(row, row_candidates, configuration)
        assignments.update(row_assignments)
        rejected.update(row_rejections)
    return assignments, rejected
