"""Semua konstanta pipeline DHC.

Angka-angka di sini adalah **kalibrasi kasar dari sampel kecil**, bukan angka klinis
baku (lihat `model-explore/PROGRESS_SUMMARY.md`). Karena itu semuanya dibuat bisa
di-override dari luar -- lewat `Config(...)` di kode, atau lewat field `config` di
request API.

Sumber tiap konstanta ada di komentarnya, supaya kalau nanti dikalibrasi ulang
ketahuan dasarnya apa.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Mapping

# Root repo -- dhc_server/dhc_pipeline/config.py -> naik 3 tingkat
REPO_ROOT = Path(__file__).resolve().parents[2]
_WEIGHTS_ROOT = REPO_ROOT / "model-explore"


@dataclass(frozen=True)
class Config:
    # ---------------- bobot model ----------------
    lateral_seg_weights: Path = _WEIGHTS_ROOT / "runs/segment/lateral_pilot_runs/baseline_seg-3/weights/best.pt"
    frontal_seg_weights: Path = _WEIGHTS_ROOT / "runs/segment/frontal_pilot_runs/baseline_seg/weights/best.pt"
    occlusal_seg_weights: Path = _WEIGHTS_ROOT / "runs/segment/occlusal_pilot_runs/baseline_seg/weights/best.pt"
    detector_weights: Path = _WEIGHTS_ROOT / "runs/detect/canine_distal_runs/v3-2/weights/best.pt"

    # ---------------- inferensi ----------------
    SEG_CONF: float = 0.5
    SEG_IOU: float = 0.4
    DET_CONF_CANINE: float = 0.25
    DET_CONF_DISTAL: float = 0.25
    DET_IOU: float = 0.5
    # TTA (test-time augmentation): inferensi diulang pada beberapa skala/flip lalu
    # digabung. Menaikkan recall kaninus dengan biaya waktu ~2x.
    DET_AUGMENT: bool = False

    # ---------------- ambang klinis ----------------
    # < LOW: crossbite anterior; > HIGH: overjet berlebih
    OVERJET_LOW: float = 0.0
    OVERJET_HIGH: float = 0.5
    # < LOW: open bite; > HIGH: deep bite
    OVERBITE_LOW: float = 0.0
    OVERBITE_HIGH: float = 0.5
    # |ratio| > ini -> Class II / III
    ANGLE_THRESHOLD: float = 0.25
    # ~30% lebar gigi; divalidasi ke 6 pasien + 3 foto luar (1 kasus klinis confirmed)
    CROSSBITE_THRESHOLD: float = 0.05
    # Crossbite POSTERIOR menurut definisi klinis hanya melibatkan premolar & molar.
    # Posisi 1-3 dari midline (insisivus sentral, lateral, kaninus) adalah zona
    # ANTERIOR -- C-ke-C -- dan tidak boleh ikut dihitung sebagai posterior.
    # Sebelum batas ini dipasang, 6 dari 22 pasien punya temuan zona anterior yang
    # salah dilaporkan sebagai crossbite posterior.
    #
    # CATATAN: temuan zona anterior itu TIDAK dipindahkan ke `anterior_crossbite`.
    # Pengukuran frontal ini sumbu TRANSVERSAL (tepi bukal terhadap midline),
    # sedangkan crossbite anterior itu sumbu DEPAN-BELAKANG (gigi atas di belakang
    # gigi bawah). Dua hal berbeda -- memindahkannya akan menukar satu kesalahan
    # dengan kesalahan lain.
    CROSSBITE_POSTERIOR_MIN_POSITION: int = 4

    # ---------------- Crossbite ANTERIOR (C-ke-C) ----------------
    # Revisi dari dokter: crossbite anterior diperiksa dari kaninus ke kaninus --
    # 6 gigi, yaitu posisi 1-3 di TIAP foto lateral. Kalau SATU saja gigi atas
    # berada di belakang pasangan bawahnya, itu sudah crossbite.
    #
    # Sebelumnya hanya posisi 1 (insisivus sentral) yang dicek, dan itu melewatkan
    # kasus nyata: pasien 2023.14 lateral kanan punya pos1=+0.23 (normal) tapi
    # pos2=-0.21 dan pos3=-0.49 -- dokter langsung melihatnya di app.
    #
    # STATUS: default (1,) -- HANYA insisivus sentral, sama seperti perilaku lama.
    # Ubah ke (1, 2, 3) untuk menyalakan aturan C-ke-C penuh.
    #
    # Mesinnya sudah siap dan sudah diuji menangkap kasus yang dokter tandai
    # (pasien 2023.14: pos2=-0.21, pos3=-0.49). TAPI belum dinyalakan karena
    # pengukurannya belum bisa dipercaya di posisi 2 & 3 -- lihat catatan ambang
    # di bawah. Menyalakannya sekarang membuat 19 dari 22 pasien (86%) ter-flag
    # crossbite anterior, yang mustahil benar dan akan membuat parameter ini
    # kehilangan makna sama sekali.
    ANTERIOR_CROSSBITE_POSITIONS: tuple = (1,)
    # Ambang per posisi. Nol = aturan literal dokter ("di belakang sedikit pun
    # sudah crossbite").
    #
    # BELUM DIKALIBRASI, dan ini perlu diketahui: di seluruh dataset, median rasio
    # posisi 1 = +0.42, posisi 2 = -0.08, posisi 3 = -0.21. Pergeseran ke negatif
    # makin ke distal itu sistematis -- pada oklusi normal, kaninus atas memang
    # duduk agak distal terhadap kaninus bawah. Jadi ambang nol kemungkinan
    # menghasilkan sebagian positif palsu di posisi 2 & 3.
    #
    # Kasus yang dikonfirmasi dokter berada di persentil 29-42%, bukan di ekor
    # ekstrem, jadi ambang berbasis persentil justru tidak menangkapnya. Untuk
    # memisahkan "bias pengukuran" dari "crossbite memang umum di populasi klinik
    # ini" dibutuhkan contoh NORMAL yang dilabeli dokter -- belum ada.
    #
    # Sudah dicoba mencari ambang yang menangkap kasus dokter tanpa membanjiri
    # positif palsu -- TIDAK ADA yang berhasil:
    #
    #   ambang   pasien ter-flag   kasus dokter tertangkap?
    #    0.00        19/22 (86%)        ya
    #   -0.40        15/22 (68%)        ya
    #   -0.45        14/22 (64%)        ya
    #   -0.50        13/22 (59%)        TIDAK
    #
    # Diukur relatif terhadap insisivus sentral pasien sendiri (untuk membuang
    # bias sistematis) juga gagal: kasus dokter jatuh di persentil 44% & 36%,
    # persis di tengah sebaran.
    #
    # Artinya bukan soal memilih angka, melainkan pengukurannya sendiri belum
    # memisahkan sinyal dari sebaran normal di posisi 2 & 3. Yang dibutuhkan:
    # contoh NORMAL yang dilabeli dokter, supaya batasnya bisa dicari dari data.
    ANTERIOR_CROSSBITE_THRESHOLD: float = 0.0

    # ---------------- Missing ----------------
    # versi frontal (neighbor-gap) -- CROSS-CHECK saja, bukan sumber utama
    GAP_RATIO_THRESHOLD: float = 0.5
    DISPLACEMENT_THRESHOLD: float = 0.35
    # versi oklusal (Arch Occupancy) -- SUMBER UTAMA
    MISSING_ARC_GAP_THRESHOLD: float = 0.6

    # ---------------- Crowding (Little's Irregularity Index) ----------------
    LITTLES_ANTERIOR_N: int = 3       # gigi per sisi dari midline (kaninus-ke-kaninus)
    LITTLES_THRESHOLD_SUM: float = 1.05
    LITTLES_STEP_THRESHOLD: float = 0.30

    # ---------------- guard kualitas (JANGAN dimatikan tanpa alasan kuat) ----------------
    # mask nempel tepi frame DAN < ini x median -> noise, dibuang.
    # Dikalibrasi dari audit 44 foto: noise 2018.05 = 0.20x (buang),
    # gigi asli kepotong frame 2021.86 = 0.45x & 0.52x (aman). 0 regresi.
    EDGE_SLIVER_MAX_AREA_RATIO: float = 0.30
    EDGE_SLIVER_TOL_PX: int = 3
    # mask insisivus < ini x median -> kemungkinan serpihan, hasil ditandai tidak andal
    INCISOR_MIN_AREA_RATIO: float = 0.5
    # di atas ini mustahil secara klinis -> hasil ditandai tidak andal
    OVERJET_PLAUSIBLE: float = 2.0
    OVERBITE_PLAUSIBLE: float = 1.5
    # buang titik dgn residual > ini x tinggi rata2 gigi, lalu fit ulang kurva lengkung
    ROBUST_RESIDUAL_FACTOR: float = 2.5

    # ---------------- overlay (geometri untuk digambar app) ----------------
    OVERLAY_ENABLED: bool = True
    # Penyederhanaan kontur: ~130 titik/gigi mentah -> ~11 titik/gigi pada 0.01.
    # Turunkan ke 0.005 (~16 titik) kalau outline terlihat menyudut di layar.
    OVERLAY_EPS_FRAC: float = 0.01
    # Kurva lengkung disampel 1000 titik untuk perhitungan; sebanyak itu mubazir
    # untuk digambar -- parabola tetap mulus dengan beberapa puluh titik.
    OVERLAY_ARCH_CURVE_POINTS: int = 24
    OVERLAY_GAP_LINE_POINTS: int = 5
    OVERLAY_COORD_DECIMALS: int = 4
    # Mask yang DIBUANG pipeline (serpihan tepi frame, outlier kurva) -- role
    # `rejected`. Ini yang menjelaskan KENAPA sebuah hasil ditandai tidak andal
    # (mis. serpihan di luar mulut yang pernah terpilih jadi anchor insisivus).
    # Disepakati tim app: mereka menggambarnya abu-abu putus-putus dan
    # menyembunyikannya secara default, dinyalakan hanya saat menelusuri kesalahan.
    OVERLAY_INCLUDE_REJECTED: bool = True

    # ---------------- lain-lain ----------------
    MIN_TEETH_FOR_OCCLUSAL: int = 4   # di bawah ini oklusal dianggap tidak bisa dianalisis
    OCCUPANCY_SAMPLES: int = 1000
    SPURIOUS_MIN_AREA_RATIO: float = 0.15

    def merged(self, overrides: Mapping[str, Any] | None) -> "Config":
        """Kembalikan Config baru dengan sebagian nilai di-override.

        Key yang tidak dikenal DIABAIKAN (sesuai API contract sect. 6), bukan error --
        supaya app versi lama tidak pecah saat server menghapus sebuah knob.
        Path bobot model sengaja TIDAK bisa di-override dari request, biar endpoint
        publik tidak bisa dipakai memuat file sembarangan dari disk server.
        """
        if not overrides:
            return self
        blocked = {f.name for f in fields(self) if f.type is Path or f.name.endswith("_weights")}
        allowed = {f.name for f in fields(self)} - blocked
        clean: dict[str, Any] = {}
        ignored: list[str] = []
        for key, value in overrides.items():
            if key in allowed and isinstance(value, (int, float)) and not isinstance(value, bool):
                clean[key] = type(getattr(self, key))(value)
            else:
                ignored.append(key)
        cfg = replace(self, **clean) if clean else self
        object.__setattr__(cfg, "_ignored_overrides", ignored)
        return cfg


DEFAULT_CONFIG = Config()
