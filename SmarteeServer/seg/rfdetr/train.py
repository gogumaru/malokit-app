#!/usr/bin/env python3
"""Fine-tune RF-DETR Seg Small on the prepared tooth dataset."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent.parent

# Keep downloaded weights and library caches inside the ignored experiment
# directory instead of writing into a user's global home directory.
os.environ.setdefault("RF_HOME", str(SCRIPT_DIR / ".cache" / "models"))
os.environ.setdefault("MPLCONFIGDIR", str(SCRIPT_DIR / ".cache" / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(SCRIPT_DIR / ".cache" / "xdg"))

import torch
from rfdetr import RFDETRSegSmall


def resolve_device(requested: str) -> str:
    """Choose the best available accelerator, or validate an explicit choice."""

    if requested != "auto":
        if requested == "mps" and not torch.backends.mps.is_available():
            raise ValueError("MPS was requested but is not available to PyTorch.")
        if requested.startswith("cuda") and not torch.cuda.is_available():
            raise ValueError("CUDA was requested but is not available to PyTorch.")
        return requested
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def validate_dataset(dataset_dir: Path) -> None:
    """Check the minimum COCO layout before model construction/download."""

    for split in ("train", "valid", "test"):
        split_dir = dataset_dir / split
        annotation_file = split_dir / "_annotations.coco.json"
        if not annotation_file.is_file():
            raise ValueError(f"Missing COCO annotations: {annotation_file}")
        with annotation_file.open(encoding="utf-8") as stream:
            coco = json.load(stream)
        if coco.get("categories") != [
            {"id": 1, "name": "tooth", "supercategory": "tooth"}
        ]:
            raise ValueError(f"Unexpected categories in {annotation_file}.")
        if not coco.get("images") or not coco.get("annotations"):
            raise ValueError(f"Empty images or annotations in {annotation_file}.")


def copy_coco_subset(source: Path, destination: Path, image_limit: int) -> None:
    """Copy a few images and their annotations for an integration smoke test."""

    annotation_file = source / "_annotations.coco.json"
    with annotation_file.open(encoding="utf-8") as stream:
        coco = json.load(stream)
    selected_images = sorted(coco["images"], key=lambda image: image["file_name"])[
        :image_limit
    ]
    selected_ids = {image["id"] for image in selected_images}
    selected_annotations = [
        annotation
        for annotation in coco["annotations"]
        if annotation["image_id"] in selected_ids
    ]

    destination.mkdir(parents=True)
    subset = dict(coco)
    subset["images"] = selected_images
    subset["annotations"] = selected_annotations
    with (destination / "_annotations.coco.json").open("w", encoding="utf-8") as stream:
        json.dump(subset, stream, indent=2)
        stream.write("\n")
    for image in selected_images:
        shutil.copy2(source / image["file_name"], destination / image["file_name"])


@contextmanager
def smoke_dataset(full_dataset: Path) -> Iterator[Path]:
    """Build a disposable 4/2/2-image dataset and remove it after training."""

    destination = SCRIPT_DIR / ".cache" / f"smoke-dataset-{os.getpid()}"
    if destination.exists():
        raise FileExistsError(f"Smoke dataset already exists: {destination}")
    try:
        copy_coco_subset(full_dataset / "train", destination / "train", 4)
        copy_coco_subset(full_dataset / "valid", destination / "valid", 2)
        copy_coco_subset(full_dataset / "test", destination / "test", 2)
        yield destination
    finally:
        shutil.rmtree(destination, ignore_errors=True)


def run_training(args: argparse.Namespace, dataset_dir: Path, output_dir: Path) -> None:
    device = resolve_device(args.device)
    print(f"Device: {device}", flush=True)
    print(f"Dataset: {dataset_dir}", flush=True)
    print(f"Output: {output_dir}", flush=True)
    print(
        f"Training: epochs={args.epochs}, batch={args.batch_size}, "
        f"gradient_accumulation={args.grad_accum_steps}",
        flush=True,
    )

    # Disabling fused optimization and mixed precision is conservative on MPS.
    # Accuracy is unaffected; after the baseline works these can be benchmarked.
    model_options = {
        "device": device,
        "amp": False if device == "mps" else True,
        "fused_optimizer": False if device == "mps" else True,
    }
    if args.initial_checkpoint is not None:
        model_options["pretrain_weights"] = str(args.initial_checkpoint)
        print(f"Initial checkpoint: {args.initial_checkpoint}", flush=True)
    model = RFDETRSegSmall(**model_options)
    model.train(
        dataset_dir=str(dataset_dir),
        output_dir=str(output_dir),
        epochs=args.epochs,
        batch_size=args.batch_size,
        grad_accum_steps=args.grad_accum_steps,
        num_workers=args.num_workers,
        device=device,
        resolution=args.resolution,
        multi_scale=False,
        expanded_scales=False,
        checkpoint_interval=max(1, min(5, args.epochs)),
        eval_interval=1,
        early_stopping=False if args.smoke_test else True,
        early_stopping_patience=10,
        notes={
            "experiment": "tooth-instance-segmentation",
            "smoke_test": args.smoke_test,
            "prepared_split_seed": 42,
            "initial_checkpoint": (
                str(args.initial_checkpoint) if args.initial_checkpoint else None
            ),
        },
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=SCRIPT_DIR / "prepared",
        help="Prepared COCO dataset",
    )
    parser.add_argument("--output", type=Path, help="New training output directory")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum-steps", type=int, default=4)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--resolution", type=int, default=384)
    parser.add_argument(
        "--initial-checkpoint",
        type=Path,
        help="Initialize model weights from a checkpoint with a fresh training state",
    )
    parser.add_argument("--device", default="auto", choices=("auto", "mps", "cpu", "cuda"))
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Train one epoch on 4 train / 2 validation images",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset_dir = args.dataset.resolve()
    validate_dataset(dataset_dir)
    if args.initial_checkpoint is not None:
        args.initial_checkpoint = args.initial_checkpoint.resolve()
        if not args.initial_checkpoint.is_file():
            raise FileNotFoundError(
                f"Initial checkpoint not found: {args.initial_checkpoint}"
            )

    if args.smoke_test:
        args.epochs = 1
        args.batch_size = 1
        args.grad_accum_steps = 1
        output_dir = (args.output or SCRIPT_DIR / "runs" / "smoke").resolve()
    else:
        output_dir = (args.output or SCRIPT_DIR / "runs" / "small-baseline").resolve()
    if output_dir.exists():
        raise FileExistsError(
            f"Output already exists: {output_dir}. Choose a new --output path."
        )
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    if args.smoke_test:
        with smoke_dataset(dataset_dir) as tiny_dataset:
            run_training(args, tiny_dataset, output_dir)
    else:
        run_training(args, dataset_dir, output_dir)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
