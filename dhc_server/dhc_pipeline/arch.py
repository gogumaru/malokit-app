"""Geometri lengkung: midline, urutan gigi, fit kurva robust.

Port langsung dari `11_app_simulation.ipynb` Section 3 & 7.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

import numpy as np
from scipy.spatial.distance import cdist

from .config import Config, DEFAULT_CONFIG

Tooth = Dict[str, Any]


def fit_arch_midline(feats: Sequence[Tooth]) -> float:
    """Midline kiri-kanan = sumbu simetri parabola yang di-fit ke centroid gigi.

    Guard: kalau puncak parabola jatuh di LUAR rentang x gigi (terjadi kalau foto
    nyaris tidak melengkung, `a` mendekati nol -- puncaknya bisa meledak jauh di luar
    frame), jatuh balik ke rata-rata x.
    """
    xs = np.array([f["centroid"][0] for f in feats])
    ys = np.array([f["centroid"][1] for f in feats])
    a, b, _c = np.polyfit(xs, ys, deg=2)
    vertex_x = -b / (2 * a)
    if not (xs.min() <= vertex_x <= xs.max()):
        return float(np.mean(xs))
    return float(vertex_x)


def split_by_midline(feats: Sequence[Tooth], midline_x: float) -> Tuple[List[Tooth], List[Tooth]]:
    """Pisah kiri/kanan, masing-masing diurutkan dari yang PALING DEKAT midline."""
    left = sorted([f for f in feats if f["centroid"][0] < midline_x],
                  key=lambda f: midline_x - f["centroid"][0])
    right = sorted([f for f in feats if f["centroid"][0] >= midline_x],
                   key=lambda f: f["centroid"][0] - midline_x)
    return left, right


def number_by_midline(feats: Sequence[Tooth], midline_x: float) -> Dict[str, List[Tuple[Tooth, int]]]:
    """Posisi proxy: 1 = paling dekat midline, makin besar makin ke distal/molar.

    BUKAN nomor FDI asli -- statusnya sama seperti posisi 1-8 di jalur lateral.
    """
    left, right = split_by_midline(feats, midline_x)
    return {
        "kiri": [(f, i + 1) for i, f in enumerate(left)],
        "kanan": [(f, i + 1) for i, f in enumerate(right)],
    }


def mask_min_distance(f1: Tooth, f2: Tooth) -> float:
    return float(cdist(f1["points"], f2["points"]).min())


def chain_one_side(side_feats: Sequence[Tooth]) -> List[Tooth]:
    """Urutkan gigi dalam satu sisi pakai greedy nearest-neighbour.

    Jaraknya **mask-ke-mask**, bukan proyeksi sumbu-X. Sumbu-X gagal saat crowding
    parah: beberapa gigi bisa menumpuk di x yang hampir sama sehingga urutannya
    kacau dan gigi yang dipasangkan bukan tetangga sebenarnya.
    """
    side_feats = list(side_feats)
    if len(side_feats) <= 1:
        return side_feats
    remaining = list(side_feats)
    chain = [remaining.pop(0)]
    while remaining:
        last = chain[-1]
        nxt = min(remaining, key=lambda f: mask_min_distance(last, f))
        chain.append(nxt)
        remaining = [f for f in remaining if f is not nxt]
    return chain


def full_chain(feats: Sequence[Tooth]) -> Tuple[List[Tooth], int]:
    """Urutan penuh satu lengkung dari ujung kiri ke ujung kanan.

    Balikan: (chain, n_left) -- `n_left` = jumlah gigi di sisi kiri, dipakai untuk
    menentukan jendela anterior (kaninus-ke-kaninus) di Little's Index.
    """
    midline = fit_arch_midline(feats)
    left0, right0 = split_by_midline(feats, midline)
    left, right = chain_one_side(left0), chain_one_side(right0)
    return list(reversed(left)) + right, len(left)


def fit_arch_curve_robust(
    feats: Sequence[Tooth], cfg: Config = DEFAULT_CONFIG
) -> Tuple[List[Tooth], np.ndarray, List[Tooth]]:
    """Fit kurva lengkung yang tahan terhadap gigi "nyasar".

    Kenapa perlu: satu foto oklusal bisa menangkap DUA pandangan sekaligus --
    pantulan kaca mulut untuk lengkung utama, plus beberapa gigi yang terlihat
    langsung di tepi frame. `np.polyfit` biasa memperlakukan semuanya sebagai satu
    kurva dan hasilnya parabola yang bentuknya salah, membuat proyeksi arc-length
    berantakan.

    Ambangnya ABSOLUT (residual > faktor x tinggi rata-rata gigi), bukan statistik
    (z-score/MAD). Versi statistik sudah dicoba dan ditolak: saat diuji ke 13 pasien
    ia membuang gigi valid di 7 pasien dan memunculkan gap palsu.

    Balikan: (gigi_bersih, koefisien_kurva, gigi_yang_dibuang)
    """
    feats = list(feats)
    xs = np.array([f["centroid"][0] for f in feats])
    ys = np.array([f["centroid"][1] for f in feats])
    coeffs0 = np.polyfit(xs, ys, deg=2)
    residuals = np.abs(ys - np.polyval(coeffs0, xs))
    avg_height = float(np.mean([f["height"] for f in feats]))
    keep = residuals < avg_height * cfg.ROBUST_RESIDUAL_FACTOR
    removed = [f for f, k in zip(feats, keep) if not k]
    clean = [f for f, k in zip(feats, keep) if k]
    if not removed or len(clean) < 4:
        return feats, coeffs0, []
    xs2 = np.array([f["centroid"][0] for f in clean])
    ys2 = np.array([f["centroid"][1] for f in clean])
    coeffs1 = np.polyfit(xs2, ys2, deg=2)
    return clean, coeffs1, removed
