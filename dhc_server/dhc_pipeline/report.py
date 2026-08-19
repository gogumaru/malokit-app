"""Gabungkan hasil semua modul jadi satu response sesuai `API_CONTRACT.md`.

Semua aturan pelaporan yang tidak boleh dilanggar ada di sini, dikumpulkan di satu
tempat supaya mudah diaudit:

1. `value: null` berarti TIDAK BISA DIHITUNG. Jangan pernah kirim `0` untuk itu --
   `0` adalah pengukuran yang sah.
2. `reliable` harus jujur. Kalau guard menyala, `reliable: false` walaupun angkanya
   ada. App memang dirancang untuk menampilkan nilai tidak andal, bukan
   menyembunyikannya.
3. Molar & kaninus dilaporkan TERPISAH; tidak dipaksa jadi satu kelas Angle.
4. Missing dari oklusal & frontal dilaporkan dua-duanya; tidak ada yang dipilih diam-diam.
5. Overjet/overbite pakai aturan sisi TERBURUK, tapi sisi yang bermasalah tidak
   boleh dipilih diam-diam kalau ada sisi yang bersih.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .config import Config, DEFAULT_CONFIG
from .overlays import build_overlays

ENGINE_VERSION = "dhc-pipeline 0.1.0"

# Peta sisi: internal pakai bahasa Indonesia, kontrak API pakai bahasa Inggris.
SIDE_ID_TO_EN = {"kanan": "right", "kiri": "left"}


def reading(
    value: Optional[float] = None,
    label: Optional[str] = None,
    side: Optional[str] = None,
    reliable: bool = False,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Bentuk `Reading` standar -- dipakai semua parameter terukur.

    Menegakkan aturan #1 & #2: kalau `value` None, `reliable` dipaksa False.
    """
    if value is None:
        reliable = False
    return {
        "value": None if value is None else round(float(value), 4),
        "label": label,
        "side": side,
        "reliable": bool(reliable),
        "warnings": list(warnings or []),
    }


def _severity(value: float, low: float, high: float) -> float:
    """Seberapa jauh sebuah nilai keluar dari rentang normal."""
    return max(low - value, 0.0, value - high)


def _pick_worst_side(
    candidates: List[tuple], low: float, high: float
) -> Optional[tuple]:
    """Aturan sisi terburuk, tapi sisi bermasalah tidak dipilih diam-diam.

    `candidates` = [(side_en, value, label, reliable, warnings), ...]

    Kalau ada sisi yang bersih, HANYA sisi bersih yang diperebutkan. Kalau semuanya
    bermasalah, tetap dilaporkan (dengan `reliable: false`) -- bukan disembunyikan.
    """
    if not candidates:
        return None
    reliable_only = [c for c in candidates if c[3]]
    pool = reliable_only or candidates
    return max(pool, key=lambda c: _severity(c[1], low, high))


def _lateral_candidates(lat_right, lat_left, value_key: str, label_key: str) -> List[tuple]:
    out = []
    for side_id, res in (("kanan", lat_right), ("kiri", lat_left)):
        if res is None or value_key not in res:
            continue
        out.append((
            SIDE_ID_TO_EN[side_id],
            res[value_key],
            res.get(label_key),
            res.get("reliable", False),
            res.get("warnings", []),
        ))
    return out


def _no_reading_warnings(lat_right, lat_left) -> List[str]:
    """Kumpulkan alasan kenapa sebuah parameter lateral tidak bisa dihitung."""
    reasons = []
    for side_id, res in (("kanan", lat_right), ("kiri", lat_left)):
        if res is None:
            reasons.append(f"{SIDE_ID_TO_EN[side_id]} lateral: analysis failed")
            continue
        for w in res.get("warnings", []):
            reasons.append(f"{SIDE_ID_TO_EN[side_id]} lateral: {w}")
    return reasons or ["could not be computed from either lateral photo"]


# --------------------------------------------------------------------------
# bagian per parameter
# --------------------------------------------------------------------------

def _build_overjet_overbite(lat_right, lat_left, cfg: Config):
    oj_cands = _lateral_candidates(lat_right, lat_left, "overjet", "overjet_label")
    ob_cands = _lateral_candidates(lat_right, lat_left, "overbite", "overbite_label")

    oj_best = _pick_worst_side(oj_cands, cfg.OVERJET_LOW, cfg.OVERJET_HIGH)
    ob_best = _pick_worst_side(ob_cands, cfg.OVERBITE_LOW, cfg.OVERBITE_HIGH)

    if oj_best is None:
        overjet = reading(warnings=_no_reading_warnings(lat_right, lat_left))
    else:
        side, val, label, rel, warns = oj_best
        overjet = reading(val, label, side, rel, warns)

    if ob_best is None:
        overbite = reading(warnings=_no_reading_warnings(lat_right, lat_left))
    else:
        side, val, label, rel, warns = ob_best
        overbite = reading(val, label, side, rel, warns)

    return overjet, overbite, _build_anterior_crossbite(lat_right, lat_left, cfg)


def _build_anterior_crossbite(lat_right, lat_left, cfg: Config) -> Dict[str, Any]:
    """Crossbite anterior dari C-ke-C (posisi 1-3 di tiap lateral), bukan dari overjet.

    Revisi dokter: satu gigi saja yang atasnya di belakang pasangan bawahnya sudah
    cukup untuk menyebut crossbite. Jadi ini TIDAK lagi turunan overjet -- overjet
    hanya melihat insisivus sentral, dan itu terbukti melewatkan kasus nyata
    (pasien 2023.14: pos1 normal, tapi pos2 & pos3 crossbite).

    `value` = rasio PALING NEGATIF di antara semua posisi yang bisa diukur, jadi
    angkanya tetap satu besaran yang bisa dibandingkan antar pasien. Gigi mana yang
    terlibat ditunjukkan lewat overlay (role `flagged`, params `anterior_crossbite`).
    """
    worst = None       # (ratio, side_en, posisi, reliable, warnings)
    any_flagged = False
    measured = 0

    for side_id, res in (("kanan", lat_right), ("kiri", lat_left)):
        if res is None:
            continue
        for row in res.get("anterior_crossbite_rows", []):
            measured += 1
            if row["flagged"]:
                any_flagged = True
            cand = (row["ratio"], SIDE_ID_TO_EN[side_id], row["posisi"],
                    res.get("reliable", False), res.get("warnings", []))
            if worst is None or cand[0] < worst[0]:
                worst = cand

    if worst is None:
        return reading(warnings=_no_reading_warnings(lat_right, lat_left))

    ratio, side, posisi, rel, warns = worst
    warns = list(warns)
    # Kalau tidak semua enam gigi terukur, hasil "tidak ada crossbite" belum tentu
    # benar -- gigi yang tidak terukur bisa saja justru yang bermasalah.
    expected = 2 * len(cfg.ANTERIOR_CROSSBITE_POSITIONS)
    if measured < expected and not any_flagged:
        warns.append(
            f"only {measured} of {expected} anterior teeth could be measured; "
            "an unmeasured tooth could still be in crossbite"
        )
        rel = False

    return reading(
        ratio,
        "possible anterior crossbite" if any_flagged else "no anterior crossbite",
        side,
        rel,
        warns,
    )


def _angle_class(ratio: Optional[float], cfg: Config) -> Optional[str]:
    if ratio is None:
        return None
    if ratio > cfg.ANGLE_THRESHOLD:
        return "II"
    if ratio < -cfg.ANGLE_THRESHOLD:
        return "III"
    return "I"


def _build_angle(lat_right, lat_left, cfg: Config) -> Dict[str, Any]:
    """Pilih sisi untuk Angle: utamakan sisi yang molar & kaninus-nya berselisih.

    Perselisihan molar-vs-kaninus adalah sinyal klinis yang lebih penting daripada
    besar-kecilnya deviasi masing-masing, jadi sisi itu yang ditampilkan.
    """
    def side_score(res) -> float:
        if res is None:
            return -1.0
        m, c = res.get("molar_ratio"), res.get("canine_ratio")
        if m is not None and c is not None and _angle_class(m, cfg) != _angle_class(c, cfg):
            return float("inf")
        vals = [v for v in (m, c) if v is not None]
        if not vals:
            return -1.0
        return max(_severity(v, -cfg.ANGLE_THRESHOLD, cfg.ANGLE_THRESHOLD) for v in vals)

    cands = [(SIDE_ID_TO_EN["kanan"], lat_right), (SIDE_ID_TO_EN["kiri"], lat_left)]
    cands = [(s, r) for s, r in cands if r is not None and ("molar_ratio" in r or "canine_ratio" in r)]

    if not cands:
        return {
            "side": None,
            "molar": reading(warnings=["molar position not found in either lateral photo"]),
            "canine": reading(warnings=["canine position not found in either lateral photo"]),
            "disagreement": False,
        }

    side, res = max(cands, key=lambda c: side_score(c[1]))
    m_ratio, c_ratio = res.get("molar_ratio"), res.get("canine_ratio")

    molar = (
        reading(m_ratio, res.get("molar_label"), side, reliable=True)
        if m_ratio is not None
        else reading(warnings=["molar position not found"])
    )
    canine = (
        reading(c_ratio, res.get("canine_label"), side, reliable=True)
        if c_ratio is not None
        else reading(warnings=["canine position not found"])
    )

    # Aturan #3: disagreement hanya kalau KEDUANYA punya nilai dan kelasnya beda.
    disagreement = (
        m_ratio is not None
        and c_ratio is not None
        and _angle_class(m_ratio, cfg) != _angle_class(c_ratio, cfg)
    )
    if disagreement:
        note = "molar and canine imply different Angle classes, manual review needed"
        molar["warnings"].append(note)
        canine["warnings"].append(note)

    return {"side": side, "molar": molar, "canine": canine, "disagreement": disagreement}


def _build_crossbite(frontal) -> Dict[str, Any]:
    if frontal is None or frontal.get("crossbite") is None:
        return {
            "label": None,
            "reliable": False,
            "flagged": [],
            "warnings": ["not enough teeth segmented in the frontal photo"],
        }
    cb = frontal["crossbite"]
    flagged = [
        {"side": SIDE_ID_TO_EN[f["side"]], "posisi": f["posisi"], "ratio": round(f["ratio"], 4)}
        for f in cb["flagged"]
    ]
    return {"label": cb["label"], "reliable": True, "flagged": flagged, "warnings": []}


def _build_missing(frontal, occ_upper, occ_lower) -> Dict[str, Any]:
    """Aturan #4: laporkan dua-duanya, tandai kalau berselisih.

    Oklusal adalah sumber utama. Foto frontal secara fisik tidak bisa melihat area
    premolar-molar, jadi angkanya sering lebih kecil -- itu keterbatasan sudut foto,
    bukan bug.
    """
    occ_counts = [
        r["missing"]["n_gaps"]
        for r in (occ_upper, occ_lower)
        if r is not None and r.get("missing") is not None
    ]
    occlusal_gaps = sum(occ_counts) if occ_counts else None
    frontal_gaps = frontal["n_gaps"] if frontal is not None else None

    warnings: List[str] = []
    if occlusal_gaps is None:
        warnings.append("occlusal photos could not be analysed")
    if frontal_gaps is None:
        warnings.append("frontal photo could not be analysed")

    disagreement = (
        occlusal_gaps is not None and frontal_gaps is not None and occlusal_gaps != frontal_gaps
    )
    if disagreement:
        warnings.append(
            "occlusal and frontal counts disagree; occlusal is the primary source "
            "but a large difference needs manual review"
        )

    return {
        "occlusal_gaps": occlusal_gaps,
        "frontal_gaps": frontal_gaps,
        "disagreement": disagreement,
        "reliable": occlusal_gaps is not None and not disagreement,
        "warnings": warnings,
    }


def _build_crowding_arch(occ, is_lower: bool) -> Optional[Dict[str, Any]]:
    """Satu lengkung. `None` kalau lengkung itu tidak bisa dihitung.

    Lengkung BAWAH selalu membawa peringatan: ambang Little's Index dikalibrasi
    hanya dari data lengkung ATAS, jadi baseline "normal" untuk bawah belum teruji
    (lihat brief bagian 8.5).
    """
    if occ is None or occ.get("crowding") is None:
        return None
    c = occ["crowding"]
    warnings: List[str] = []
    if is_lower:
        warnings.append(
            "lower-arch threshold is not yet validated (calibrated on upper arch only)"
        )
    return {
        "sum": round(c["sum"], 4),
        "label": c["label"],
        "flagged_teeth": c["flagged_teeth"],
        "reliable": not is_lower,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def build_response(
    *,
    patient_id: Optional[str],
    lat_right: Optional[dict],
    lat_left: Optional[dict],
    frontal: Optional[dict],
    occ_upper: Optional[dict],
    occ_lower: Optional[dict],
    cfg: Config = DEFAULT_CONFIG,
) -> Dict[str, Any]:
    overjet, overbite, anterior = _build_overjet_overbite(lat_right, lat_left, cfg)
    return {
        "patient_id": patient_id,
        "engine_version": ENGINE_VERSION,
        "overjet": overjet,
        "overbite": overbite,
        "anterior_crossbite": anterior,
        "angle": _build_angle(lat_right, lat_left, cfg),
        "crossbite_posterior": _build_crossbite(frontal),
        "missing": _build_missing(frontal, occ_upper, occ_lower),
        "crowding": {
            "upper": _build_crowding_arch(occ_upper, is_lower=False),
            "lower": _build_crowding_arch(occ_lower, is_lower=True),
        },
        # Geometri untuk digambar app -- koordinat, bukan gambar jadi
        # (lihat `overlays.py` dan `API_CONTRACT_OVERLAYS.md`).
        "overlays": build_overlays(
            lat_right=lat_right,
            lat_left=lat_left,
            frontal=frontal,
            occ_upper=occ_upper,
            occ_lower=occ_lower,
            cfg=cfg,
        ),
    }
