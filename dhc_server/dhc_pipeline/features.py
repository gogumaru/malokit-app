"""Fitur per gigi dari mask segmentasi + penyaring mask palsu.

Port langsung dari `11_app_simulation.ipynb` Section 3. Perilaku harus IDENTIK --
ada uji regresi di `tests/test_regression.py` yang membandingkan hasil paket ini
dengan angka yang keluar dari notebook.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

import cv2
import numpy as np
from sklearn.cluster import KMeans

from .config import Config, DEFAULT_CONFIG

Tooth = Dict[str, Any]


def instance_features_from_mask(pts: np.ndarray) -> Tooth:
    """Ubah poligon mask jadi fitur yang dipakai semua modul hilir.

    `oriented_width` (sisi terpanjang `cv2.minAreaRect`) dipakai Little's Index --
    tahan rotasi, beda dari `width` bbox lurus yang mengecil kalau gigi berputar.
    """
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    (_cx, _cy), (rw, rh), _angle = cv2.minAreaRect(pts.astype(np.float32))
    return {
        "points": pts,
        "centroid": [float((x0 + x1) / 2), float((y0 + y1) / 2)],
        "bbox": (x0, y0, x1, y1),
        "width": x1 - x0,
        "height": y1 - y0,
        "oriented_width": float(max(rw, rh)),
    }


def bbox_area(f: Tooth) -> float:
    x0, y0, x1, y1 = f["bbox"]
    return float((x1 - x0) * (y1 - y0))


def filter_spurious_instances(feats: Sequence[Tooth], cfg: Config = DEFAULT_CONFIG) -> List[Tooth]:
    """Buang mask yang jauh lebih kecil dari gigi pada umumnya."""
    if not feats:
        return list(feats)
    areas = [bbox_area(f) for f in feats]
    median_area = float(np.median(areas))
    return [f for f, a in zip(feats, areas) if a >= median_area * cfg.SPURIOUS_MIN_AREA_RATIO]


def drop_edge_slivers(
    feats: Sequence[Tooth], img_w: int, img_h: int, cfg: Config = DEFAULT_CONFIG
) -> List[Tooth]:
    """Buang mask yang NEMPEL tepi frame **DAN** jauh lebih kecil dari gigi lain.

    Dua syarat itu harus barengan. Kalau cuma "nempel tepi", gigi asli paling depan
    yang kepotong frame ikut kebuang -- itu terbukti bikin regresi saat diuji.

    Ditemukan dari audit 44 foto lateral: satu foto punya mask palsu di LUAR mulut
    (13x20 px di tepi frame, 0.20x median) yang lolos `filter_spurious_instances`
    lalu terpilih sebagai anchor insisivus -> overjet jadi 9.33 (mustahil).

    Ambang 0.30 dikalibrasi dari data itu: noise = 0.20x (dibuang), gigi asli yang
    kepotong frame = 0.45x & 0.52x (aman). Diuji ulang ke 44 foto: 0 regresi.

    Sengaja HANYA dipakai di jalur lateral -- frontal & oklusal belum diuji.
    """
    if not feats:
        return list(feats)
    areas = [bbox_area(f) for f in feats]
    med = float(np.median(areas))
    tol = cfg.EDGE_SLIVER_TOL_PX
    out: List[Tooth] = []
    for f, a in zip(feats, areas):
        x0, y0, x1, y1 = f["bbox"]
        touches_edge = x0 <= tol or y0 <= tol or x1 >= img_w - tol or y1 >= img_h - tol
        if touches_edge and a < med * cfg.EDGE_SLIVER_MAX_AREA_RATIO:
            continue
        out.append(f)
    return out


def split_arch_kmeans(feats: Sequence[Tooth]) -> tuple[List[Tooth], List[Tooth]]:
    """Pisah lengkung atas vs bawah.

    Fit kurva kuadratik ke semua gigi dulu, baru cluster **residual**-nya -- bukan
    posisi-y mentah. Posisi-y mentah gagal kalau kepala pasien miring atau lengkung
    melengkung tajam (catatan di `10_frontal_missing_displacement.ipynb`).
    """
    feats = list(feats)
    if len(feats) < 4:
        if len(feats) < 2:
            return feats, []
        ys = np.array([[f["centroid"][1]] for f in feats])
        km = KMeans(n_clusters=2, n_init=10, random_state=0).fit(ys)
        upper_label = int(np.argmin(km.cluster_centers_.flatten()))
        upper = [f for f, l in zip(feats, km.labels_) if l == upper_label]
        lower = [f for f, l in zip(feats, km.labels_) if l != upper_label]
        return upper, lower

    xs = np.array([f["centroid"][0] for f in feats])
    ys = np.array([f["centroid"][1] for f in feats])
    coeffs = np.polyfit(xs, ys, deg=2)
    residuals = ys - np.polyval(coeffs, xs)
    km = KMeans(n_clusters=2, n_init=10, random_state=0).fit(residuals.reshape(-1, 1))
    upper_label = int(np.argmin(km.cluster_centers_.flatten()))
    upper = [f for f, l in zip(feats, km.labels_) if l == upper_label]
    lower = [f for f, l in zip(feats, km.labels_) if l != upper_label]
    return upper, lower


def median_area(feats: Sequence[Tooth]) -> float:
    return float(np.median([bbox_area(f) for f in feats])) if feats else 0.0
