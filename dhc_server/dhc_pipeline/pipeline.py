"""Orkestrasi: 5 foto masuk -> satu response JSON keluar."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

from .config import Config, DEFAULT_CONFIG
from .frontal import analyze_frontal
from .imaging import UnreadableImage
from .lateral import analyze_lateral
from .occlusal import analyze_occlusal
from .report import build_response

log = logging.getLogger(__name__)

PathLike = Union[str, Path]


def _safe(fn, img_path: PathLike, cfg: Config, what: str, failures: dict) -> Optional[dict]:
    """Jalankan satu analisis; kalau meledak, kembalikan None dan CATAT sebabnya.

    Satu foto rusak tidak boleh menggagalkan seluruh laporan -- parameter yang
    bergantung padanya cukup dilaporkan sebagai "tidak bisa dihitung"
    (API contract 4.4 & 4.5).

    Sebab kegagalan dikumpulkan di `failures` supaya, kalau SEMUA foto gagal,
    pesan errornya bisa menyebutkan penyebab konkretnya -- bukan sekadar
    "semua analisis gagal" yang tidak bisa ditindaklanjuti.
    """
    try:
        return fn(Path(img_path), cfg)
    except UnreadableImage as exc:
        # sebab yang sudah jelas & layak ditampilkan ke pengguna
        log.warning("analisis %s gagal: %s", what, exc)
        failures[what] = str(exc)
        return None
    except Exception as exc:
        log.exception("analisis %s gagal untuk %s", what, img_path)
        failures[what] = f"{type(exc).__name__}: {exc}"
        return None


def analyze_patient(
    *,
    frontal: PathLike,
    lateral_kanan: PathLike,
    lateral_kiri: PathLike,
    oklusal_atas: PathLike,
    oklusal_bawah: PathLike,
    patient_id: Optional[str] = None,
    config: Optional[Config] = None,
    config_overrides: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Analisis satu pasien.

    `oklusal_atas` / `oklusal_bawah` harus sudah benar dari pemanggil -- pipeline
    tidak menebak-nebak (lihat catatan di `__init__.py`).
    """
    cfg = (config or DEFAULT_CONFIG).merged(config_overrides)

    failures: Dict[str, str] = {}
    lat_right = _safe(analyze_lateral, lateral_kanan, cfg, "lateral_kanan", failures)
    lat_left = _safe(analyze_lateral, lateral_kiri, cfg, "lateral_kiri", failures)
    front = _safe(analyze_frontal, frontal, cfg, "frontal", failures)
    occ_upper = _safe(analyze_occlusal, oklusal_atas, cfg, "oklusal_atas", failures)
    occ_lower = _safe(analyze_occlusal, oklusal_bawah, cfg, "oklusal_bawah", failures)

    if all(r is None for r in (lat_right, lat_left, front, occ_upper, occ_lower)):
        # Kalau semua foto gagal karena sebab yang sama, sebutkan sekali saja --
        # itu hampir selalu masalah format berkas, bukan masalah per-foto.
        unique = set(failures.values())
        detail = (
            unique.pop() if len(unique) == 1
            else "; ".join(f"{view}: {why}" for view, why in failures.items())
        )
        raise RuntimeError(f"tidak ada satu pun foto yang bisa dianalisis -- {detail}")

    return build_response(
        patient_id=patient_id,
        lat_right=lat_right,
        lat_left=lat_left,
        frontal=front,
        occ_upper=occ_upper,
        occ_lower=occ_lower,
        cfg=cfg,
    )
