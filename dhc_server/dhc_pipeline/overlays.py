"""Ubah hasil analisis jadi geometri untuk digambar app.

Acuan: `API_CONTRACT_OVERLAYS.md` + `OVERLAY_FILTERING_PROPOSAL.md` (disepakati).

Yang dikirim adalah **koordinat**, bukan gambar jadi. App masih memegang foto
aslinya, jadi mengirim balik PNG berarti mengirim data yang sama dua kali -- dan
teks yang dibakar ke piksel akan jadi sumber kebenaran kedua yang bisa berselisih
dengan `label` di response.

Aturan koordinat (paling mudah salah, baca dua kali):
    Semua titik adalah PECAHAN 0-1 terhadap **gambar yang diunggah**, titik asal
    kiri-atas. `x = piksel_x / lebar`, `y = piksel_y / tinggi`.

    Sudah diverifikasi bahwa `masks.xy` dari ultralytics memang berada di ruang
    piksel gambar asli, bukan 640x640 hasil letterbox: gambar yang sama diuji pada
    512x341, 1024x682, 2048x1364, dan 1200x800 -- pecahan koordinatnya identik
    sampai 3 desimal.

Dua sumbu keterangan yang sengaja dipisah:
    `role`   menjawab "ini apa"          -> menentukan WARNA di app
    `params` menjawab "ini bantu periksa apa" -> menentukan KAPAN ditampilkan

Modul ini sengaja terpisah dari modul analisis: tidak ada satu pun angka DHC yang
dihitung di sini, hanya penyajian ulang geometri yang sudah ada.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import cv2
import numpy as np

from .config import Config, DEFAULT_CONFIG
from .features import Tooth

# ---- role: menentukan warna di app ----
ROLE_TOOTH = "tooth"              # cyan    -- mask segmentasi biasa
ROLE_FLAGGED = "flagged"          # oranye  -- gigi yang ditandai sebuah aturan
ROLE_ANCHOR = "anchor"            # magenta -- KELUARAN DETECTOR (kaninus / distal)
ROLE_REFERENCE = "reference"      #         -- gigi yang BENAR-BENAR dipakai mengukur
ROLE_MEASUREMENT = "measurement"  # merah   -- garis tempat sebuah nilai diukur
ROLE_ARCH_CURVE = "archCurve"     # kuning  -- kurva lengkung hasil fit
ROLE_GAP = "gap"                  # merah   -- dugaan celah gigi hilang
ROLE_REJECTED = "rejected"        # abu2 putus-putus -- mask yang DIBUANG pipeline

# `anchor` vs `reference` sengaja dipisah jadi dua role (usul tim app): kalau box
# detector dan gigi yang dipakai mengukur TIDAK bertumpuk, itu sendiri informasi
# penting -- dua warna berbeda menunjukkannya seketika, sementara awalan teks
# kecil di layar HP tidak terbaca.

# ---- params: kunci parameter, sama persis dengan response utama ----
P_OVERJET = "overjet"
P_OVERBITE = "overbite"
P_ANTERIOR_CB = "anterior_crossbite"
P_ANGLE = "angle"
P_CROSSBITE_POST = "crossbite_posterior"
P_MISSING = "missing"
P_CROWDING = "crowding"

# Satu box insisivus melayani tiga parameter sekaligus -- itu sebabnya `params`
# berupa daftar, bukan string tunggal.
# Insisivus sentral mendasari Overjet & Overbite. Crossbite anterior TIDAK lagi
# ikut di sini -- sejak revisi C-ke-C, dia diperiksa di posisi 1-3 sendiri dan
# gigi yang bermasalah ditandai terpisah dengan role `flagged`.
INCISOR_PARAMS = [P_OVERJET, P_OVERBITE]
LATERAL_PARAMS = INCISOR_PARAMS + [P_ANGLE]
OCCLUSAL_PARAMS = [P_MISSING, P_CROWDING]

# `params` kosong = selalu tampil, apa pun parameter yang sedang dibuka.
ALWAYS = []


# --------------------------------------------------------------------------
# primitif
# --------------------------------------------------------------------------

def _pt(x: float, y: float, w: int, h: int, nd: int) -> List[float]:
    """Piksel -> pecahan 0-1, dijepit ke rentang supaya app tidak menggambar keluar kanvas."""
    return [
        round(min(max(float(x) / w, 0.0), 1.0), nd),
        round(min(max(float(y) / h, 0.0), 1.0), nd),
    ]


def _shape(kind: str, role: str, points: List[List[float]],
           params: Sequence[str], label: Optional[str] = None) -> Dict[str, Any]:
    return {"kind": kind, "role": role, "label": label,
            "params": list(params), "points": points}


def polygon(pts: np.ndarray, w: int, h: int, role: str, cfg: Config,
            params: Sequence[str] = ALWAYS, label: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Kontur mask -> poligon yang disederhanakan.

    Tanpa `approxPolyDP`, satu gigi bisa ~130 titik dan satu view jadi ratusan kB.
    Pada eps 0.01 bentuknya tetap terjaga di ~11 titik per gigi.
    Titik pertama TIDAK diulang di akhir -- app menutup poligon sendiri.
    """
    contour = np.asarray(pts, dtype=np.float32)
    if len(contour) < 3:
        return None
    approx = cv2.approxPolyDP(contour, cfg.OVERLAY_EPS_FRAC * cv2.arcLength(contour, True), True)
    coords = [_pt(x, y, w, h, cfg.OVERLAY_COORD_DECIMALS) for x, y in approx.reshape(-1, 2)]
    if len(coords) < 3:
        return None
    return _shape("polygon", role, coords, params, label)


def box(x0: float, y0: float, x1: float, y1: float, w: int, h: int, role: str, cfg: Config,
        params: Sequence[str] = ALWAYS, label: Optional[str] = None) -> Dict[str, Any]:
    """Tepat 2 titik: kiri-atas lalu kanan-bawah (urutan dinormalkan)."""
    nd = cfg.OVERLAY_COORD_DECIMALS
    lo_x, hi_x = (x0, x1) if x0 <= x1 else (x1, x0)
    lo_y, hi_y = (y0, y1) if y0 <= y1 else (y1, y0)
    return _shape("box", role, [_pt(lo_x, lo_y, w, h, nd), _pt(hi_x, hi_y, w, h, nd)], params, label)


def line(points: Sequence[Sequence[float]], w: int, h: int, role: str, cfg: Config,
         params: Sequence[str] = ALWAYS, label: Optional[str] = None) -> Optional[Dict[str, Any]]:
    nd = cfg.OVERLAY_COORD_DECIMALS
    coords = [_pt(x, y, w, h, nd) for x, y in points]
    return _shape("line", role, coords, params, label) if len(coords) >= 2 else None


def _subsample(xs: np.ndarray, ys: np.ndarray, n: int) -> List[List[float]]:
    """Ambil n titik merata dari kurva rapat; ujung-ujungnya selalu ikut."""
    idx = range(len(xs)) if len(xs) <= n else np.linspace(0, len(xs) - 1, n).astype(int)
    return [[float(xs[i]), float(ys[i])] for i in idx]


def _tooth_polys(feats: Sequence[Tooth], w: int, h: int, role: str, cfg: Config,
                 params: Sequence[str] = ALWAYS) -> List[Dict[str, Any]]:
    out = []
    for f in feats:
        shape = polygon(f["points"], w, h, role, cfg, params)
        if shape:
            out.append(shape)
    return out


# --------------------------------------------------------------------------
# per view
# --------------------------------------------------------------------------

def lateral_overlay(res: Optional[dict], cfg: Config) -> Optional[dict]:
    """Outline gigi + box detector + gigi yang dipakai mengukur + garis pengukuran."""
    if not res or "image_size" not in res:
        return None
    w, h = res["image_size"]
    shapes: List[Dict[str, Any]] = []

    teeth = [f for f, _pos in res.get("upper_result", [])] + \
            [f for f, _pos in res.get("lower_result", [])]
    shapes += _tooth_polys(teeth, w, h, ROLE_TOOTH, cfg, ALWAYS)

    # Keluaran detector apa adanya. Dipakai memeriksa Angle, karena penomoran
    # (dan karenanya kaninus posisi-3) berangkat dari anchor ini.
    for b in res.get("detector_boxes", []):
        if "xyxy" not in b:
            continue
        x0, y0, x1, y1 = b["xyxy"]
        shapes.append(box(x0, y0, x1, y1, w, h, ROLE_ANCHOR, cfg,
                          [P_ANGLE], "canine" if b["cls"] == 0 else "distal"))

    # Gigi yang BENAR-BENAR dipakai menghitung. Ini yang membuat kegagalan bisa
    # diperiksa: pada kasus overjet 9.33, box detector terlihat wajar karena
    # detector-nya memang berhasil -- yang meleset adalah insisivus, yang
    # diturunkan dengan menghitung posisi dari kaninus lalu mendarat di serpihan.
    for key, label, params in (
        ("incisors", "incisor", INCISOR_PARAMS),
        ("molars", "molar", [P_ANGLE]),
        ("canines", "canine", [P_ANGLE]),
    ):
        pair = res.get(key)
        if not pair:
            continue
        for side in ("upper", "lower"):
            x0, y0, x1, y1 = pair[side]["bbox"]
            shapes.append(box(x0, y0, x1, y1, w, h, ROLE_REFERENCE, cfg, params, label))

    inc = res.get("incisors")
    if inc:
        ui, li = inc["upper"], inc["lower"]
        # Overjet diukur mendatar antara tepi mesial kedua insisivus. Garis ditarik
        # pada ketinggian tengah keduanya supaya terlihat menghubungkan apa.
        y_mid = (ui["bbox"][3] + li["bbox"][1]) / 2
        seg = line([[ui["bbox"][0], y_mid], [li["bbox"][0], y_mid]],
                   w, h, ROLE_MEASUREMENT, cfg, INCISOR_PARAMS)
        if seg:
            shapes.append(seg)
        # Overbite diukur tegak: tepi bawah insisivus atas -> tepi atas insisivus bawah.
        x_mid = (ui["centroid"][0] + li["centroid"][0]) / 2
        seg = line([[x_mid, ui["bbox"][3]], [x_mid, li["bbox"][1]]],
                   w, h, ROLE_MEASUREMENT, cfg, INCISOR_PARAMS)
        if seg:
            shapes.append(seg)

    # Crossbite anterior (C-ke-C): tandai gigi yang atasnya di belakang pasangan
    # bawahnya. Yang normal tidak perlu bentuk tambahan -- outline-nya sudah tampil.
    # Gigi yang bermasalah ditandai `flagged`; yang diperiksa tapi normal tetap
    # dikirim sebagai `reference`. Ini disengaja: keluhan awal dokter adalah
    # "cuma satu gigi yang dicek", jadi CAKUPAN pemeriksaan harus terlihat --
    # bukan cuma temuannya.
    for row in res.get("anterior_crossbite_rows", []):
        role = ROLE_FLAGGED if row["flagged"] else ROLE_REFERENCE
        for tooth in row["teeth"]:
            shp = polygon(tooth["points"], w, h, role, cfg,
                          [P_ANTERIOR_CB], str(row["posisi"]))
            if shp:
                shapes.append(shp)

    if cfg.OVERLAY_INCLUDE_REJECTED:
        shapes += _tooth_polys(res.get("dropped_masks", []), w, h, ROLE_REJECTED, cfg, LATERAL_PARAMS)

    return {"shapes": shapes} if shapes else None


def frontal_overlay(res: Optional[dict], cfg: Config) -> Optional[dict]:
    """Outline gigi, gigi ter-flag crossbite posterior, dan celah dugaan gigi hilang.

    Gigi ter-flag DISPLACEMENT sengaja tidak dikirim: `displacement` bukan salah
    satu parameter di response utama, jadi tidak ada layar yang bisa menampilkannya
    (disepakati tim app). Kalau nanti displacement jadi parameter tersendiri,
    tinggal ditambahkan dengan `params: ["displacement"]`.
    """
    if not res or "image_size" not in res:
        return None
    w, h = res["image_size"]
    shapes: List[Dict[str, Any]] = []

    crossbite_ids = set()
    cb = res.get("crossbite")
    if cb:
        for item in cb.get("flagged", []):
            for f in item.get("teeth", ()):
                crossbite_ids.add(id(f))

    for f in list(res.get("upper", [])) + list(res.get("lower", [])):
        if id(f) in crossbite_ids:
            shape = polygon(f["points"], w, h, ROLE_FLAGGED, cfg, [P_CROSSBITE_POST])
        else:
            shape = polygon(f["points"], w, h, ROLE_TOOTH, cfg, ALWAYS)
        if shape:
            shapes.append(shape)

    # Celah dugaan gigi hilang: kotak yang membentang di antara dua gigi bertetangga.
    for arch in ("upper", "lower"):
        for a, b, _ratio in res.get("gaps", {}).get(arch, []):
            shapes.append(box(
                a["bbox"][2], min(a["bbox"][1], b["bbox"][1]),
                b["bbox"][0], max(a["bbox"][3], b["bbox"][3]),
                w, h, ROLE_GAP, cfg, [P_MISSING],
            ))

    return {"shapes": shapes} if shapes else None


def occlusal_overlay(res: Optional[dict], cfg: Config) -> Optional[dict]:
    """Outline gigi + gigi crowding + kurva lengkung + celah.

    `label` pada gigi ter-flag memakai indeks yang SAMA dengan `crowding.*.flagged_teeth`
    di response, sehingga angka dan sorotan di layar pasti merujuk gigi yang sama.
    """
    if not res or "image_size" not in res:
        return None
    w, h = res["image_size"]
    shapes: List[Dict[str, Any]] = []

    crowding = res.get("crowding")
    labels: Dict[int, str] = {}
    if crowding and crowding.get("chain"):
        chain = crowding["chain"]
        for idx in crowding.get("flagged_teeth", []):
            if 1 <= idx <= len(chain):          # indeks 1-based di sepanjang rantai
                labels[id(chain[idx - 1])] = str(idx)

    for f in res.get("feats", []):
        if id(f) in labels:
            shape = polygon(f["points"], w, h, ROLE_FLAGGED, cfg, [P_CROWDING], labels[id(f)])
        else:
            shape = polygon(f["points"], w, h, ROLE_TOOTH, cfg, ALWAYS)
        if shape:
            shapes.append(shape)

    missing = res.get("missing")
    if missing:
        xs, ys = missing["xs_curve"], missing["ys_curve"]
        # Kurva selalu tampil: celah digambar menempel padanya, tanpa kurvanya
        # posisi celah jadi sulit dibaca.
        curve = line(_subsample(xs, ys, cfg.OVERLAY_ARCH_CURVE_POINTS),
                     w, h, ROLE_ARCH_CURVE, cfg, ALWAYS)
        if curve:
            shapes.append(curve)
        for g in missing.get("gaps", []):
            i0, i1 = g["idx_range"]
            seg = line(_subsample(xs[i0:i1 + 1], ys[i0:i1 + 1], cfg.OVERLAY_GAP_LINE_POINTS),
                       w, h, ROLE_GAP, cfg, [P_MISSING])
            if seg:
                shapes.append(seg)

        if cfg.OVERLAY_INCLUDE_REJECTED:
            shapes += _tooth_polys(missing.get("removed_masks", []), w, h,
                                   ROLE_REJECTED, cfg, OCCLUSAL_PARAMS)

    return {"shapes": shapes} if shapes else None


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def build_overlays(
    *,
    lat_right: Optional[dict],
    lat_left: Optional[dict],
    frontal: Optional[dict],
    occ_upper: Optional[dict],
    occ_lower: Optional[dict],
    cfg: Config = DEFAULT_CONFIG,
) -> Dict[str, Any]:
    """Kunci memakai nama field unggahan yang sama, jadi app tidak perlu tabel terjemahan.

    `None` untuk sebuah view berarti "tidak ada anotasi" -- itu wajar, bukan kegagalan.
    """
    if not cfg.OVERLAY_ENABLED:
        return {k: None for k in
                ("frontal", "lateral_kanan", "lateral_kiri", "oklusal_atas", "oklusal_bawah")}
    return {
        "frontal": frontal_overlay(frontal, cfg),
        "lateral_kanan": lateral_overlay(lat_right, cfg),
        "lateral_kiri": lateral_overlay(lat_left, cfg),
        "oklusal_atas": occlusal_overlay(occ_upper, cfg),
        "oklusal_bawah": occlusal_overlay(occ_lower, cfg),
    }
