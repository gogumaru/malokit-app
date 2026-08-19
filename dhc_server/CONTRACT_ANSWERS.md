# Jawaban untuk `API_CONTRACT.md` §8 — dari tim modeling

Server sudah dibangun dan berjalan sesuai kontrak. Di bawah ini jawaban delapan pertanyaan terbuka, ditambah **satu penyimpangan yang perlu dikonfirmasi** dan beberapa catatan implementasi.

---

## Jawaban delapan pertanyaan

### 1. Base URL dan port untuk lokal/testing?

Belum dipatok — server menerima host/port apa pun lewat argumen uvicorn:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

Saran: `http://<ip-lan>:8000`. Karena app menyimpannya di Settings, silakan pakai apa pun yang nyaman. Selama pengembangan, mode stub bisa dijalankan di port berbeda supaya bisa berdampingan dengan server asli.

### 2. `label` bahasa Inggris atau Indonesia?

**Bahasa Inggris**, sesuai preferensi di kontrak. Daftar lengkap nilai yang mungkin:

| Field | Nilai yang mungkin |
|---|---|
| `overjet.label` | `possible anterior crossbite`, `possible excess overjet`, `possible normal overjet` |
| `overbite.label` | `possible open bite`, `possible deep bite`, `possible normal overbite` |
| `anterior_crossbite.label` | `possible anterior crossbite`, `no anterior crossbite` |
| `angle.molar.label`, `angle.canine.label` | `resembles Class I`, `resembles Class II`, `resembles Class III` |
| `crossbite_posterior.label` | `possible posterior crossbite`, `normal` |
| `crowding.*.label` | `possible crowding`, `normal` |

Semuanya diawali "possible/resembles" dengan sengaja — ini proxy pengukuran dari foto, bukan diagnosis.

### 3. Konfirmasi semua `value` adalah rasio, bukan milimeter?

**Dikonfirmasi: semuanya rasio ternormalisasi, tidak ada satuan milimeter di mana pun.**

| Field | Dinormalisasi terhadap |
|---|---|
| `overjet.value` | lebar insisivus atas |
| `overbite.value` | tinggi insisivus atas |
| `anterior_crossbite.value` | sama dengan overjet (nilai yang sama) |
| `angle.molar.value` / `angle.canine.value` | lebar gigi atas pada posisi itu |
| `crossbite_posterior.flagged[].ratio` | lebar lengkung (dari midline ke tepi bukal terjauh) |
| `crowding.*.sum` | jumlah step Little's Index, tiap step dinormalisasi ke `oriented_width` rata-rata |

Konversi ke milimeter **tidak mungkin** dari foto ini — tidak ada objek referensi berskala di dalam frame. Kalau nanti dibutuhkan, perlu penanda kalibrasi fisik saat pemotretan, dan itu perubahan pada alur pengambilan foto, bukan pada server.

### 4. Perlu autentikasi?

**Sekarang belum ada.** Aman untuk jaringan lokal tepercaya selama pengembangan.

Untuk pemakaian di luar itu, autentikasi **perlu ditambahkan** — foto intraoral adalah data medis. Yang paling ringan: header API key. Tinggal bilang kalau app siap mengirimkannya, implementasinya singkat.

### 5. Waktu analisis realistis per pasien?

Diukur di MacBook Pro (Apple Silicon), 8 pasien, model sudah dimuat:

```
rata-rata 0.32 detik   min 0.30   maks 0.34
```

**Sinkron aman, jauh di bawah ambang 30 detik.** Catatan: keempat model dimuat saat server start (~4 detik) supaya request pertama tidak menanggung bebannya. Kalau nanti dideploy ke mesin tanpa GPU/Apple Silicon, angkanya bisa naik beberapa kali lipat — akan kami ukur ulang di mesin target sebelum produksi.

### 6. Overlay masuk versi pertama?

**Sudah — semuanya, bukan bertahap.** Setelah addendum `API_CONTRACT_OVERLAYS.md`, kelima view mengirim geometri. Prioritas 1–5 kalian dikerjakan sekaligus karena datanya bersumber dari tempat yang sama; memisahnya justru menambah kerja.

Yang dikirim per view:

| View | Isi |
|---|---|
| `lateral_kanan`, `lateral_kiri` | `tooth` polygon, `anchor` box (kaninus & distal), `measurement` line (overjet mendatar, overbite tegak) |
| `frontal` | `tooth` polygon, `flagged` (displacement + gigi crossbite), `gap` box |
| `oklusal_atas`, `oklusal_bawah` | `tooth` polygon, `flagged` (crowding, ber-label indeks), `archCurve`, `gap` line mengikuti kurva |

---

## Jawaban untuk addendum overlay (§7)

### 7.1 Apakah `masks.xy` sejajar dengan gambar yang diunggah?

**Ya, untuk ketiga model segmentasi. Tidak ada pemotongan internal.** Ini tidak kami jawab dari asumsi — diuji langsung, karena kalian benar bahwa kesalahan di sini "looks almost right".

Gambar yang sama diuji pada beberapa ukuran, lalu koordinatnya dinormalisasi:

| Ukuran | x/W | y/H |
|---|---|---|
| 512×341 | [0.138, 0.984] | [0.015, 0.991] |
| 1024×682 | [0.138, 0.984] | [0.015, 0.991] |
| 2048×1364 | [0.138, 0.984] | [0.015, 0.991] |
| 1200×800 | [0.138, 0.984] | [0.015, 0.990] |

Identik di rentang skala 4×, jadi letterbox 640×640 memang sudah dikembalikan oleh ultralytics. Kami menormalisasi terhadap dimensi berkas yang diterima, sehingga pemotongan di sisi app otomatis aman.

Diverifikasi juga secara visual: koordinat 0–1 digambar ulang ke foto (persis yang app lakukan) dan mendarat tepat pada gigi, bukan bergeser.

### 7.2 Bisakah `label` pada `flagged` memakai indeks yang sama dengan `flagged_teeth`?

**Ya, sudah.** Ini butuh perubahan di pipeline: sebelumnya `flagged_teeth` hanya berisi angka tanpa jejak ke gigi mana, jadi tidak ada cara memetakannya ke poligon. Sekarang rantai gigi ikut disimpan sehingga indeks dan outline dijamin merujuk gigi yang sama — ada test khusus yang membandingkan keduanya di tiap pasien.

Indeksnya 1-based sepanjang rantai gigi dari kiri ke kanan gambar. Sekali lagi: ini **bukan** nomor FDI.

### 7.3 Keberatan menghapus opsi data URI?

**Tidak, silakan dihapus.** Satu format lebih baik daripada dua. Kami tidak pernah mengirim gambar.

---

## Dua hal yang butuh keputusan kalian soal overlay

**1. Mask yang DIBUANG pipeline belum dikirim — mau ditambahkan?**

Pipeline membuang dua jenis mask: serpihan di tepi frame (`drop_edge_slivers`) dan outlier kurva lengkung. **Serpihan inilah yang dulu terpilih jadi anchor dan menghasilkan overjet 9.33** — persis kasus yang kalian sebut sebagai alasan terkuat.

Menampilkannya akan langsung menjawab "kenapa hasil ini tidak andal". Tapi tabel `role` kalian tidak punya nama untuk ini, dan **kami tidak mau mengirim role yang tidak dikenal app** — risikonya app tidak menggambar apa pun atau crash.

Kodenya sudah siap di belakang saklar (`OVERLAY_INCLUDE_REJECTED`, default **mati**). Tinggal sepakati namanya — usul kami `rejected`, warna abu-abu putus-putus — lalu kami nyalakan.

**2. Gigi ter-flag crossbite memakai `role: flagged`, sama dengan displacement.**

Tabel kalian tidak punya role khusus crossbite, jadi keduanya kami beri `flagged`. Konsekuensinya app tidak bisa membedakan "gigi ini displaced" dari "gigi ini crossbite" hanya dari warna. Kalau perlu dibedakan, tambahkan satu role lagi.

---

## Ukuran & performa overlay

Diukur ke 22 pasien:

```
rata-rata 19.7 kB   maksimum 23.4 kB   (anggaran kalian 40 kB)
```

Sekitar 80–100 bentuk per pasien. `approxPolyDP` pada `eps_frac = 0.01` memangkas ~130 titik/gigi jadi ~11 titik/gigi. Kalau outline terlihat menyudut di layar, kami bisa turunkan ke 0.005 (~16 titik/gigi) — ruang anggarannya masih lega.

Overlay bisa dimatikan lewat `OVERLAY_ENABLED` kalau app suatu saat hanya butuh angka; kuncinya tetap ada dengan isi `null` supaya bentuk response tidak berubah.

---

## ⚠️ Satu penyimpangan yang perlu dikonfirmasi: `anterior_crossbite`

Contoh di kontrak §2 menunjukkan, untuk pasien dengan `overjet.value = 0.50`:

```json
"anterior_crossbite": { "value": null, "label": null, "side": null,
                        "reliable": false, "warnings": [] }
```

Ini bertabrakan dengan aturan wajib §5 nomor 1 dan §3: **`null` berarti tidak bisa dihitung**. Padahal dalam kasus itu crossbite anterior justru **bisa** ditentukan — overjet-nya positif, jadi jawabannya "tidak ada crossbite anterior". Mengirim `null` membuat app tidak bisa membedakan "sudah diperiksa, hasilnya tidak ada" dari "gagal diperiksa".

**Yang kami implementasikan:** `anterior_crossbite` adalah `Reading` penuh yang mencerminkan overjet (crossbite anterior secara definisi = overjet negatif, tidak ada pengukuran terpisah):

```json
"anterior_crossbite": { "value": 0.50, "label": "no anterior crossbite",
                        "side": "right", "reliable": true, "warnings": [] }
```

- `value` = nilai overjet yang sama
- `label` = `possible anterior crossbite` kalau `value < 0`, selain itu `no anterior crossbite`
- `null` **hanya** kalau overjet memang tidak bisa dihitung

Kalau app lebih suka perilaku di contoh kontrak, bilang saja — perubahannya satu fungsi di `report.py`. Kami memilih versi ini karena mematuhi aturan wajib yang kontrak sendiri tetapkan.

---

## Catatan implementasi

**`flagged_teeth` itu indeks, bukan nomor FDI.** Angkanya adalah posisi 1-based sepanjang rantai gigi dari kiri ke kanan gambar. Kami **tidak punya** penomoran FDI asli — detector FDI eksternal sudah dicoba dan gagal total (domain gap parah, terdokumentasi di `PROGRESS_SUMMARY.md`). Selama overlay belum ada, field ini sifatnya informatif saja.

**`posisi` di `crossbite_posterior.flagged` sengaja tetap bahasa Indonesia**, sesuai permintaan kontrak. Nilainya: 1 = gigi paling dekat midline, makin besar makin ke arah molar.

**`side` di `crossbite_posterior.flagged` adalah sisi GAMBAR**, bukan sisi anatomis pasien. Foto frontal dibelah di midline, lalu `kiri`/`kanan` dipetakan ke `left`/`right`. Kalau UI perlu menyebut sisi pasien, perlu disepakati dulu konvensinya (kiri pasien = kanan gambar pada foto frontal normal).

**Endpoint tambahan di luar kontrak** (silakan diabaikan kalau tidak perlu):
- `GET /v1/health` — status + daftar bobot model yang hilang. Berguna supaya app bisa menampilkan pesan jelas, bukan sekadar connection refused.
- `GET /v1/config` — konstanta yang sedang berlaku, untuk memverifikasi override benar-benar sampai.

**Path bobot model tidak bisa di-override lewat `config`** — kalau bisa, endpoint publik jadi bisa dipakai memuat file sembarangan dari disk server. Kunci lain yang tidak dikenal diabaikan diam-diam, sesuai kontrak.

**Mode stub sudah siap** (kontrak §7): `DHC_STUB=1 uvicorn app:app --port 8000`. Mengabaikan foto, membalas contoh statis. Ada test yang memastikan stub dan hasil asli punya bentuk yang sama, jadi stub yang basi akan ketahuan.

**Format foto yang diterima: JPEG, PNG, WebP, dan HEIC/HEIF.** HEIC penting karena itu format default kamera iPhone — app boleh mengirimnya langsung tanpa konversi. (Awalnya server menolak HEIC dan kelima analisis gagal; sudah diperbaiki dengan `pillow-heif`.) Kalau app tetap ingin mengonversi ke JPEG di sisi klien, itu juga tidak masalah dan sedikit menghemat bandwidth.

**Ada halaman coba-coba interaktif** di `http://<host>:8000/docs` (Swagger, otomatis dari FastAPI). Berguna untuk memeriksa bentuk response sebelum menulis kode klien. Satu jebakan kecil: Swagger mengisi field `Form` opsional dengan teks placeholder `string`. Server sudah memperlakukannya sebagai kosong, jadi tidak perlu dikhawatirkan — tapi kalau mengirim `config` sungguhan, isinya harus JSON objek yang valid.

---

## Yang perlu diingat saat merancang UI

Dua hal ini paling sering terlewat dan dampaknya paling besar:

1. **"Tidak bisa dihitung" itu sering, bukan langka.** Detector kaninus meleset di 25% foto; 7 dari 44 foto pada audit sama sekali tidak menghasilkan Overjet/Overbite. Ini batas kemampuan model, bukan bug yang akan hilang. Perlakukan sebagai state kelas satu.

2. **`crowding.lower` selalu `reliable: false`.** Ambangnya dikalibrasi hanya dari lengkung atas, jadi baseline lengkung bawah belum teruji (brief §8.5). Bukan berarti angkanya pasti salah — hanya belum bisa dipertanggungjawabkan.

Selebihnya, semua aturan wajib di §5 sudah dipatuhi dan ada test-nya di `tests/test_api.py`.
