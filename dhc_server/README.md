# DHC pipeline server

Server HTTP yang membungkus pipeline pengukuran maloklusi dari `model-explore/11_app_simulation.ipynb`, mengikuti `API_CONTRACT.md`.

Lima foto intraoral masuk, satu JSON keluar.

> **Status: alat bantu penelitian, bukan alat diagnosis mandiri.** Baca [Batasan](#batasan-yang-harus-tercermin-di-ui) sebelum membangun UI di atasnya.

---

## Instalasi

```bash
cd dhc_server
pip install -r requirements.txt
```

Server membaca bobot model dari `model-explore/runs/...` (lihat `dhc_pipeline/config.py`). Total ~22 MB, empat file:

| Model | Ukuran | Tugas |
|---|---|---|
| segmentasi lateral | 5.7 MB | mask per gigi, foto lateral |
| segmentasi frontal | 5.7 MB | mask per gigi, foto frontal |
| segmentasi oklusal | 5.7 MB | mask per gigi, foto oklusal |
| detector anchor | 5.3 MB | kaninus + gigi paling distal |

Cek kelengkapannya kapan saja lewat `GET /v1/health`.

## Menjalankan

```bash
cd dhc_server
uvicorn app:app --host 0.0.0.0 --port 8000
```

Mode stub — tidak memuat model sama sekali, membalas contoh statis (untuk membuktikan handshake app lebih dulu, sesuai kontrak §7):

```bash
DHC_STUB=1 uvicorn app:app --port 8000
```

Variabel lingkungan:

| Variabel | Default | Fungsi |
|---|---|---|
| `DHC_STUB` | kosong | `1` = mode stub |
| `DHC_LOG_LEVEL` | `INFO` | level log |
| `DHC_MAX_UPLOAD_MB` | `25` | batas ukuran tiap foto |

## Format foto

Diterima: **JPEG, PNG, WebP, HEIC/HEIF**. Dukungan HEIC berasal dari `pillow-heif` — penting karena itu format default kamera iPhone. Kalau paket itu tidak terpasang, server tetap jalan untuk format lain dan memberi pesan yang jelas saat menerima HEIC (bukan gagal misterius).

Gambar dibuka sekali lalu objeknya dioper ke YOLO, bukan path-nya, supaya format yang butuh decoder tambahan ikut tertangani. Sudah diverifikasi: hasil mask lewat objek gambar identik dengan lewat path (selisih 0.000000 px).

## Endpoint

| Endpoint | Fungsi |
|---|---|
| `POST /v1/analyze` | 5 foto → satu JSON (bentuknya di `API_CONTRACT.md` §2) |
| `GET /v1/health` | status server + bobot model yang hilang |
| `GET /v1/config` | konstanta yang sedang berlaku (untuk memverifikasi kalibrasi) |

Contoh:

```bash
curl -X POST http://localhost:8000/v1/analyze \
  -F "frontal=@frontal.jpg" \
  -F "lateral_kanan=@lat_kanan.jpg" \
  -F "lateral_kiri=@lat_kiri.jpg" \
  -F "oklusal_atas=@okl_atas.jpg" \
  -F "oklusal_bawah=@okl_bawah.jpg" \
  -F "patient_id=2018.08"
```

**Nama field membawa identitas view.** Server mempercayainya apa adanya dan tidak pernah menebak ulang dari isi gambar atau EXIF. Di dataset riset, penamaan file terbukti tidak konsisten — 5 dari 13 pasien terbalik — dan itu sempat menghasilkan kesimpulan yang salah. Di app hal ini tidak jadi masalah karena pemotretan dipandu per langkah.

## Overlay (geometri untuk digambar app)

Kunci `overlays` mengirim **koordinat**, bukan gambar jadi — app masih memegang fotonya, jadi cukup dikirim angka. Acuan: `API_CONTRACT_OVERLAYS.md` + `OVERLAY_FILTERING_PROPOSAL.md`.

Semua titik adalah pecahan **0–1 terhadap gambar yang diunggah**, titik asal kiri-atas. Sudah diverifikasi bahwa `masks.xy` ultralytics berada di ruang piksel gambar asli (bukan 640×640 hasil letterbox): gambar yang sama diuji pada 512×341 sampai 2048×1364, pecahan koordinatnya identik.

Tiap bentuk punya dua sumbu keterangan yang sengaja dipisah:

- **`role`** menjawab *"ini apa"* → menentukan **warna** di app
- **`params`** menjawab *"ini bantu periksa apa"* → menentukan **kapan ditampilkan**

| `role` | Dipakai untuk |
|---|---|
| `tooth` | mask segmentasi biasa |
| `flagged` | gigi yang ditandai aturan (crowding, crossbite) |
| `anchor` | **keluaran detector** — kaninus & distal |
| `reference` | **gigi yang benar-benar dipakai mengukur** — insisivus, molar, kaninus |
| `measurement` | garis tempat overjet & overbite diukur |
| `archCurve` | kurva lengkung hasil fit |
| `gap` | dugaan celah gigi hilang |
| `rejected` | mask yang **dibuang** pipeline (serpihan tepi frame, outlier kurva) |

`anchor` dan `reference` sengaja dipisah: kalau box detector dan gigi yang dipakai mengukur **tidak bertumpuk**, itu sendiri informasi penting. Kasus overjet 9.33 adalah contohnya — detector-nya berhasil, yang meleset justru insisivus yang diturunkan dengan menghitung posisi dari kaninus.

Aturan filter di sisi app:

```
gambar sebuah bentuk jika:
    params kosong                  (konteks: outline & kurva lengkung)
    ATAU parameter_aktif ada di params
```

Nilai `params` memakai kunci parameter response apa adanya: `overjet`, `overbite`, `anterior_crossbite`, `angle`, `crossbite_posterior`, `missing`, `crowding`.

Ukuran: rata-rata **22.4 kB** per pasien (maksimum 26.9 kB dari 22 pasien), sekitar 96 bentuk. Bisa dimatikan lewat `OVERLAY_ENABLED`; kuncinya tetap ada dengan isi `null` supaya bentuk response stabil.

Gigi ter-flag **displacement** di frontal sengaja tidak dikirim — `displacement` bukan parameter di response utama, jadi tidak ada layar yang bisa menampilkannya.

## Struktur

```
dhc_server/
  app.py                 FastAPI: endpoint, validasi, penanganan error
  stub.py                response contoh untuk mode stub
  dhc_pipeline/
    config.py            semua konstanta, bisa di-override
    models.py            muat & cache 4 model YOLO
    features.py          fitur per gigi, penyaring mask palsu
    arch.py              midline, urutan gigi, fit kurva robust
    lateral.py           overjet, overbite, Angle  + guard kualitas
    frontal.py           missing (cross-check), displacement, crossbite posterior
    occlusal.py          missing (arch occupancy), crowding (Little's Index)
    overlays.py          geometri 0-1 untuk digambar app
    report.py            gabungkan jadi response sesuai kontrak
    pipeline.py          orkestrasi analyze_patient()
  tests/
    test_api.py          bentuk response & kasus tepi (tanpa model, aman untuk CI)
    test_overlays.py     aturan kontrak overlay (butuh model + dataset)
    test_regression.py   angka harus sama dengan notebook (butuh model + dataset)
```

Bisa dipakai langsung sebagai library, tanpa HTTP:

```python
from dhc_pipeline import analyze_patient

hasil = analyze_patient(
    frontal="f.jpg", lateral_kanan="lk.jpg", lateral_kiri="lki.jpg",
    oklusal_atas="oa.jpg", oklusal_bawah="ob.jpg",
    patient_id="2018.08",
)
```

## Test

```bash
cd dhc_server
pytest tests/test_api.py -v          # cepat, tanpa model
pytest tests/ -v                     # termasuk regresi (butuh model + dataset)
```

`test_regression.py` mengunci hasil paket ini terhadap angka yang dikeluarkan notebook. Angka acuannya **dihasilkan dengan menjalankan kode notebook**, bukan ditulis tangan. Kalau ada yang gagal, artinya port-nya menyimpang dari riset — perbaiki kodenya, jangan ubah angka acuannya.

**Hasil verifikasi port:** 22 pasien diuji, **semua nilai terukur identik** dengan notebook (overjet, overbite, Angle, crossbite, missing, crowding). Satu-satunya perbedaan yang disengaja: saat anchor kaninus gagal, paket ini menjelaskan sebabnya di `warnings`, sedangkan notebook mengirim daftar kosong — ini diminta kontrak §4.1.

## Performa

Diukur di MacBook Pro (Apple Silicon), 8 pasien, semua model sudah dimuat:

```
rata-rata 0.32 detik   min 0.30   maks 0.34
```

Empat model dimuat sekali saat server start (~4 detik), jadi request pertama tidak menanggung bebannya. Sinkron aman — jauh di bawah ambang 30 detik di kontrak.

---

## Batasan yang harus tercermin di UI

Semua ini hasil audit nyata, bukan kehati-hatian normatif. Rinciannya di `model-explore/APP_EXPORT_BRIEF.md` §8.

**1. Detector kaninus gagal di 25% foto.** Dari audit 44 foto lateral, kaninus tidak ditemukan lengkap di 11 foto, dan **7 foto sama sekali tidak bisa menghasilkan Overjet/Overbite**. Ini konsisten dengan metrik model (`canine recall = 0.704`) — batas kemampuan model, bukan bug. Hanya bisa diperbaiki dengan menambah data anotasi.

→ Siapkan state "tidak bisa dihitung" sebagai hasil yang **normal dan sering**, bukan sebagai error.

**2. `value: null` bukan `0`.** Nol adalah pengukuran yang sah. Kalau UI menampilkan null sebagai `0` atau kosong, hasilnya menyesatkan.

**3. Guard sudah aktif.** Hasil ditandai `reliable: false` bila mask insisivus terlalu kecil (kemungkinan yang terambil serpihan) atau angkanya di luar rentang yang mungkin secara klinis. Contoh nyata: satu pasien sempat menghasilkan overjet 9.33 karena mask palsu di luar mulut terpilih sebagai anchor; setelah guard dipasang, sistem otomatis memakai sisi lain yang bersih.

**4. Lengkung bawah untuk Crowding belum tervalidasi.** Ambang Little's Index dikalibrasi hanya dari lengkung atas, jadi `crowding.lower` selalu membawa peringatan dan `reliable: false`.

**5. Sampel validasi masih sangat kecil** — 3 kasus crowding dan 3 kasus missing yang dikonfirmasi manual. Semua ambang batas berstatus kalibrasi kasar.

**6. Missing dari frontal tidak bisa melihat area premolar-molar** (tertutup pipi), jadi angkanya sering lebih kecil dari oklusal. Itu keterbatasan sudut foto, bukan bug — karena itu oklusal jadi sumber utama dan selisihnya ditandai `disagreement`.

**7. Belum ada skor DHC/IOTN gabungan.** Tiap parameter berdiri sendiri.

## Catatan keamanan

- Path bobot model **tidak bisa** di-override lewat field `config` di request — endpoint publik tidak boleh dipakai memuat file sembarangan dari disk server (ada test-nya).
- Foto yang diunggah ditulis ke direktori sementara dan **selalu dihapus** setelah analisis (blok `finally`).
- Belum ada autentikasi. Untuk pemakaian di luar jaringan lokal tepercaya, perlu ditambahkan — foto intraoral adalah data medis.
