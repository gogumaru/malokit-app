"""Pipeline pengukuran DHC dari 5 foto intraoral.

Pemakaian:

    from dhc_pipeline import analyze_patient

    hasil = analyze_patient(
        frontal="frontal.jpg",
        lateral_kanan="lat_kanan.jpg",
        lateral_kiri="lat_kiri.jpg",
        oklusal_atas="okl_atas.jpg",
        oklusal_bawah="okl_bawah.jpg",
    )

PENTING: penelepon WAJIB tahu foto oklusal mana yang atas dan mana yang bawah.
Jangan pernah menebaknya dari nama file atau EXIF -- di dataset riset penamaannya
terbukti tidak konsisten (5 dari 13 pasien terbalik) dan itu sempat menghasilkan
kesimpulan yang salah. Di aplikasi, hal ini dijamin oleh alur pemotretan yang
dipandu per langkah.
"""

from .config import Config, DEFAULT_CONFIG
from .pipeline import analyze_patient
from .report import ENGINE_VERSION

__all__ = ["analyze_patient", "Config", "DEFAULT_CONFIG", "ENGINE_VERSION"]
