"""Uji regresi: paket harus menghasilkan angka yang sama dengan notebook 11.

Angka acuan di bawah DIHASILKAN dengan menjalankan kode `11_app_simulation.ipynb`
apa adanya pada foto di `Dataset/app_simulation_patient/` (bukan ditulis manual). Kalau ada test di sini
yang gagal, artinya port-nya menyimpang dari riset -- perbaiki paketnya, JANGAN
ubah angka acuannya tanpa memahami sebabnya.

Perbedaan yang DISENGAJA terhadap notebook (satu-satunya):
    saat anchor kaninus gagal, paket menambahkan warning yang menjelaskan sebabnya,
    sementara notebook mengirim daftar warning kosong. Ini diminta API contract
    sect. 4.1. Semua nilai TERUKUR identik.

Jalankan:  pytest dhc_server/tests/test_regression.py -v
Butuh bobot model + folder Dataset; kalau tidak ada, test otomatis di-skip.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "dhc_server"))

SIM_ROOT = REPO / "Dataset" / "app_simulation_patient"

# Pasien yang kode file oklusalnya TERBALIK (4=atas, 5=bawah).
# Ditemukan lewat pengecekan visual manual -- 5 dari 13 pasien yang dites saat itu.
# Di aplikasi, hal ini tidak berlaku: app tahu foto mana yang atas dari alur pemotretan.
REVERSED_OKLUSAL = {"2021.04", "2023.14", "2018.08", "2018.73", "2018.57a"}

TOL = 1e-6

# (pasien, overjet_kanan, overbite_kanan, overjet_kiri, overbite_kiri)
LATERAL_REFERENCE = [
    ("2018.05", None, None, 1.5490, 0.3000),
    ("2018.08", 0.5000, 0.2297, None, None),
    ("2018.15", -0.2840, 0.0860, 1.2632, 0.1727),
    ("2018.56", 0.2185, 0.0067, -0.0094, 0.0764),
    ("2018.57a", 1.0822, -0.0152, 1.0349, -0.0145),
    ("2018.57b", 1.2115, 0.0000, -0.1449, 0.0625),
    ("2019.20", 0.9316, -0.0136, 0.0984, -0.0211),
    ("2021.04", 0.4157, 0.1698, 0.6667, 0.1652),
    ("2021.69", 0.4255, 0.0879, 0.6404, 0.2371),
    ("2023.25", -0.3250, 0.6032, -0.0526, 0.0690),
]

# (pasien, n_gap_oklusal_atas, n_gap_oklusal_bawah, crowding_sum_atas, crowding_sum_bawah)
OCCLUSAL_REFERENCE = [
    ("2018.08", 0, 0, 1.1604, 1.3962),
    ("2018.15", 0, 0, 1.6413, 1.3488),
    ("2018.100", 1, 0, 1.1334, 1.8311),
    ("2018.57a", 1, 0, 0.8485, 0.9673),
    ("2021.69", 0, 0, 0.9343, 2.1111),
]


def _photos(pid: str) -> dict:
    d = {p.stem[-1]: p for p in (SIM_ROOT / pid).glob("*.JPG")}
    if pid in REVERSED_OKLUSAL:
        bawah, atas = d.get("5"), d.get("4")
    else:
        bawah, atas = d.get("4"), d.get("5")
    return {
        "frontal": d.get("1"),
        "lateral_kanan": d.get("2"),
        "lateral_kiri": d.get("3"),
        "oklusal_atas": atas,
        "oklusal_bawah": bawah,
    }


def _require(pid: str) -> dict:
    if not SIM_ROOT.exists():
        pytest.skip(f"folder dataset tidak ada: {SIM_ROOT}")
    ph = _photos(pid)
    missing = [k for k, v in ph.items() if v is None]
    if missing:
        pytest.skip(f"{pid}: foto tidak lengkap ({missing})")
    return ph


def _approx(actual, expected):
    if expected is None:
        assert actual is None, f"harusnya tidak bisa dihitung, tapi dapat {actual}"
    else:
        assert actual is not None, "harusnya ada nilai, tapi dapat None"
        assert abs(actual - expected) < 1e-3, f"{actual} != {expected}"


@pytest.mark.parametrize("pid,oj_r,ob_r,oj_l,ob_l", LATERAL_REFERENCE)
def test_lateral_matches_notebook(pid, oj_r, ob_r, oj_l, ob_l):
    from dhc_pipeline.lateral import analyze_lateral

    ph = _require(pid)
    right = analyze_lateral(ph["lateral_kanan"])
    left = analyze_lateral(ph["lateral_kiri"])
    _approx(right.get("overjet"), oj_r)
    _approx(right.get("overbite"), ob_r)
    _approx(left.get("overjet"), oj_l)
    _approx(left.get("overbite"), ob_l)


@pytest.mark.parametrize("pid,gap_up,gap_low,crowd_up,crowd_low", OCCLUSAL_REFERENCE)
def test_occlusal_matches_notebook(pid, gap_up, gap_low, crowd_up, crowd_low):
    from dhc_pipeline.occlusal import analyze_occlusal

    ph = _require(pid)
    up = analyze_occlusal(ph["oklusal_atas"])
    low = analyze_occlusal(ph["oklusal_bawah"])
    assert up["missing"]["n_gaps"] == gap_up
    assert low["missing"]["n_gaps"] == gap_low
    _approx(up["crowding"]["sum"], crowd_up)
    _approx(low["crowding"]["sum"], crowd_low)


def test_anchor_failure_is_reported_not_silent():
    """Saat anchor gagal, harus ada penjelasannya -- ini beda yang disengaja dari notebook."""
    from dhc_pipeline.lateral import analyze_lateral

    ph = _require("2020.35")
    res = analyze_lateral(ph["lateral_kanan"])
    assert res.get("overjet") is None
    assert res["reliable"] is False
    assert res["warnings"], "kegagalan anchor harus dijelaskan, bukan diam-diam"
