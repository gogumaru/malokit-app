"""Muat & cache 4 model YOLO.

Model dimuat sekali lalu dipakai ulang -- memuat ulang tiap request bikin latensi
naik beberapa detik tanpa manfaat apa pun.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict

from .config import Config, DEFAULT_CONFIG

log = logging.getLogger(__name__)

_cache: Dict[str, object] = {}
_lock = threading.Lock()


def _load(path) -> object:
    from ultralytics import YOLO  # impor di dalam fungsi -- torch berat, jangan saat import modul

    key = str(path)
    with _lock:
        if key not in _cache:
            if not path.exists():
                raise FileNotFoundError(
                    f"Bobot model tidak ditemukan: {path}\n"
                    "Cek path di dhc_pipeline/config.py, atau salin file .pt ke lokasi itu."
                )
            log.info("memuat model: %s", path)
            _cache[key] = YOLO(str(path))
        return _cache[key]


def lateral_seg(cfg: Config = DEFAULT_CONFIG):
    return _load(cfg.lateral_seg_weights)


def frontal_seg(cfg: Config = DEFAULT_CONFIG):
    return _load(cfg.frontal_seg_weights)


def occlusal_seg(cfg: Config = DEFAULT_CONFIG):
    return _load(cfg.occlusal_seg_weights)


def detector(cfg: Config = DEFAULT_CONFIG):
    return _load(cfg.detector_weights)


def warmup(cfg: Config = DEFAULT_CONFIG) -> None:
    """Muat semua model di awal (dipanggil saat server start).

    Tanpa ini, request pertama menanggung beban muat 4 model sekaligus dan bisa
    kelihatan seperti timeout dari sisi app.
    """
    lateral_seg(cfg)
    frontal_seg(cfg)
    occlusal_seg(cfg)
    detector(cfg)
    log.info("4 model siap")


def missing_weights(cfg: Config = DEFAULT_CONFIG) -> list[str]:
    """Daftar bobot yang tidak ada -- dipakai endpoint /v1/health."""
    paths = {
        "lateral_seg": cfg.lateral_seg_weights,
        "frontal_seg": cfg.frontal_seg_weights,
        "occlusal_seg": cfg.occlusal_seg_weights,
        "detector": cfg.detector_weights,
    }
    return [f"{name}: {path}" for name, path in paths.items() if not path.exists()]
