#!/usr/bin/env python3
"""Evaluate a trained RF-DETR tooth checkpoint on the untouched test split."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
os.environ.setdefault("RF_HOME", str(SCRIPT_DIR / ".cache" / "models"))
os.environ.setdefault("MPLCONFIGDIR", str(SCRIPT_DIR / ".cache" / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(SCRIPT_DIR / ".cache" / "xdg"))

import torch
from rfdetr import RFDETRSegSmall


def resolve_device(requested: str) -> str:
    if requested != "auto":
        if requested == "mps" and not torch.backends.mps.is_available():
            raise ValueError("MPS was requested but is not available to PyTorch.")
        if requested == "cuda" and not torch.cuda.is_available():
            raise ValueError("CUDA was requested but is not available to PyTorch.")
        return requested
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=SCRIPT_DIR / "runs" / "small-baseline" / "checkpoint_best_total.pth",
    )
    parser.add_argument("--dataset", type=Path, default=SCRIPT_DIR / "prepared")
    parser.add_argument(
        "--output",
        type=Path,
        default=SCRIPT_DIR / "runs" / "small-baseline" / "test_metrics.json",
    )
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--resolution", type=int, default=384)
    parser.add_argument("--device", choices=("auto", "mps", "cpu", "cuda"), default="auto")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checkpoint = args.checkpoint.resolve()
    dataset = args.dataset.resolve()
    output = args.output.resolve()
    if not checkpoint.is_file():
        raise FileNotFoundError(f"Checkpoint not found: {checkpoint}")
    if not (dataset / "test" / "_annotations.coco.json").is_file():
        raise FileNotFoundError(f"Test COCO annotations not found in: {dataset}")
    if output.exists():
        raise FileExistsError(f"Metrics output already exists: {output}")

    device = resolve_device(args.device)
    print(f"Checkpoint: {checkpoint}")
    print(f"Test dataset: {dataset / 'test'}")
    print(f"Device: {device}")
    model = RFDETRSegSmall.from_checkpoint(checkpoint, device=device)
    metrics = model.evaluate(
        split="test",
        dataset_dir=str(dataset),
        output_dir=str(output.parent / "test-evaluation"),
        batch_size=args.batch_size,
        num_workers=args.num_workers,
        device=device,
        resolution=args.resolution,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        json.dump(metrics, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(f"Saved metrics: {output}")
    for key in sorted(metrics):
        print(f"{key}: {metrics[key]:.6f}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
