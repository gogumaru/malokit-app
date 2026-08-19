"""Server HTTP untuk pipeline DHC -- implementasi `API_CONTRACT.md`.

Jalankan:
    cd dhc_server
    uvicorn app:app --host 0.0.0.0 --port 8000

Mode stub (tidak memuat model sama sekali, balas contoh statis):
    DHC_STUB=1 uvicorn app:app --port 8000

Endpoint:
    POST /v1/analyze   -- 5 foto masuk, satu JSON keluar
    GET  /v1/health    -- status server & ketersediaan bobot model
    GET  /v1/config    -- konstanta yang sedang berlaku (untuk debugging kalibrasi)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

from dhc_pipeline import DEFAULT_CONFIG, ENGINE_VERSION, analyze_patient
from dhc_pipeline import models as model_registry
from stub import stub_response

logging.basicConfig(
    level=os.getenv("DHC_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("dhc.server")

STUB_MODE = os.getenv("DHC_STUB", "").lower() in {"1", "true", "yes"}

# Nama field ini adalah IDENTITAS VIEW. Server mempercayainya apa adanya dan tidak
# pernah menebak ulang dari isi gambar atau EXIF -- app sudah tahu foto mana yang
# mana karena pemotretannya dipandu per langkah. Menebak-nebak di sini persis
# jebakan yang diperingatkan di brief bagian 1.
REQUIRED_VIEWS = ["frontal", "lateral_kanan", "lateral_kiri", "oklusal_atas", "oklusal_bawah"]

MAX_UPLOAD_BYTES = int(os.getenv("DHC_MAX_UPLOAD_MB", "25")) * 1024 * 1024

@asynccontextmanager
async def lifespan(_app: FastAPI):
    if STUB_MODE:
        log.warning("MODE STUB aktif -- foto diabaikan, balasan statis dari stub.py")
    else:
        missing = model_registry.missing_weights(DEFAULT_CONFIG)
        if missing:
            # Jangan bikin server gagal start: /v1/health harus tetap bisa dipanggil
            # supaya app bisa menampilkan pesan yang jelas, bukan connection refused.
            log.error("bobot model tidak lengkap:\n  %s", "\n  ".join(missing))
        else:
            log.info("memuat model di awal supaya request pertama tidak menanggung bebannya...")
            t0 = time.perf_counter()
            model_registry.warmup(DEFAULT_CONFIG)
            log.info("model siap dalam %.1f detik", time.perf_counter() - t0)
    yield


app = FastAPI(
    title="DHC pipeline",
    version=ENGINE_VERSION,
    description="Mengukur parameter maloklusi dari 5 foto intraoral. "
                "Alat bantu penelitian -- bukan alat diagnosis mandiri.",
    lifespan=lifespan,
)


# --------------------------------------------------------------------------
# health & config
# --------------------------------------------------------------------------

@app.get("/v1/health")
def health() -> Dict[str, Any]:
    missing = [] if STUB_MODE else model_registry.missing_weights(DEFAULT_CONFIG)
    return {
        "status": "ok" if not missing else "degraded",
        "stub_mode": STUB_MODE,
        "engine_version": ENGINE_VERSION,
        "missing_weights": missing,
    }


@app.get("/v1/config")
def config() -> Dict[str, Any]:
    """Konstanta yang sedang berlaku.

    Berguna saat tim riset menyetel kalibrasi di lapangan -- bisa dicek apakah
    override benar-benar sampai ke server.
    """
    from dataclasses import fields

    return {
        f.name: getattr(DEFAULT_CONFIG, f.name)
        for f in fields(DEFAULT_CONFIG)
        if not f.name.endswith("_weights")
    }


# --------------------------------------------------------------------------
# analyze
# --------------------------------------------------------------------------

def _error(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message, **extra})


async def _save_uploads(uploads: Dict[str, UploadFile], tmpdir: Path) -> Dict[str, Path]:
    saved: Dict[str, Path] = {}
    for view, upload in uploads.items():
        dest = tmpdir / f"{view}.jpg"
        size = 0
        with dest.open("wb") as fh:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise ValueError(f"{view} melebihi batas {MAX_UPLOAD_BYTES // (1024*1024)} MB")
                fh.write(chunk)
        saved[view] = dest
    return saved


@app.post("/v1/analyze")
async def analyze(
    frontal: Optional[UploadFile] = File(None),
    lateral_kanan: Optional[UploadFile] = File(None),
    lateral_kiri: Optional[UploadFile] = File(None),
    oklusal_atas: Optional[UploadFile] = File(None),
    oklusal_bawah: Optional[UploadFile] = File(None),
    patient_id: Optional[str] = Form(
        None, description="Opsional. Dikembalikan apa adanya di response. Kosongkan kalau tidak dipakai."
    ),
    config: Optional[str] = Form(
        None,
        description=(
            'Opsional. JSON objek untuk menimpa ambang batas, mis. {"OVERJET_HIGH": 0.9}. '
            "KOSONGKAN kalau tidak dipakai -- di Swagger UI, field ini bisa terisi otomatis "
            'dengan teks "string" yang bukan JSON dan akan ditolak.'
        ),
    ),
):
    uploads = {
        "frontal": frontal,
        "lateral_kanan": lateral_kanan,
        "lateral_kiri": lateral_kiri,
        "oklusal_atas": oklusal_atas,
        "oklusal_bawah": oklusal_bawah,
    }

    if patient_id and patient_id.strip() == "string":
        patient_id = None      # placeholder Swagger, bukan id pasien sungguhan

    if STUB_MODE:
        return stub_response(patient_id)

    # 4.3 -- foto wajib tidak lengkap: tolak, jangan analisis sebagian
    missing = [view for view in REQUIRED_VIEWS if uploads[view] is None]
    if missing:
        return _error(
            400, "missing_photo", "All five photos are required.", missing=missing
        )

    overrides: Optional[dict] = None
    # "string" adalah placeholder yang diisi otomatis oleh Swagger UI pada field Form
    # opsional. Itu artefak UI, bukan niat pengguna -- perlakukan seperti kosong.
    if config and config.strip() and config.strip() != "string":
        try:
            overrides = json.loads(config)
            if not isinstance(overrides, dict):
                raise ValueError("harus berupa objek JSON, bukan " + type(overrides).__name__)
        except Exception as exc:
            return _error(
                400,
                "bad_config",
                f"Field `config` bukan objek JSON yang valid: {exc}. "
                'Contoh yang benar: {"OVERJET_HIGH": 0.9}. Kosongkan field ini kalau tidak dipakai.',
            )

    tmpdir = Path(tempfile.mkdtemp(prefix="dhc_"))
    t0 = time.perf_counter()
    try:
        try:
            saved = await _save_uploads(uploads, tmpdir)
        except ValueError as exc:
            return _error(400, "upload_too_large", str(exc))

        result = analyze_patient(
            frontal=saved["frontal"],
            lateral_kanan=saved["lateral_kanan"],
            lateral_kiri=saved["lateral_kiri"],
            oklusal_atas=saved["oklusal_atas"],
            oklusal_bawah=saved["oklusal_bawah"],
            patient_id=patient_id,
            config_overrides=overrides,
        )
        log.info(
            "analisis selesai patient_id=%s dalam %.1f detik",
            patient_id, time.perf_counter() - t0,
        )
        return result

    except FileNotFoundError as exc:
        # bobot model tidak ada -- ini masalah deployment, bukan masalah foto
        log.error("bobot model hilang: %s", exc)
        return _error(500, "pipeline_failure", str(exc))
    except Exception as exc:
        # 4.4 -- tidak ada satu pun yang bisa dijalankan
        log.exception("pipeline gagal total")
        return _error(500, "pipeline_failure", f"Analysis failed: {exc}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
