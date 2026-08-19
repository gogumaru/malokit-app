"""Missing (cross-check), Displacement, dan Crossbite posterior -- dari foto frontal.

Port dari `11_app_simulation.ipynb` Section 5 & 6.

Kenapa crossbite posterior dari FRONTAL, bukan oklusal: foto frontal diambil saat
pasien menggigit, jadi kedua lengkung ada dalam SATU foto -- rotasi & skalanya
dijamin sama. Oklusal sudah dicoba dan gagal: foto atas & bawah adalah dua jepretan
terpisah yang orientasinya tidak dijamin sejajar.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

from . import models
from .arch import fit_arch_midline, number_by_midline
from .config import Config, DEFAULT_CONFIG
from .imaging import open_image
from .features import (
    Tooth,
    filter_spurious_instances,
    instance_features_from_mask,
    split_arch_kmeans,
)


# --------------------------------------------------------------------------
# Missing (cross-check) & Displacement
# --------------------------------------------------------------------------

def detect_missing_gaps(arch_feats: Sequence[Tooth], cfg: Config) -> List[Tuple[Tooth, Tooth, float]]:
    """Celah antar gigi bertetangga yang jauh lebih lebar dari normal.

    CATATAN: ini metode LAMA dan hanya cross-check. Sumber utama Missing adalah
    Arch Occupancy dari foto oklusal (`occlusal.py`). Foto frontal secara fisik
    tidak bisa melihat area premolar-molar (tertutup pipi), jadi gigi hilang di
    area itu MUSTAHIL terdeteksi dari sini -- berapa pun ambangnya.
    """
    ordered = sorted(arch_feats, key=lambda f: f["centroid"][0])
    flagged = []
    for a, b in zip(ordered, ordered[1:]):
        gap = b["bbox"][0] - a["bbox"][2]
        avg_width = (a["width"] + b["width"]) / 2
        ratio = gap / avg_width
        if ratio > cfg.GAP_RATIO_THRESHOLD:
            flagged.append((a, b, float(ratio)))
    return flagged


def detect_displacement(arch_feats: Sequence[Tooth], cfg: Config) -> List[Tuple[Tooth, float]]:
    """Gigi yang menyimpang dari kurva lengkung, dinormalisasi ke tingginya."""
    if len(arch_feats) < 4:
        return []
    xs = np.array([f["centroid"][0] for f in arch_feats])
    ys = np.array([f["centroid"][1] for f in arch_feats])
    coeffs = np.polyfit(xs, ys, deg=2)
    residuals = ys - np.polyval(coeffs, xs)
    flagged = []
    for f, res in zip(arch_feats, residuals):
        ratio = res / f["height"]
        if abs(ratio) > cfg.DISPLACEMENT_THRESHOLD:
            flagged.append((f, float(ratio)))
    return flagged


# --------------------------------------------------------------------------
# Crossbite posterior -- titik ukur TEPI BUKAL, bukan centroid
# --------------------------------------------------------------------------

def buccal_edge_x(f: Tooth, side: str) -> float:
    """Tepi bukal (terluar) gigi: x0 kalau di sisi kiri, x1 kalau di sisi kanan.

    Yang menentukan crossbite adalah permukaan bukal, bukan titik tengah gigi --
    centroid bias kalau lebar crown berbeda (masalah yang sama seperti Overjet
    sebelum diperbaiki ke tepi bbox).
    """
    x0, _y0, x1, _y1 = f["bbox"]
    return x0 if side == "kiri" else x1


def transverse_offset_edge(f: Tooth, side: str, midline_x: float) -> float:
    return abs(buccal_edge_x(f, side) - midline_x)


def compute_arch_width_edge(result_upper, result_lower, midline_x: float) -> float:
    offsets = [
        transverse_offset_edge(f, side, midline_x)
        for result in (result_upper, result_lower)
        for side in ("kiri", "kanan")
        for f, _pos in result[side]
    ]
    return max(offsets)


def compute_crossbite_proxy_edge(side, result_upper, result_lower, midline_x, arch_width, cfg) -> List[dict]:
    upper_by_pos = {pos: f for f, pos in result_upper[side]}
    lower_by_pos = {pos: f for f, pos in result_lower[side]}
    rows = []
    for pos in sorted(set(upper_by_pos) & set(lower_by_pos)):
        # Posisi 1-3 = zona anterior (C-ke-C), bukan wilayah crossbite posterior.
        if pos < cfg.CROSSBITE_POSTERIOR_MIN_POSITION:
            continue
        f_upper, f_lower = upper_by_pos[pos], lower_by_pos[pos]
        offset_upper = transverse_offset_edge(f_upper, side, midline_x)
        offset_lower = transverse_offset_edge(f_lower, side, midline_x)
        ratio = float((offset_lower - offset_upper) / arch_width)
        rows.append({
            "posisi": int(pos),
            "ratio": ratio,
            "flagged": ratio > cfg.CROSSBITE_THRESHOLD,
            "f_upper": f_upper,
            "f_lower": f_lower,
        })
    return rows


def compute_crossbite_posterior(
    upper: Sequence[Tooth], lower: Sequence[Tooth], cfg: Config = DEFAULT_CONFIG
) -> Optional[Dict[str, Any]]:
    """Pakai ulang upper/lower hasil split `analyze_frontal` -- tidak segmentasi ulang.

    Balikan `None` kalau gigi terlalu sedikit untuk dibandingkan.
    """
    if len(upper) < 2 or len(lower) < 2:
        return None
    midline_x = fit_arch_midline(upper)
    result_upper = number_by_midline(upper, midline_x)
    result_lower = number_by_midline(lower, midline_x)
    arch_width = compute_arch_width_edge(result_upper, result_lower, midline_x)
    rows = {
        side: compute_crossbite_proxy_edge(side, result_upper, result_lower, midline_x, arch_width, cfg)
        for side in ("kiri", "kanan")
    }
    flagged = [
        {
            "side": side, "posisi": r["posisi"], "ratio": r["ratio"],
            # objek gigi ikut dibawa supaya overlay bisa meng-outline gigi yang tepat
            "teeth": (r["f_upper"], r["f_lower"]),
        }
        for side in ("kiri", "kanan")
        for r in rows[side]
        if r["flagged"]
    ]
    return {
        "midline_x": midline_x,
        "rows": rows,
        "flagged": flagged,
        "label": "possible posterior crossbite" if flagged else "normal",
    }


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def analyze_frontal(img_path: Path, cfg: Config = DEFAULT_CONFIG) -> Dict[str, Any]:
    image = open_image(img_path)
    pred = models.frontal_seg(cfg).predict(
        source=image, conf=cfg.SEG_CONF, iou=cfg.SEG_IOU, verbose=False
    )[0]
    feats = [] if pred.masks is None else [instance_features_from_mask(xy) for xy in pred.masks.xy]
    feats = filter_spurious_instances(feats, cfg)
    upper, lower = split_arch_kmeans(feats)

    gaps = {
        "upper": detect_missing_gaps(upper, cfg),
        "lower": detect_missing_gaps(lower, cfg),
    }
    disp = {
        "upper": detect_displacement(upper, cfg),
        "lower": detect_displacement(lower, cfg),
    }
    return {
        "n_teeth": len(feats),
        "image_size": (image.width, image.height),
        "upper": upper,
        "lower": lower,
        "gaps": gaps,
        "disp": disp,
        "n_gaps": len(gaps["upper"]) + len(gaps["lower"]),
        "n_displaced": len(disp["upper"]) + len(disp["lower"]),
        "crossbite": compute_crossbite_posterior(upper, lower, cfg),
    }
