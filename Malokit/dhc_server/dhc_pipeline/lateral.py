"""Overjet, Overbite, Angle -- dari foto lateral.

Port langsung dari `11_app_simulation.ipynb` Section 4.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image
from sklearn.cluster import KMeans

from . import models
from .config import Config, DEFAULT_CONFIG
from .imaging import open_image
from .features import (
    Tooth,
    bbox_area,
    drop_edge_slivers,
    filter_spurious_instances,
    instance_features_from_mask,
    median_area,
    split_arch_kmeans,
)

Numbered = List[Tuple[Tooth, Optional[int]]]


# --------------------------------------------------------------------------
# anchor: kaninus + gigi paling distal
# --------------------------------------------------------------------------

def dedupe_top1_per_arch_boxes(boxes: List[dict]) -> List[dict]:
    """Sisakan 1 box terbaik per (kelas, lengkung).

    Detector kadang menandai beberapa kandidat kaninus dalam satu lengkung; tanpa
    dedupe, anchor bisa jatuh ke kandidat dengan confidence rendah.
    """
    if not boxes:
        return []
    if len(boxes) < 2:
        arch = [0]
    else:
        ys = np.array([[b["cy"]] for b in boxes])
        km = KMeans(n_clusters=2, n_init=10, random_state=0).fit(ys)
        upper_label = int(np.argmin(km.cluster_centers_.flatten()))
        arch = [0 if l == upper_label else 1 for l in km.labels_]
    for b, a in zip(boxes, arch):
        b["arch"] = a
    best: Dict[tuple, dict] = {}
    for b in boxes:
        key = (b["cls"], b["arch"])
        if key not in best or b["conf"] > best[key]["conf"]:
            best[key] = b
    return list(best.values())


def resolve_canine_anchor(arch, anchors, arch_feats_map) -> Tuple[Optional[Tooth], str]:
    """Ambil kaninus lengkung ini; kalau tak ada, tebak dari kaninus lengkung seberang.

    Jalur "cross" ini yang menyelamatkan sebagian besar foto -- detector hanya
    menemukan kaninus lengkap (atas+bawah) di ~75% foto.
    """
    other = "lower" if arch == "upper" else "upper"
    canine_f = anchors[arch]["canine"]
    if canine_f is not None:
        return canine_f, "direct"
    other_canine_f = anchors[other]["canine"]
    arch_feats = arch_feats_map[arch]
    if other_canine_f is None or not arch_feats:
        return None, "none"
    ref_x = other_canine_f["centroid"][0]
    return min(arch_feats, key=lambda f: abs(f["centroid"][0] - ref_x)), "cross"


def resolve_distal_anchor(arch, anchors, arch_feats_map, canine_f, direction) -> Tuple[Optional[Tooth], str]:
    distal_f = anchors[arch]["distal_most"]
    if distal_f is not None:
        return distal_f, "direct"
    af = arch_feats_map[arch]
    if not af or direction is None or canine_f is None:
        return None, "none"
    candidates = [f for f in af if f is not canine_f]
    if not candidates:
        return None, "none"
    return max(candidates, key=lambda f: f["centroid"][0] * direction), "seg_fallback"


def determine_photo_direction(anchors) -> Optional[int]:
    """+1 kalau distal ada di kanan gambar, -1 kalau di kiri (foto lateral kiri vs kanan)."""
    for arch in ("upper", "lower"):
        c = anchors[arch]["canine"]
        d = anchors[arch]["distal_most"]
        if c is not None and d is not None:
            return 1 if d["centroid"][0] > c["centroid"][0] else -1
    return None


def number_by_anchors(arch_feats: Sequence[Tooth], canine_f: Tooth, distal_f: Tooth) -> Numbered:
    """Nomori gigi: kaninus = posisi 3, lalu `pos = 3 + (i - canine_idx)` ke arah mesial.

    Gigi di luar rentang 1-8 diberi `None` -- ini yang membuang gigi sisi SEBERANG
    yang ikut terlihat di tepi foto lateral. Itu perilaku yang benar, bukan bug.
    """
    sign = 1 if distal_f["centroid"][0] > canine_f["centroid"][0] else -1
    ordered = sorted(arch_feats, key=lambda f: f["centroid"][0] * sign)
    canine_idx = next(i for i, f in enumerate(ordered) if f is canine_f)
    out: Numbered = []
    for i, f in enumerate(ordered):
        pos = 3 + (i - canine_idx)
        out.append((f, pos if 1 <= pos <= 8 else None))
    return out


# --------------------------------------------------------------------------
# ambil gigi pada posisi tertentu
# --------------------------------------------------------------------------

def _find_pos(result: Numbered, pos: int) -> Optional[Tooth]:
    for f, p in result:
        if p == pos:
            return f
    return None


def get_pair(upper_result: Numbered, lower_result: Numbered, pos: int) -> Optional[Tuple[Tooth, Tooth]]:
    u, l = _find_pos(upper_result, pos), _find_pos(lower_result, pos)
    return None if (u is None or l is None) else (u, l)


def mesial_direction_from_fdi(upper_result: Numbered) -> int:
    pos_map = {p: f for f, p in upper_result if p is not None}
    if 1 not in pos_map:
        return 1
    max_pos = max(pos_map)
    return 1 if pos_map[1]["centroid"][0] <= pos_map[max_pos]["centroid"][0] else -1


# --------------------------------------------------------------------------
# rumus
# --------------------------------------------------------------------------

def compute_overjet_proxy(upper_incisor: Tooth, lower_incisor: Tooth, direction: int) -> float:
    """Selisih tepi mesial insisivus atas vs bawah / lebar insisivus atas.

    Pakai TEPI bbox, bukan centroid: centroid bergeser kalau lebar crown atas dan
    bawah berbeda, sehingga hasilnya bias.
    """
    upper_x = upper_incisor["bbox"][0] if direction == 1 else upper_incisor["bbox"][2]
    lower_x = lower_incisor["bbox"][0] if direction == 1 else lower_incisor["bbox"][2]
    return float(((lower_x - upper_x) * direction) / upper_incisor["width"])


def compute_overbite_proxy(upper_incisor: Tooth, lower_incisor: Tooth) -> float:
    dy = upper_incisor["bbox"][3] - lower_incisor["bbox"][1]
    return float(dy / upper_incisor["height"])


def compute_relationship_proxy(
    upper_t: Tooth, lower_t: Tooth, direction: int, cfg: Config
) -> Tuple[float, str]:
    """Relasi antero-posterior -- dipakai untuk molar (pos 6) MAUPUN kaninus (pos 3)."""
    upper_mesial_x = upper_t["bbox"][0] if direction == 1 else upper_t["bbox"][2]
    lower_mesial_x = lower_t["bbox"][0] if direction == 1 else lower_t["bbox"][2]
    ratio = float(((lower_mesial_x - upper_mesial_x) * direction) / upper_t["width"])
    if ratio > cfg.ANGLE_THRESHOLD:
        label = "resembles Class II"
    elif ratio < -cfg.ANGLE_THRESHOLD:
        label = "resembles Class III"
    else:
        label = "resembles Class I"
    return ratio, label


def overjet_label(proxy: float, cfg: Config) -> str:
    if proxy < cfg.OVERJET_LOW:
        return "possible anterior crossbite"
    if proxy > cfg.OVERJET_HIGH:
        return "possible excess overjet"
    return "possible normal overjet"


def overbite_label(proxy: float, cfg: Config) -> str:
    if proxy < cfg.OVERBITE_LOW:
        return "possible open bite"
    if proxy > cfg.OVERBITE_HIGH:
        return "possible deep bite"
    return "possible normal overbite"


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def analyze_lateral(img_path: Path, cfg: Config = DEFAULT_CONFIG) -> Dict[str, Any]:
    """Satu foto lateral -> overjet, overbite, angle (molar & kaninus) + peringatan.

    Kunci yang berhubungan dengan pengukuran bisa TIDAK ADA kalau anchor gagal --
    itu hasil yang normal dan sering (7 dari 44 foto pada audit), bukan error.
    """
    # Dibuka sekali lalu objeknya dioper ke YOLO (bukan path) supaya format yang
    # butuh decoder tambahan -- terutama HEIC dari iPhone -- ikut tertangani.
    # Sudah diverifikasi: hasil mask lewat objek PIL identik dengan lewat path.
    image = open_image(img_path)
    seg = models.lateral_seg(cfg).predict(
        source=image, conf=cfg.SEG_CONF, iou=cfg.SEG_IOU, verbose=False
    )[0]
    feats = [] if seg.masks is None else [instance_features_from_mask(xy) for xy in seg.masks.xy]
    feats = filter_spurious_instances(feats, cfg)
    kept = drop_edge_slivers(feats, image.width, image.height, cfg)
    # Fragmen yang dibuang disimpan, bukan dilupakan: inilah bukti visual paling
    # langsung kenapa sebuah hasil ditandai tidak andal (mis. serpihan di luar
    # mulut yang pernah terpilih jadi anchor insisivus -> overjet 9.33).
    dropped_ids = {id(f) for f in kept}
    dropped = [f for f in feats if id(f) not in dropped_ids]
    feats = kept

    upper, lower = split_arch_kmeans(feats)
    arch_feats_map = {"upper": upper, "lower": lower}

    det = models.detector(cfg).predict(
        source=image,
        conf=min(cfg.DET_CONF_CANINE, cfg.DET_CONF_DISTAL),
        iou=cfg.DET_IOU,
        verbose=False,
        augment=cfg.DET_AUGMENT,
    )[0]
    raw_boxes: List[dict] = []
    if det.boxes is not None:
        for box in det.boxes:
            cls = int(box.cls.item())
            conf = float(box.conf.item())
            if conf < (cfg.DET_CONF_CANINE if cls == 0 else cfg.DET_CONF_DISTAL):
                continue
            x0, y0, x1, y1 = box.xyxy[0].tolist()
            raw_boxes.append({
                "cls": cls, "conf": conf,
                "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2,
                "xyxy": (x0, y0, x1, y1),   # disimpan untuk overlay role "anchor"
            })
    deduped = dedupe_top1_per_arch_boxes(raw_boxes)

    anchors = {
        "upper": {"canine": None, "distal_most": None},
        "lower": {"canine": None, "distal_most": None},
    }
    for db in deduped:
        cat = "canine" if db["cls"] == 0 else "distal_most"
        best_f, best_arch, best_d = None, None, 1e18
        for arch, fl in arch_feats_map.items():
            for f in fl:
                d = abs(f["centroid"][0] - db["cx"]) + abs(f["centroid"][1] - db["cy"])
                if d < best_d:
                    best_d, best_f, best_arch = d, f, arch
        if best_f is not None:
            anchors[best_arch][cat] = best_f

    direction = determine_photo_direction(anchors)
    arch_results: Dict[str, Numbered] = {}
    n_canine_direct = 0
    for arch in ("upper", "lower"):
        canine_f, canine_src = resolve_canine_anchor(arch, anchors, arch_feats_map)
        distal_f, _ = resolve_distal_anchor(arch, anchors, arch_feats_map, canine_f, direction)
        if canine_src == "direct":
            n_canine_direct += 1
        af = arch_feats_map[arch]
        arch_results[arch] = (
            number_by_anchors(af, canine_f, distal_f)
            if (canine_f is not None and distal_f is not None)
            else [(f, None) for f in af]
        )

    result: Dict[str, Any] = {
        "n_teeth": len(feats),
        "n_canine_direct": n_canine_direct,
        "upper_result": arch_results["upper"],
        "lower_result": arch_results["lower"],
        "warnings": [],
        # --- bahan overlay (tidak dipakai perhitungan) ---
        "image_size": (image.width, image.height),
        # Yang dikirim ke overlay adalah box SETELAH dedupe -- yaitu yang benar-benar
        # jadi anchor pengukuran. Mengirim semua kandidat mentah justru menyesatkan:
        # klinisi tidak bisa tahu box mana yang mendasari angkanya.
        "detector_boxes": deduped,
        "dropped_masks": dropped,
    }

    incisors = get_pair(arch_results["upper"], arch_results["lower"], 1)
    direction2 = mesial_direction_from_fdi(arch_results["upper"])

    if incisors is not None:
        ui, li = incisors
        result["overjet"] = compute_overjet_proxy(ui, li, direction2)
        result["overjet_label"] = overjet_label(result["overjet"], cfg)
        result["overbite"] = compute_overbite_proxy(ui, li)
        result["overbite_label"] = overbite_label(result["overbite"], cfg)
        result["incisors"] = {"upper": ui, "lower": li}

        # --- guard kualitas ---
        # (1) mask insisivus jauh lebih kecil dari gigi lain -> kemungkinan yang
        #     terambil serpihan/noise, bukan insisivus asli.
        # (2) angka di luar rentang yang mungkin secara klinis.
        # Nilainya TETAP dilaporkan, tapi ditandai tidak andal -- lebih berguna
        # daripada disembunyikan.
        all_feats = [f for f, _ in arch_results["upper"]] + [f for f, _ in arch_results["lower"]]
        med = median_area(all_feats)

        def area_ratio(f: Tooth) -> float:
            return bbox_area(f) / med if med else 1.0

        if area_ratio(ui) < cfg.INCISOR_MIN_AREA_RATIO:
            result["warnings"].append("upper incisor mask is tiny (anchor likely wrong)")
        if area_ratio(li) < cfg.INCISOR_MIN_AREA_RATIO:
            result["warnings"].append("lower incisor mask is tiny (anchor likely wrong)")
        if abs(result["overjet"]) > cfg.OVERJET_PLAUSIBLE:
            result["warnings"].append(
                f"|overjet| = {abs(result['overjet']):.2f} exceeds plausible range "
                f"({cfg.OVERJET_PLAUSIBLE})"
            )
        if abs(result["overbite"]) > cfg.OVERBITE_PLAUSIBLE:
            result["warnings"].append(
                f"|overbite| = {abs(result['overbite']):.2f} exceeds plausible range "
                f"({cfg.OVERBITE_PLAUSIBLE})"
            )
    else:
        result["warnings"].append("canine anchor not detected, incisor position unavailable")

    result["reliable"] = incisors is not None and not result["warnings"]

    # --- Crossbite anterior: C-ke-C (posisi 1-3), bukan hanya insisivus sentral ---
    # Tiap posisi diperiksa sendiri; satu saja negatif sudah cukup. Barisnya
    # disimpan lengkap (termasuk yang normal) supaya overlay bisa menunjukkan
    # gigi mana yang diperiksa, bukan cuma yang bermasalah.
    ac_rows = []
    for pos in cfg.ANTERIOR_CROSSBITE_POSITIONS:
        pair = get_pair(arch_results["upper"], arch_results["lower"], pos)
        if pair is None:
            continue
        ratio = compute_overjet_proxy(pair[0], pair[1], direction2)
        ac_rows.append({
            "posisi": pos,
            "ratio": ratio,
            "flagged": ratio < cfg.ANTERIOR_CROSSBITE_THRESHOLD,
            "teeth": pair,
        })
    result["anterior_crossbite_rows"] = ac_rows

    molars = get_pair(arch_results["upper"], arch_results["lower"], 6)
    if molars is not None:
        result["molar_ratio"], result["molar_label"] = compute_relationship_proxy(
            molars[0], molars[1], direction2, cfg
        )
        result["molars"] = {"upper": molars[0], "lower": molars[1]}

    canines = get_pair(arch_results["upper"], arch_results["lower"], 3)
    if canines is not None:
        result["canine_ratio"], result["canine_label"] = compute_relationship_proxy(
            canines[0], canines[1], direction2, cfg
        )
        result["canines"] = {"upper": canines[0], "lower": canines[1]}

    return result
