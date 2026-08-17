#!/usr/bin/env python3
"""Prepare a Roboflow COCO export for patient-safe RF-DETR training.

Roboflow assigns individual images to train/validation/test. Dental photos from
the same patient are correlated, so an image-level split leaks patient anatomy
into evaluation. This program recombines the exported splits and assigns every
visit/view belonging to one patient to exactly one new split.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import random
import re
import shutil
import sys
import zipfile
from collections import Counter, defaultdict
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SOURCE_SPLITS = ("train", "valid", "test")
OUTPUT_SPLITS = ("train", "valid", "test")
TOOTH_CATEGORY = {"id": 1, "name": "tooth", "supercategory": "tooth"}


@dataclass(frozen=True)
class ImageSample:
    """One image and all COCO annotations that belong to it."""

    patient_id: str
    archive: Path
    source_member: str
    image: dict[str, Any]
    annotations: tuple[dict[str, Any], ...]
    train_only: bool = False


def original_stem(file_name: str) -> str:
    """Remove Roboflow's generated hash and source-extension marker."""

    stem = Path(file_name).stem
    stem = re.sub(r"\.rf\.[^.]+$", "", stem, flags=re.IGNORECASE)
    return re.sub(r"_(?:JPE?G|PNG)$", "", stem, flags=re.IGNORECASE)


def patient_id_from_filename(file_name: str) -> str:
    """Extract `<patient>` from `<patient><YYYYMMDD><view>` filenames.

    Example: `202193202108305_JPG.rf.<hash>.jpg` contains patient `202193`,
    visit date `20210830`, and view `5`.
    """

    stem = original_stem(file_name)
    if len(stem) < 10 or not stem.isdigit():
        raise ValueError(
            f"Cannot read patient/date/view from {file_name!r}: "
            "expected <patient><YYYYMMDD><view>."
        )

    patient_id = stem[:-9]
    visit_date = stem[-9:-1]
    view = stem[-1]
    if not patient_id or not view.isdigit():
        raise ValueError(f"Invalid patient or view in {file_name!r}.")
    try:
        datetime.strptime(visit_date, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"Invalid visit date in {file_name!r}: {visit_date}") from exc
    return patient_id


def discover_archives(archive_dir: Path) -> list[Path]:
    """Return every Roboflow ZIP in the dataset directory."""

    candidates = sorted(archive_dir.glob("*.zip"))
    if not candidates:
        raise ValueError(f"No ZIP archives found in {archive_dir}.")
    return candidates


def source_annotation_members(members: set[str]) -> dict[str, str]:
    """Locate exported splits whether they are at ZIP root or one folder deep."""

    result = {}
    for split in SOURCE_SPLITS:
        suffix = f"{split}/_annotations.coco.json"
        matches = sorted(
            member
            for member in members
            if not member.startswith("__MACOSX/")
            and (member == suffix or member.endswith(f"/{suffix}"))
        )
        if len(matches) > 1:
            raise ValueError(f"Archive contains multiple {split!r} COCO files: {matches}")
        if matches:
            result[split] = matches[0]
    if not result:
        raise ValueError("Archive contains no train/valid/test COCO annotations.")
    return result


def training_only_patient_id(file_name: str, archive: Path) -> str:
    """Group ambiguous exported names conservatively outside evaluation."""

    stem = original_stem(file_name)
    stem = re.sub(r"(?:_jpe?g|_png)+$", "", stem, flags=re.IGNORECASE)
    return f"train-only:{archive.stem}:{stem.lower()}"


def load_samples(
    archives: Iterable[Path],
) -> tuple[list[ImageSample], Counter[str], dict[str, Any]]:
    """Read every exported split and return a single sample collection."""

    samples: list[ImageSample] = []
    category_counts: Counter[str] = Counter()
    seen_file_names: set[str] = set()
    skipped_unannotated: list[str] = []
    training_only_files: list[str] = []
    source_image_counts: Counter[str] = Counter()

    for archive in archives:
        archive = archive.resolve()
        with zipfile.ZipFile(archive) as bundle:
            members = set(bundle.namelist())
            annotations_by_split = source_annotation_members(members)
            for source_split, annotation_member in annotations_by_split.items():
                with bundle.open(annotation_member) as annotation_file:
                    coco = json.load(annotation_file)

                category_names = {
                    category["id"]: category["name"] for category in coco["categories"]
                }
                annotations_by_image: dict[int, list[dict[str, Any]]] = defaultdict(list)
                for annotation in coco["annotations"]:
                    category_name = category_names.get(annotation["category_id"])
                    if category_name not in {"teeth", "tooth"}:
                        raise ValueError(
                            f"Unsupported annotated category {category_name!r} "
                            f"(id={annotation['category_id']})."
                        )
                    category_counts[category_name] += 1
                    annotations_by_image[annotation["image_id"]].append(annotation)

                split_prefix = annotation_member.rsplit("/", 1)[0]
                for image in coco["images"]:
                    file_name = image["file_name"]
                    if file_name in seen_file_names:
                        raise ValueError(f"Duplicate exported filename: {file_name}")
                    seen_file_names.add(file_name)

                    source_member = f"{split_prefix}/{file_name}"
                    if source_member not in members:
                        raise ValueError(f"Archive is missing image {source_member}.")
                    annotations = tuple(annotations_by_image.get(image["id"], ()))
                    if not annotations:
                        skipped_unannotated.append(f"{archive.name}:{file_name}")
                        continue

                    train_only = False
                    try:
                        patient_id = patient_id_from_filename(file_name)
                    except ValueError:
                        patient_id = training_only_patient_id(file_name, archive)
                        train_only = True
                        training_only_files.append(f"{archive.name}:{file_name}")

                    source_image_counts[archive.name] += 1
                    samples.append(
                        ImageSample(
                            patient_id=patient_id,
                            archive=archive,
                            source_member=source_member,
                            image=image,
                            annotations=annotations,
                            train_only=train_only,
                        )
                    )

    preparation_notes = {
        "source_image_counts": dict(sorted(source_image_counts.items())),
        "skipped_unannotated_images": skipped_unannotated,
        "training_only_images": training_only_files,
    }
    return samples, category_counts, preparation_notes


def validate_ratios(ratios: dict[str, float]) -> None:
    if any(value <= 0 for value in ratios.values()):
        raise ValueError("All split ratios must be greater than zero.")
    if abs(sum(ratios.values()) - 1.0) > 1e-9:
        raise ValueError(f"Split ratios must sum to 1.0, got {sum(ratios.values())}.")


def assign_patients(
    samples: Iterable[ImageSample], ratios: dict[str, float], seed: int
) -> dict[str, list[ImageSample]]:
    """Balance image counts while keeping every patient in one split."""

    validate_ratios(ratios)
    by_patient: dict[str, list[ImageSample]] = defaultdict(list)
    for sample in samples:
        by_patient[sample.patient_id].append(sample)
    if len(by_patient) < len(OUTPUT_SPLITS):
        raise ValueError("At least three patients are required for three splits.")

    rng = random.Random(seed)
    training_only_patients = {
        sample.patient_id for sample in samples if sample.train_only
    }
    assigned: dict[str, list[ImageSample]] = {name: [] for name in OUTPUT_SPLITS}
    for patient_id in training_only_patients:
        assigned["train"].extend(by_patient.pop(patient_id))

    patient_groups = list(by_patient.items())
    rng.shuffle(patient_groups)
    # Largest groups are placed first. Shuffle above makes equal-size ties depend
    # on the seed without making the result depend on dictionary ordering.
    patient_groups.sort(key=lambda item: len(item[1]), reverse=True)

    total_images = sum(len(group) for _, group in patient_groups)
    targets = {name: ratios[name] * total_images for name in OUTPUT_SPLITS}
    for _, group in patient_groups:
        # Pick the split with the largest proportional amount still unfilled.
        destination = max(
            OUTPUT_SPLITS,
            key=lambda name: (
                (targets[name] - len(assigned[name])) / targets[name],
                targets[name] - len(assigned[name]),
            ),
        )
        assigned[destination].extend(group)

    return assigned


def normalized_coco(samples: list[ImageSample]) -> dict[str, Any]:
    """Create a deterministic one-category COCO document for one split."""

    images: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    next_annotation_id = 1

    for next_image_id, sample in enumerate(
        sorted(samples, key=lambda item: item.image["file_name"]), start=1
    ):
        image = copy.deepcopy(sample.image)
        image["id"] = next_image_id
        images.append(image)

        for source_annotation in sample.annotations:
            annotation = copy.deepcopy(source_annotation)
            annotation["id"] = next_annotation_id
            annotation["image_id"] = next_image_id
            annotation["category_id"] = TOOTH_CATEGORY["id"]
            annotations.append(annotation)
            next_annotation_id += 1

    return {
        "info": {
            "description": "Patient-safe RF-DETR tooth instance segmentation dataset",
            "version": "1.0",
        },
        "licenses": [],
        "categories": [TOOTH_CATEGORY],
        "images": images,
        "annotations": annotations,
    }


def verify_assignment(assigned: dict[str, list[ImageSample]]) -> None:
    """Fail if a patient leaked between generated splits."""

    patient_sets = {
        split: {sample.patient_id for sample in samples}
        for split, samples in assigned.items()
    }
    for index, left in enumerate(OUTPUT_SPLITS):
        for right in OUTPUT_SPLITS[index + 1 :]:
            overlap = patient_sets[left] & patient_sets[right]
            if overlap:
                raise AssertionError(
                    f"Patient leakage between {left} and {right}: {sorted(overlap)}"
                )
    for split in ("valid", "test"):
        if any(sample.train_only for sample in assigned[split]):
            raise AssertionError(f"Training-only sample assigned to {split}.")


def write_prepared_dataset(
    archives: Sequence[Path],
    output: Path,
    assigned: dict[str, list[ImageSample]],
    category_counts: Counter[str],
    preparation_notes: dict[str, Any],
    ratios: dict[str, float],
    seed: int,
) -> dict[str, Any]:
    """Write via a staging directory, then publish the completed dataset."""

    if output.exists():
        raise FileExistsError(
            f"Output already exists: {output}. Choose a new --output path."
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(f".{output.name}.tmp-{os.getpid()}")
    if staging.exists():
        raise FileExistsError(f"Staging path already exists: {staging}")
    staging.mkdir()

    try:
        with ExitStack() as stack:
            bundles = {
                archive.resolve(): stack.enter_context(zipfile.ZipFile(archive))
                for archive in archives
            }
            for split in OUTPUT_SPLITS:
                split_dir = staging / split
                split_dir.mkdir()
                coco = normalized_coco(assigned[split])
                with (split_dir / "_annotations.coco.json").open(
                    "w", encoding="utf-8"
                ) as annotation_file:
                    json.dump(coco, annotation_file, indent=2)
                    annotation_file.write("\n")

                for sample in assigned[split]:
                    destination = split_dir / sample.image["file_name"]
                    with bundles[sample.archive].open(
                        sample.source_member
                    ) as source, destination.open("wb") as target:
                        shutil.copyfileobj(source, target)

        summary = {
            "source_archives": [str(archive.resolve()) for archive in archives],
            "seed": seed,
            "requested_ratios": ratios,
            "source_category_annotation_counts": dict(sorted(category_counts.items())),
            "total_images": sum(len(samples) for samples in assigned.values()),
            "total_annotations": sum(
                len(sample.annotations)
                for samples in assigned.values()
                for sample in samples
            ),
            "total_patients": len(
                {
                    sample.patient_id
                    for samples in assigned.values()
                    for sample in samples
                }
            ),
            "training_only_images": len(preparation_notes["training_only_images"]),
            "training_only_files": preparation_notes["training_only_images"],
            "skipped_unannotated_images": preparation_notes[
                "skipped_unannotated_images"
            ],
            "source_image_counts": preparation_notes["source_image_counts"],
            "splits": {},
        }
        for split in OUTPUT_SPLITS:
            patient_ids = sorted({sample.patient_id for sample in assigned[split]})
            summary["splits"][split] = {
                "images": len(assigned[split]),
                "annotations": sum(
                    len(sample.annotations) for sample in assigned[split]
                ),
                "patients": len(patient_ids),
                "patient_ids": patient_ids,
            }

        with (staging / "split_summary.json").open("w", encoding="utf-8") as summary_file:
            json.dump(summary, summary_file, indent=2)
            summary_file.write("\n")

        staging.rename(output)
        return summary
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        type=Path,
        action="append",
        dest="archives",
        help="Roboflow COCO ZIP; repeat to combine exports (default: all dataset ZIPs)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=script_dir / "prepared",
        help="New output directory (default: seg/rfdetr/prepared)",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.70)
    parser.add_argument("--valid-ratio", type=float, default=0.15)
    parser.add_argument("--test-ratio", type=float, default=0.15)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    archives = args.archives or discover_archives(
        script_dir.parent / "datasets" / "roboflow"
    )
    archives = [archive.resolve() for archive in archives]
    output = args.output.resolve()
    ratios = {
        "train": args.train_ratio,
        "valid": args.valid_ratio,
        "test": args.test_ratio,
    }

    try:
        samples, category_counts, preparation_notes = load_samples(archives)
        assigned = assign_patients(samples, ratios=ratios, seed=args.seed)
        verify_assignment(assigned)
        summary = write_prepared_dataset(
            archives=archives,
            output=output,
            assigned=assigned,
            category_counts=category_counts,
            preparation_notes=preparation_notes,
            ratios=ratios,
            seed=args.seed,
        )
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Prepared dataset: {output}")
    print(
        f"Total: {summary['total_images']} images, "
        f"{summary['total_annotations']} annotations, "
        f"{summary['total_patients']} patients"
    )
    print(
        f"Training-only ambiguous filenames: {summary['training_only_images']}; "
        f"skipped unannotated: {len(summary['skipped_unannotated_images'])}"
    )
    for split in OUTPUT_SPLITS:
        details = summary["splits"][split]
        print(
            f"  {split:5}: {details['images']:3} images, "
            f"{details['annotations']:4} annotations, "
            f"{details['patients']:2} patients"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
