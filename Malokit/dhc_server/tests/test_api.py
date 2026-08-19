"""Uji kontrak API: bentuk response, aturan wajib, dan penanganan kasus tepi.

Test di sini TIDAK butuh bobot model (pakai stub mode / gambar palsu), jadi bisa
dijalankan di CI. Uji yang butuh model asli ada di `test_regression.py`.

Jalankan:  pytest dhc_server/tests/test_api.py -v
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

READING_KEYS = {"value", "label", "side", "reliable", "warnings"}


def _fake_jpeg() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (128, 100, 100)).save(buf, format="JPEG")
    return buf.getvalue()


def _files(views=None):
    views = views or ["frontal", "lateral_kanan", "lateral_kiri", "oklusal_atas", "oklusal_bawah"]
    return [(v, (f"{v}.jpg", _fake_jpeg(), "image/jpeg")) for v in views]


@pytest.fixture()
def stub_client(monkeypatch):
    monkeypatch.setenv("DHC_STUB", "1")
    for mod in ("app", "stub"):
        sys.modules.pop(mod, None)
    import app as app_module

    return TestClient(app_module.app)


# --------------------------------------------------------------------------
# bentuk response
# --------------------------------------------------------------------------

def _assert_reading(obj, where: str):
    assert set(obj) == READING_KEYS, f"{where}: kunci Reading harus persis {READING_KEYS}, dapat {set(obj)}"
    assert isinstance(obj["reliable"], bool), f"{where}: `reliable` harus boolean"
    assert isinstance(obj["warnings"], list), f"{where}: `warnings` harus list (jangan null)"
    # aturan #1 & #2 kontrak
    if obj["value"] is None:
        assert obj["reliable"] is False, f"{where}: value null WAJIB reliable=false"


def assert_contract_shape(body: dict) -> None:
    """Cek satu response memenuhi API_CONTRACT sect. 2 & 3."""
    for key in ("patient_id", "engine_version", "overjet", "overbite", "anterior_crossbite",
                "angle", "crossbite_posterior", "missing", "crowding", "overlays"):
        assert key in body, f"kunci wajib hilang: {key}"

    for name in ("overjet", "overbite", "anterior_crossbite"):
        _assert_reading(body[name], name)

    angle = body["angle"]
    assert set(angle) == {"side", "molar", "canine", "disagreement"}
    _assert_reading(angle["molar"], "angle.molar")
    _assert_reading(angle["canine"], "angle.canine")
    assert isinstance(angle["disagreement"], bool)
    # aturan #3: disagreement hanya sah kalau KEDUANYA punya nilai
    if angle["disagreement"]:
        assert angle["molar"]["value"] is not None and angle["canine"]["value"] is not None

    cb = body["crossbite_posterior"]
    assert isinstance(cb["flagged"], list)
    for f in cb["flagged"]:
        assert set(f) == {"side", "posisi", "ratio"}
        assert f["side"] in {"left", "right"}
        assert isinstance(f["posisi"], int)

    miss = body["missing"]
    for key in ("occlusal_gaps", "frontal_gaps", "disagreement", "reliable", "warnings"):
        assert key in miss
    assert isinstance(miss["disagreement"], bool)
    # aturan #4: dua-duanya dilaporkan, tidak ada yang dipilih diam-diam
    if miss["occlusal_gaps"] is not None and miss["frontal_gaps"] is not None:
        assert miss["disagreement"] == (miss["occlusal_gaps"] != miss["frontal_gaps"])

    crowd = body["crowding"]
    assert set(crowd) == {"upper", "lower"}
    for arch in ("upper", "lower"):
        item = crowd[arch]
        if item is None:
            continue
        assert set(item) == {"sum", "label", "flagged_teeth", "reliable", "warnings"}
        assert isinstance(item["flagged_teeth"], list)
        assert all(isinstance(t, int) for t in item["flagged_teeth"])

    # Overlay: kunci harus memakai nama field unggahan, dan tiap bentuk mematuhi
    # aturan kontrak. Cek ini juga menjaga agar STUB tidak basi -- kalau response
    # asli berubah bentuk tapi stub tidak, app akan mengembangkan UI terhadap
    # bentuk yang salah tanpa ada yang menyadarinya.
    overlays = body["overlays"]
    assert isinstance(overlays, dict)
    assert set(overlays) == {
        "frontal", "lateral_kanan", "lateral_kiri", "oklusal_atas", "oklusal_bawah"
    }, f"kunci overlay harus sama dengan nama field unggahan, dapat {set(overlays)}"

    valid_roles = {"tooth", "flagged", "anchor", "reference", "measurement",
                   "archCurve", "gap", "rejected"}
    count_rule = {"polygon": (3, None), "box": (2, 2), "line": (2, None), "point": (1, 1)}
    for view, data in overlays.items():
        if data is None:
            continue
        assert set(data) == {"shapes"}, f"{view}: overlay hanya boleh punya kunci `shapes`"
        for sh in data["shapes"]:
            assert set(sh) == {"kind", "role", "label", "params", "points"}, (
                f"{view}: kunci bentuk salah"
            )
            assert isinstance(sh["params"], list), f"{view}: `params` harus list"
            assert sh["role"] in valid_roles, f"{view}: role tak dikenal {sh['role']}"
            lo, hi = count_rule[sh["kind"]]
            n = len(sh["points"])
            assert n >= lo and (hi is None or n == hi), f"{view}: {sh['kind']} punya {n} titik"
            for x, y in sh["points"]:
                assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0, (
                    f"{view}: koordinat ({x},{y}) di luar 0-1 -- piksel mentah?"
                )


def test_stub_matches_contract_shape(stub_client):
    r = stub_client.post("/v1/analyze", files=_files(), data={"patient_id": "TEST-1"})
    assert r.status_code == 200
    body = r.json()
    assert_contract_shape(body)
    assert body["patient_id"] == "TEST-1", "patient_id harus dikembalikan apa adanya"


def test_lower_arch_carries_unvalidated_warning(stub_client):
    """Brief 8.5: ambang lengkung bawah belum tervalidasi, harus selalu ditandai."""
    body = stub_client.post("/v1/analyze", files=_files()).json()
    lower = body["crowding"]["lower"]
    if lower is not None:
        assert lower["warnings"], "lengkung bawah wajib membawa peringatan kalibrasi"
        assert lower["reliable"] is False


# --------------------------------------------------------------------------
# kasus tepi
# --------------------------------------------------------------------------

def test_missing_photo_returns_400(monkeypatch):
    """4.3 -- foto kurang: tolak, jangan analisis sebagian."""
    monkeypatch.delenv("DHC_STUB", raising=False)
    sys.modules.pop("app", None)
    import app as app_module

    client = TestClient(app_module.app)
    incomplete = _files(["frontal", "lateral_kanan", "lateral_kiri", "oklusal_atas"])
    r = client.post("/v1/analyze", files=incomplete)
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "missing_photo"
    assert body["missing"] == ["oklusal_bawah"]
    assert "message" in body


def test_bad_config_returns_400(monkeypatch):
    monkeypatch.delenv("DHC_STUB", raising=False)
    sys.modules.pop("app", None)
    import app as app_module

    client = TestClient(app_module.app)
    r = client.post("/v1/analyze", files=_files(), data={"config": "bukan-json"})
    assert r.status_code == 400
    assert r.json()["error"] == "bad_config"


def test_health_endpoint(stub_client):
    body = stub_client.get("/v1/health").json()
    assert body["status"] in {"ok", "degraded"}
    assert "engine_version" in body
    assert isinstance(body["missing_weights"], list)


def test_config_endpoint_exposes_thresholds(stub_client):
    body = stub_client.get("/v1/config").json()
    for key in ("OVERJET_HIGH", "LITTLES_THRESHOLD_SUM", "CROSSBITE_THRESHOLD"):
        assert key in body
    assert not any(k.endswith("_weights") for k in body), "path bobot model jangan dibocorkan"


# --------------------------------------------------------------------------
# config override
# --------------------------------------------------------------------------

def test_config_override_applied_and_unknown_keys_ignored():
    from dhc_pipeline.config import DEFAULT_CONFIG

    cfg = DEFAULT_CONFIG.merged({"OVERJET_HIGH": 0.9, "kunci_ngawur": 123})
    assert cfg.OVERJET_HIGH == 0.9
    assert not hasattr(cfg, "kunci_ngawur")
    # yang lain tidak boleh ikut berubah
    assert cfg.LITTLES_THRESHOLD_SUM == DEFAULT_CONFIG.LITTLES_THRESHOLD_SUM


def test_config_override_cannot_change_model_paths():
    """Endpoint publik tidak boleh dipakai memuat file sembarangan dari disk server."""
    from dhc_pipeline.config import DEFAULT_CONFIG

    cfg = DEFAULT_CONFIG.merged({"detector_weights": "/etc/passwd"})
    assert cfg.detector_weights == DEFAULT_CONFIG.detector_weights

def test_stub_actually_contains_overlays(stub_client):
    """Stub HARUS punya overlay berisi.

    Alur yang disepakati (kontrak §7) adalah app menyambung ke stub dulu untuk
    membuktikan handshake. Kalau stub mengirim overlay kosong, app akan mengira
    renderer-nya bekerja padahal tidak pernah menggambar apa pun.
    """
    body = stub_client.post("/v1/analyze", files=_files()).json()
    filled = [v for v in body["overlays"].values() if v and v["shapes"]]
    assert filled, "stub tidak boleh mengirim overlay kosong semua"

    roles = {sh["role"] for v in filled for sh in v["shapes"]}
    # contoh harus mewakili SEMUA role -- app perlu menguji setiap warna & layer,
    # termasuk `rejected` yang mereka gambar abu-abu putus-putus
    for role in ("tooth", "anchor", "reference", "flagged", "measurement",
                 "archCurve", "gap", "rejected"):
        assert role in roles, f"contoh stub belum mencakup role `{role}`"

    # dan setiap parameter harus bisa difilter dari stub
    params = {p for v in filled for sh in v["shapes"] for p in sh["params"]}
    for prm in ("overjet", "overbite", "anterior_crossbite", "angle",
                "crossbite_posterior", "missing", "crowding"):
        assert prm in params, f"contoh stub belum mencakup parameter `{prm}`"
