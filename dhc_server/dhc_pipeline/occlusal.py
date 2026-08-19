"""Missing (Arch Occupancy) & Crowding (Little's Irregularity Index) -- foto oklusal.

Port dari `11_app_simulation.ipynb` Section 7. Ini jalur UTAMA untuk Missing dan
satu-satunya untuk Crowding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

from . import models
from .arch import fit_arch_curve_robust, full_chain
from .config import Config, DEFAULT_CONFIG
from .imaging import open_image
from .features import Tooth, filter_spurious_instances, instance_features_from_mask


# --------------------------------------------------------------------------
# Missing -- Arch Occupancy
# --------------------------------------------------------------------------

def build_occupancy(feats: Sequence[Tooth], cfg: Config):
    """Proyeksikan semua titik mask ke arc-length kurva lengkung -> peta occupancy 1-D.

    Tidak memakai konsep "gigi tetangga" sama sekali, jadi kebal terhadap rotasi gigi
    dan salah-pasangan -- masalah yang membuat metode neighbour-gap gagal.
    """
    feats_clean, coeffs, removed = fit_arch_curve_robust(feats, cfg)
    xs_clean = np.array([f["centroid"][0] for f in feats_clean])
    xs_curve = np.linspace(xs_clean.min(), xs_clean.max(), cfg.OCCUPANCY_SAMPLES)
    ys_curve = np.polyval(coeffs, xs_curve)
    seg_len = np.hypot(np.diff(xs_curve), np.diff(ys_curve))
    cum_arc = np.concatenate([[0.0], np.cumsum(seg_len)])

    occupancy = np.zeros(cfg.OCCUPANCY_SAMPLES, dtype=bool)
    tooth_spans: List[Tuple[float, float]] = []
    for f in feats_clean:
        pts = f["points"]
        d2 = (pts[:, 0:1] - xs_curve[None, :]) ** 2 + (pts[:, 1:2] - ys_curve[None, :]) ** 2
        idxs = np.argmin(d2, axis=1)
        s_lo, s_hi = int(idxs.min()), int(idxs.max())
        occupancy[s_lo:s_hi + 1] = True
        tooth_spans.append((cum_arc[s_lo], cum_arc[s_hi]))
    return occupancy, cum_arc, xs_curve, ys_curve, tooth_spans, removed


def find_empty_gaps(occupancy, cum_arc, tooth_spans, cfg: Config):
    """Rentang kosong di antara gigi terluar yang lebih lebar dari ambang."""
    avg_w = float(np.mean([hi - lo for lo, hi in tooth_spans]))
    cover_start = min(lo for lo, _hi in tooth_spans)
    cover_end = max(hi for _lo, hi in tooth_spans)
    gaps: List[dict] = []
    in_gap, gap_start = False, None

    for i in range(len(occupancy)):
        s = cum_arc[i]
        if s < cover_start or s > cover_end:
            continue
        if not occupancy[i] and not in_gap:
            in_gap, gap_start = True, i
        elif occupancy[i] and in_gap:
            in_gap = False
            gap_len = cum_arc[i - 1] - cum_arc[gap_start]
            if gap_len > avg_w * cfg.MISSING_ARC_GAP_THRESHOLD:
                gaps.append({"length": float(gap_len), "idx_range": (gap_start, i - 1)})
    if in_gap:
        gap_len = cum_arc[-1] - cum_arc[gap_start]
        if gap_len > avg_w * cfg.MISSING_ARC_GAP_THRESHOLD:
            gaps.append({"length": float(gap_len), "idx_range": (gap_start, len(occupancy) - 1)})
    return gaps, avg_w


def detect_missing_occupancy(feats: Sequence[Tooth], cfg: Config) -> Dict[str, Any]:
    occupancy, cum_arc, xs_curve, ys_curve, tooth_spans, removed = build_occupancy(feats, cfg)
    gaps, avg_w = find_empty_gaps(occupancy, cum_arc, tooth_spans, cfg)
    return {
        "gaps": gaps,
        "n_gaps": len(gaps),
        "gap_ratios": [round(g["length"] / avg_w, 2) for g in gaps],
        "avg_tooth_arc_width": avg_w,
        "n_outliers_removed": len(removed),
        "label": "possible missing tooth" if gaps else "normal",
        "xs_curve": xs_curve,
        "ys_curve": ys_curve,
        # objek gigi yang dibuang fit robust -- bahan overlay, bukan perhitungan
        "removed_masks": removed,
    }


# --------------------------------------------------------------------------
# Crowding -- Little's Irregularity Index
# --------------------------------------------------------------------------

def littles_step(f_i: Tooth, f_next: Tooth) -> Tuple[float, np.ndarray, np.ndarray]:
    """"Step" (loncatan) titik kontak antara dua gigi bertetangga.

    Arah lengkung diambil LOKAL dari dua centroid tetangga saja (`u`), jadi tidak
    butuh fit kurva global sama sekali -- otomatis kebal terhadap semua masalah
    `polyfit` yang mengganggu Arch Occupancy.

    `p_a` = titik mask gigi-i yang paling maju ke arah gigi berikutnya,
    `p_b` = titik mask gigi berikutnya yang paling mundur ke arah gigi-i.
    Kalau lengkung rapi keduanya sejajar di sumbu `n`; kalau gigi berputar/berimpit,
    muncul offset -- itulah sinyal crowding.
    """
    ci = np.array(f_i["centroid"])
    cn = np.array(f_next["centroid"])
    u = cn - ci
    u = u / np.linalg.norm(u)
    n = np.array([-u[1], u[0]])
    pts_i = f_i["points"].astype(np.float64)
    pts_n = f_next["points"].astype(np.float64)
    p_a = pts_i[np.argmax(pts_i @ u)]
    p_b = pts_n[np.argmin(pts_n @ u)]
    avg_w = (f_i["oriented_width"] + f_next["oriented_width"]) / 2
    return float(abs(np.dot(p_a - p_b, n)) / avg_w), p_a, p_b


def detect_crowding_littles(feats: Sequence[Tooth], cfg: Config) -> Dict[str, Any]:
    """Little's Index pada segmen ANTERIOR saja (kaninus-ke-kaninus).

    Molar sengaja dikecualikan: angulasi alaminya bukan tanda crowding. Versi yang
    memakai seluruh lengkung sudah dicoba -- hasilnya berisik dan gagal memisahkan
    normal vs crowding.

    `flagged_teeth` = indeks 1-based sepanjang rantai gigi dari kiri ke kanan gambar
    (bukan nomor FDI -- kita tidak punya penomoran FDI asli).
    """
    chain, n_left = full_chain(feats)
    start = max(0, n_left - cfg.LITTLES_ANTERIOR_N)
    end = min(len(chain), n_left + cfg.LITTLES_ANTERIOR_N)
    anterior = chain[start:end]

    steps: List[float] = []
    flagged_idx: set[int] = set()
    for i in range(len(anterior) - 1):
        step, _pa, _pb = littles_step(anterior[i], anterior[i + 1])
        steps.append(step)
        if step > cfg.LITTLES_STEP_THRESHOLD:
            flagged_idx.add(start + i + 1)      # 1-based index dalam chain penuh
            flagged_idx.add(start + i + 2)

    total = float(sum(steps))
    return {
        "sum": total,
        "steps": [round(s, 3) for s in steps],
        "n_anterior": len(anterior),
        "flagged_teeth": sorted(flagged_idx),
        "label": "possible crowding" if total > cfg.LITTLES_THRESHOLD_SUM else "normal",
        # Rantai gigi ikut dikembalikan supaya overlay bisa memetakan tiap indeks di
        # `flagged_teeth` ke poligon gigi yang BENAR-BENAR sama -- tanpa ini, angka
        # dan sorotan di layar bisa merujuk gigi yang berbeda.
        "chain": chain,
    }


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def analyze_occlusal(img_path: Path, cfg: Config = DEFAULT_CONFIG) -> Dict[str, Any]:
    """Satu foto oklusal -> missing (arch occupancy) + crowding (Little's Index).

    Kalau gigi yang tersegmentasi terlalu sedikit, `missing` & `crowding` = None --
    itu hasil "tidak bisa dihitung" yang sah, bukan error.
    """
    image = open_image(img_path)
    pred = models.occlusal_seg(cfg).predict(
        source=image, conf=cfg.SEG_CONF, iou=cfg.SEG_IOU, verbose=False
    )[0]
    feats = [] if pred.masks is None else [instance_features_from_mask(xy) for xy in pred.masks.xy]
    feats = filter_spurious_instances(feats, cfg)

    if len(feats) < cfg.MIN_TEETH_FOR_OCCLUSAL:
        return {
            "n_teeth": len(feats),
            "image_size": (image.width, image.height),
            "feats": feats,
            "missing": None,
            "crowding": None,
            "reason": f"only {len(feats)} teeth segmented, need at least {cfg.MIN_TEETH_FOR_OCCLUSAL}",
        }

    return {
        "n_teeth": len(feats),
        "image_size": (image.width, image.height),
        "feats": feats,
        "missing": detect_missing_occupancy(feats, cfg),
        "crowding": detect_crowding_littles(feats, cfg),
        "reason": None,
    }
