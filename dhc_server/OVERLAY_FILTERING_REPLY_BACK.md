# Balasan: keempatnya sudah jalan, plus jawaban soal displacement

Poin 1–4 dari daftar kalian sudah diimplementasikan dan sudah ada di server. Poin 5 (displacement) kami jawab dengan pengukuran di bagian akhir — jawabannya lebih menarik dari dugaan kami sendiri.

Server sudah mengirim bentuk baru ini sekarang. Karena decoder kalian sudah toleran (poin 1.3), tidak ada yang perlu dirilis bersamaan — silakan pasang di sisi kalian kapan pun.

---

## 1. Layer `rejected` — menyala

`OVERLAY_INCLUDE_REJECTED` sudah `true`, nama role `rejected` seperti yang kalian sebut.

Contoh nyata sudah ada di stub: satu bentuk dari `2018.05` lateral kanan — **serpihan 13×20 px di luar mulut** yang dulu terpilih jadi anchor insisivus dan menghasilkan overjet 9.33. Itu benda yang selama ini cuma bisa kami ceritakan; sekarang bisa dilihat.

`params`-nya diisi parameter yang bisa dijelaskannya: di lateral `["overjet", "overbite", "anterior_crossbite", "angle"]`, di oklusal `["missing", "crowding"]`. Jadi saat klinisi membuka overjet lalu menyalakan layer itu, yang muncul adalah serpihan yang relevan dengan lateral, bukan semuanya.

## 2. `params` — terpasang di semua bentuk

Nilai memakai kunci response apa adanya, termasuk `angle`. `params: []` untuk `tooth` dan `archCurve` seperti disepakati.

Diuji dengan meniru sisi kalian — filter dijalankan pada koordinat 0–1 lalu digambar ke foto:

| Buka | Yang tampil (di luar outline) |
|---|---|
| `overjet` | box insisivus + 2 garis ukur |
| `angle` | box kaninus & distal, insisivus hilang |
| `crowding` | gigi ter-flag + kurva lengkung |
| `missing` | celah + kurva lengkung |
| `crossbite_posterior` | gigi ter-flag di frontal |

Ada test yang memastikan **kalau sebuah parameter punya temuan, bentuknya pasti ada**. Parameter yang hasilnya normal memang tidak punya bentuk tambahan — yang tampil cuma outline. Yang kami jaga adalah kasus sebaliknya: ada angka bermasalah tapi tidak ada apa pun yang bisa ditunjuk di layar.

## 3. Box insisivus — dikirim

Insisivus, molar, dan kaninus yang dipakai mengukur, masing-masing untuk lengkung atas & bawah.

## 4. `role: reference` — dipakai, awalan `det ` dibuang

Usul kalian kami ambil utuh:

| Bentuk | `role` | `label` |
|---|---|---|
| Keluaran detector | `anchor` | `canine`, `distal` |
| Gigi yang dipakai mengukur | `reference` | `canine`, `molar`, `incisor` |

Alasan kalian benar dan lebih baik dari usul kami: pada kasus 9.33, box `anchor` dan `reference` untuk insisivus **tidak akan bertumpuk sama sekali** — dua warna yang meleset jauh, terbaca seketika. Awalan teks empat huruf di layar HP tidak akan menyampaikan itu.

## Ukuran

```
sebelum : rata-rata 19.7 kB   maks 23.4 kB
sesudah : rata-rata 22.4 kB   maks 26.9 kB     (anggaran 40 kB)
```

Naik ~14%, masih lega. Sekitar 96 bentuk per pasien.

## Stub sudah diperbarui

Mode stub kini memuat **kedelapan role** dan **ketujuh nilai `params`**, jadi filter dan setiap warna bisa diuji tanpa menyalakan model. Isinya sengaja gabungan dua pasien supaya semua role terwakili — sebagian besar `2018.08`, ditambah satu `rejected` dari `2018.05`. Ada test yang gagal kalau stub tidak lagi mencakup semuanya, supaya tidak diam-diam basi.

---

## 5. Displacement vs crowding — beda, dan datanya cukup tegas

Kami ukur ke 22 pasien, bukan menjawab dari teori.

**Keduanya mengukur sumbu yang berbeda:**

- **Displacement (frontal)** — simpangan **vertikal** tiap gigi dari kurva lengkung yang di-fit, dinormalisasi ke tinggi gigi. Menangkap gigi yang duduk lebih tinggi/rendah dari barisannya.
- **Crowding (oklusal, Little's Index)** — simpangan **buko-lingual** di titik kontak antar gigi bertetangga. Menangkap gigi yang berputar atau terdorong ke dalam/luar.

**Hasil pengukuran:**

```
korelasi Pearson (jumlah displacement vs crowding maks) = -0.215

keduanya menyala   : 12 pasien
HANYA displacement :  3 pasien   <- crowding tidak menangkapnya
HANYA crowding     :  6 pasien   <- displacement tidak menangkapnya
```

Korelasinya praktis nol (dan sedikit negatif). Sembilan dari 21 pasien hanya ke-flag oleh salah satunya. Jadi jawabannya: **bukan hal yang sama dilihat dari dua sudut** — keduanya benar-benar mengukur hal berbeda.

### Tapi kami sarankan JANGAN menjadikannya parameter dulu

Meski secara teknis berbeda, displacement adalah bagian **paling lemah validasinya** di seluruh pipeline:

- Berasal dari `10_frontal_missing_displacement.ipynb`, bagian tertua yang belum pernah ditinjau ulang
- Ambang `0.35` tidak pernah divalidasi ke satu pun kasus yang dikonfirmasi klinisi — murni angka awal
- Tetangganya di notebook yang sama (Missing versi frontal) sudah terbukti tidak andal dan diturunkan jadi sekadar cross-check
- Kami belum pernah memeriksa apakah yang ke-flag itu benar-benar gigi bermasalah

Menjadikannya parameter ke-7 berarti menaikkan ukuran yang paling belum teruji ke status setara Overjet dan Crowding — yang keduanya sudah divalidasi ke kasus nyata. Menurut kami itu keliru urutannya.

**Usul kami:** biarkan seperti sekarang (tidak dikirim, tidak jadi parameter) sampai ada validasi ke kasus yang dikonfirmasi. Kalau ternyata memang bermakna klinis, menambahkannya nanti murah: bentuknya sudah dihitung pipeline, tinggal diberi `params: ["displacement"]`.

Kalau kalian ingin tetap menampilkannya lebih dulu sebagai layer eksplorasi — bukan sebagai temuan — bilang saja, kami kirimkan dengan penandaan yang jelas bahwa ambangnya belum tervalidasi.

---

## Soal "jangan menahan sinyal karena kami"

Terima kasih sudah memperbaiki decoding-nya, dan kami akan memanfaatkannya. Tapi kami tetap akan **memberi tahu lebih dulu sebelum menambah role baru**, bukan karena takut app-nya pecah, melainkan karena role tanpa warna berarti klinisi melihat garis abu-abu yang tidak bisa ditafsirkan. Itu tetap kegagalan, hanya lebih senyap.

## Ringkasan

| Item | Status |
|---|---|
| 1. Layer `rejected` | selesai |
| 2. Field `params` | selesai |
| 3. Box insisivus | selesai |
| 4. Role `reference` | selesai |
| 5. Displacement | terjawab — berbeda, tapi kami sarankan belum dijadikan parameter |

40 test lolos, termasuk yang mengunci aturan filter, konsistensi label, dan kelengkapan stub.
