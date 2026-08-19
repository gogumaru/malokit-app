"""Pembacaan gambar yang toleran terhadap format kiriman app.

Kenapa modul ini ada: Pillow polos tidak bisa membaca **HEIC/HEIF**, padahal itu
format default kamera iPhone. Tanpa ini, foto yang dikirim langsung dari iPhone
membuat kelima analisis gagal dan pesan errornya tidak menjelaskan apa-apa.

`pillow-heif` bersifat opsional: kalau tidak terpasang, server tetap jalan untuk
JPEG/PNG/WebP dan memberi pesan yang jelas saat menerima HEIC.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, UnidentifiedImageError

log = logging.getLogger(__name__)

HEIF_AVAILABLE = False
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_AVAILABLE = True
except Exception:  # pragma: no cover - tergantung lingkungan
    log.warning(
        "pillow-heif tidak terpasang: foto HEIC/HEIF (default iPhone) akan ditolak. "
        "Pasang dengan `pip install pillow-heif`."
    )


class UnreadableImage(ValueError):
    """Gambar tidak bisa dibaca -- pesannya sudah layak ditampilkan ke pengguna."""


def _looks_like_heif(path: Path) -> bool:
    """Deteksi HEIC/HEIF dari magic bytes, bukan dari ekstensi nama file.

    App bisa saja mengirim file HEIC dengan nama `.jpg` (mis. karena field
    multipart-nya diberi nama begitu), jadi ekstensi tidak bisa dipercaya.
    """
    try:
        head = path.open("rb").read(12)
    except OSError:
        return False
    return len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] in {
        b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis",
    }


def open_image(path: Path) -> Image.Image:
    """Buka gambar sebagai RGB, dengan pesan error yang bisa ditindaklanjuti."""
    path = Path(path)
    try:
        img = Image.open(path)
        img.load()
        return img.convert("RGB")
    except UnidentifiedImageError as exc:
        if _looks_like_heif(path) and not HEIF_AVAILABLE:
            raise UnreadableImage(
                "foto berformat HEIC/HEIF (default kamera iPhone) dan server ini belum "
                "bisa membacanya. Perbaikan: pasang `pillow-heif` di server, atau minta "
                "app mengirim JPEG."
            ) from exc
        # Nama berkas sengaja TIDAK disebut: view yang gagal sudah diidentifikasi
        # oleh pemanggil, dan menyebut nama file membuat sebab yang identik terlihat
        # berbeda sehingga tidak bisa diringkas jadi satu pesan.
        raise UnreadableImage(
            "berkas tidak dikenali sebagai gambar. Pastikan yang dikirim benar-benar "
            "JPEG/PNG/HEIC, bukan berkas kosong atau rusak."
        ) from exc
    except OSError as exc:
        raise UnreadableImage(f"gagal membaca berkas gambar: {exc}") from exc
