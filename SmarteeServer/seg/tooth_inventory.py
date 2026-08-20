"""Load validated Milestone 1 instance evidence for tooth inventory matching."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import numpy as np
import skimage.io


@dataclass(frozen=True)
class InventoryInstance:
    local_id: str
    centroid_xy: Tuple[float, float]
    width: float
    height: float
    detector_confidence: float
    area_pixels: int


@dataclass(frozen=True)
class InventoryView:
    photo_index: int
    checkpoint: str
    backend: str
    fallback_reason: Optional[str]
    instances: Tuple[InventoryInstance, ...]


@dataclass(frozen=True)
class SlotAssignment:
    slot_id: str
    arch: str
    ordinal: int
    instance: Optional[InventoryInstance]
    assignment_confidence: float
    rejection_reason: Optional[str] = None


def _load_binary_mask(path: Path, expected_shape: Tuple[int, int]) -> None:
    mask = np.asarray(skimage.io.imread(str(path)))
    if mask.ndim != 2 or mask.shape != expected_shape:
        raise ValueError(
            f"Invalid instance mask geometry for {path.name}: {mask.shape}, "
            f"expected {expected_shape}."
        )
    if set(np.unique(mask)) - {0, 255}:
        raise ValueError(f"Instance mask is not binary: {path.name}")


def load_inventory_views(instance_root: Path, tag: str) -> Dict[int, InventoryView]:
    """Load RF-DETR-only identity evidence from a durable instance bundle."""

    tag_dir = instance_root / tag
    manifest_path = tag_dir / "instances.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 1:
        raise ValueError("Unsupported instance manifest schema")

    views = {}
    for raw_index, record in manifest.get("views", {}).items():
        photo_index = int(raw_index)
        backend = str(record["backend"])
        width = int(record["rgbWidth"])
        height = int(record["rgbHeight"])
        if width <= 0 or height <= 0:
            raise ValueError("Invalid source RGB geometry")
        instances = []
        if backend == "rfdetr":
            for instance in record.get("instances", []):
                mask_path = tag_dir / str(instance["mask"])
                _load_binary_mask(mask_path, (height, width))
                confidence = float(instance["confidence"])
                if not 0.0 <= confidence <= 1.0:
                    raise ValueError("Invalid detector confidence")
                bbox = [int(value) for value in instance["bboxXYWH"]]
                centroid = [float(value) for value in instance["centroidXY"]]
                if len(bbox) != 4 or len(centroid) != 2:
                    raise ValueError("Invalid instance geometry metadata")
                instances.append(
                    InventoryInstance(
                        local_id=str(instance["localId"]),
                        centroid_xy=(centroid[0] / width, centroid[1] / height),
                        width=bbox[2] / width,
                        height=bbox[3] / height,
                        detector_confidence=confidence,
                        area_pixels=int(instance["areaPixels"]),
                    )
                )
        views[photo_index] = InventoryView(
            photo_index=photo_index,
            checkpoint=str(record.get("checkpoint", "")),
            backend=backend,
            fallback_reason=record.get("fallbackReason"),
            instances=tuple(instances),
        )
    return views


def align_primary_arch(
    instances: Sequence[InventoryInstance], arch: str
) -> Tuple[SlotAssignment, ...]:
    """Align a primary arch sequence to fixed slots while allowing gaps."""

    if arch not in ("U", "L"):
        raise ValueError("arch must be 'U' or 'L'")
    candidates = sorted(
        (instance for instance in instances if instance.detector_confidence >= 0.50),
        key=lambda instance: instance.centroid_xy[0],
    )
    count = len(candidates)
    slot_count = 14
    costs = np.full((count + 1, slot_count + 1), np.inf)
    moves = np.full((count + 1, slot_count + 1), "", dtype=object)
    costs[0, 0] = 0.0
    for candidate_index in range(count + 1):
        for slot_index in range(slot_count + 1):
            current = costs[candidate_index, slot_index]
            if not np.isfinite(current):
                continue
            if slot_index < slot_count and current + 0.18 < costs[candidate_index, slot_index + 1]:
                costs[candidate_index, slot_index + 1] = current + 0.18
                moves[candidate_index, slot_index + 1] = "skip_slot"
            if candidate_index < count and current + 0.35 < costs[candidate_index + 1, slot_index]:
                costs[candidate_index + 1, slot_index] = current + 0.35
                moves[candidate_index + 1, slot_index] = "skip_instance"
            if candidate_index < count and slot_index < slot_count:
                instance = candidates[candidate_index]
                expected_x = (slot_index + 0.5) / slot_count
                match_cost = abs(instance.centroid_xy[0] - expected_x) + 0.25 * (
                    1.0 - instance.detector_confidence
                )
                if current + match_cost < costs[candidate_index + 1, slot_index + 1]:
                    costs[candidate_index + 1, slot_index + 1] = current + match_cost
                    moves[candidate_index + 1, slot_index + 1] = "match"

    matched = {}
    candidate_index, slot_index = count, slot_count
    while candidate_index or slot_index:
        move = moves[candidate_index, slot_index]
        if move == "match":
            instance = candidates[candidate_index - 1]
            expected_x = (slot_index - 0.5) / slot_count
            match_cost = abs(instance.centroid_xy[0] - expected_x) + 0.25 * (
                1.0 - instance.detector_confidence
            )
            if match_cost <= 0.20:
                matched[slot_index] = (instance, match_cost)
            candidate_index -= 1
            slot_index -= 1
        elif move == "skip_slot":
            slot_index -= 1
        elif move == "skip_instance":
            candidate_index -= 1
        else:
            raise RuntimeError("Invalid primary-arch alignment path")

    return tuple(
        SlotAssignment(
            slot_id=f"{arch}-{ordinal:02d}",
            arch=arch,
            ordinal=ordinal,
            instance=matched.get(ordinal, (None, 0.0))[0],
            assignment_confidence=max(0.0, 1.0 - matched[ordinal][1] / 0.20)
            if ordinal in matched
            else 0.0,
            rejection_reason=None if ordinal in matched else "unobserved",
        )
        for ordinal in range(1, slot_count + 1)
    )


def _split_supporting_arch_rows(
    instances: Sequence[InventoryInstance],
) -> Optional[Tuple[Tuple[InventoryInstance, ...], Tuple[InventoryInstance, ...]]]:
    """Return upper and lower rows only when a supporting view separates them."""

    ordered = sorted(instances, key=lambda instance: instance.centroid_xy[1])
    if len(ordered) < 4:
        return None
    gaps = [
        right.centroid_xy[1] - left.centroid_xy[1]
        for left, right in zip(ordered, ordered[1:])
    ]
    split_index, largest_gap = max(enumerate(gaps), key=lambda item: item[1])
    upper = tuple(ordered[: split_index + 1])
    lower = tuple(ordered[split_index + 1 :])
    if largest_gap < 0.12 or len(upper) < 2 or len(lower) < 2:
        return None
    return upper, lower


def _evidence_record(
    photo_index: int, view: InventoryView, assignment: SlotAssignment
) -> dict:
    """Format one provenance-preserving assignment evidence record."""

    if assignment.instance is None:
        raise ValueError("Cannot create evidence for an unassigned slot")
    return {
        "photoIndex": photo_index,
        "checkpoint": view.checkpoint,
        "localId": assignment.instance.local_id,
        "detectorConfidence": assignment.instance.detector_confidence,
        "normalizedCentroidXY": list(assignment.instance.centroid_xy),
        "assignmentConfidence": assignment.assignment_confidence,
    }


def build_tooth_inventory(
    tag: str,
    views: Dict[int, InventoryView],
    confirmed_absent_slots=(),
) -> dict:
    """Build distinct patient and design statuses without changing the SSM."""

    valid_slot_ids = {
        *(f"U-{ordinal:02d}" for ordinal in range(1, 15)),
        *(f"L-{ordinal:02d}" for ordinal in range(1, 15)),
    }
    confirmed_absent_slots = set(confirmed_absent_slots)
    invalid_slots = confirmed_absent_slots - valid_slot_ids
    if invalid_slots:
        raise ValueError(f"Unknown confirmed-absent slot: {sorted(invalid_slots)[0]}")

    upper = align_primary_arch(views.get(0, InventoryView(0, "", "h5", None, ())).instances, "U")
    lower = align_primary_arch(views.get(1, InventoryView(1, "", "h5", None, ())).instances, "L")
    corroborating_evidence = {assignment.slot_id: [] for assignment in (*upper, *lower)}
    source_views = {}
    for photo_index, view in views.items():
        rejection_reasons = []
        if photo_index in (2, 3, 4):
            arch_rows = _split_supporting_arch_rows(view.instances)
            if arch_rows is None:
                rejection_reasons.append("ambiguous_arch_rows")
            else:
                for arch, row in zip(("U", "L"), arch_rows):
                    for assignment in align_primary_arch(row, arch):
                        if assignment.instance is not None:
                            corroborating_evidence[assignment.slot_id].append(
                                _evidence_record(photo_index, view, assignment)
                            )
        source_views[str(photo_index)] = {
            "backend": view.backend,
            "identityEvidenceAvailable": view.backend == "rfdetr" and bool(view.instances),
            "rejectionReasons": rejection_reasons,
        }
    slots = []
    for assignment in (*upper, *lower):
        if assignment.slot_id in confirmed_absent_slots:
            patient_status = design_status = "confirmedAbsent"
        elif assignment.instance is not None:
            patient_status = design_status = "observed"
        else:
            patient_status, design_status = "unknown", "inferred"
        evidence = []
        if assignment.instance is not None:
            photo_index = 0 if assignment.arch == "U" else 1
            view = views[photo_index]
            evidence.append(_evidence_record(photo_index, view, assignment))
            evidence.extend(corroborating_evidence[assignment.slot_id])
        slots.append(
            {
                "slotId": assignment.slot_id,
                "arch": "upper" if assignment.arch == "U" else "lower",
                "ordinal": assignment.ordinal,
                "patientStatus": patient_status,
                "designStatus": design_status,
                "confidence": assignment.assignment_confidence,
                "evidence": evidence,
                "rejectionReasons": [] if assignment.instance is not None else [assignment.rejection_reason],
            }
        )
    return {
        "schemaVersion": 1,
        "tag": tag,
        "sourceInstanceBundle": "instances.json",
        "sourceViews": source_views,
        "slots": slots,
    }


def write_tooth_inventory(output_root: Path, tag: str, inventory: dict) -> Path:
    """Atomically persist one inventory beside its request-specific artifacts."""

    output_dir = output_root / tag
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "tooth_inventory.json"
    temporary = output_dir / "tooth_inventory.json.tmp"
    temporary.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target
