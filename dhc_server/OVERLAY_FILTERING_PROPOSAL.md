# Usul: satu field lagi supaya overlay bisa difilter per parameter

Ini usul **aditif** ke `API_CONTRACT_OVERLAYS.md`. Tidak ada yang dihapus atau diubah artinya, jadi app yang belum memakainya tetap jalan seperti sekarang.

Ringkasnya: kami ingin menambah satu field `params` di tiap bentuk, dan menambah beberapa box anchor yang sekarang belum dikirim.

---

## 1. Yang ingin dicapai

Saat klinisi membuka satu parameter, layar hanya menampilkan bentuk yang relevan untuk parameter itu — bukan semua anotasi sekaligus. Outline segmentasi tetap tampil di semua tampilan sebagai konteks.

| Parameter dibuka | Bentuk tambahan yang tampil |
|---|---|
| `overjet`, `overbite`, `anterior_crossbite` | box insisivus atas & bawah + garis pengukuran |
| `angle` | box kaninus & distal |
| `crossbite_posterior` | gigi yang ter-flag crossbite (frontal) |
| `missing` — frontal | box celah frontal |
| `missing` — oklusal | celah oklusal saja (bukan gigi crowding) |
| `crowding` | gigi crowding saja |

Selalu tampil, apa pun parameternya:
- `role: tooth` — outline segmentasi, sebagai konteks
- `role: archCurve` — di kedua view oklusal; celah digambar menempel pada kurva ini, tanpa kurvanya posisi celah jadi sulit dibaca

---

## 2. Kenapa ini tidak bisa dilakukan app dengan data yang ada sekarang

Kami sudah memeriksa apakah app bisa memfilter cukup dari `role` + nama view. Sebagian bisa, tapi ada dua yang buntu:

**`role: anchor` mencampur dua parameter berbeda.** Box insisivus (untuk Overjet/Overbite) dan box kaninus & distal (untuk Angle) sama-sama `anchor`. Tidak ada cara memisahkannya.

**`role: flagged` di frontal mencampur displacement dengan crossbite posterior.** Ini yang benar-benar tidak terpecahkan — dua aturan berbeda menandai gigi yang berbeda, tapi hasilnya identik di JSON.

Yang lain sebenarnya sudah bisa dibedakan lewat nama view (`gap` di frontal vs di oklusal, `flagged` di oklusal pasti crowding).

---

## 3. Usul: field `params`

Satu field baru di tiap bentuk — daftar parameter yang bentuk itu bantu periksa:

```json
{
  "kind": "box",
  "role": "anchor",
  "label": "incisor",
  "params": ["overjet", "overbite", "anterior_crossbite"],
  "points": [[0.31, 0.42], [0.37, 0.55]]
}
```

Berupa **daftar** karena satu bentuk memang sering melayani beberapa parameter — box insisivus yang sama dipakai Overjet, Overbite, dan Crossbite anterior. Menduplikasi bentuknya hanya akan memboroskan byte.

Nilainya memakai **kunci yang sama persis dengan response utama**, jadi tidak perlu tabel terjemahan:

```
overjet · overbite · anterior_crossbite · angle · crossbite_posterior · missing · crowding
```

`params: []` berarti "selalu tampilkan" — dipakai `tooth` dan `archCurve`.

### Aturan di sisi app

```
gambar sebuah bentuk jika:
    bentuk.params kosong            (konteks: outline & kurva lengkung)
    ATAU parameter_aktif ada di bentuk.params
```

Itu saja. Tidak ada tabel pemetaan yang perlu dipelihara di sisi app.

---

## 4. Pemetaan lengkap yang akan kami kirim

| View | `role` | `label` | `params` |
|---|---|---|---|
| lateral | `tooth` | – | `[]` |
| lateral | `anchor` | `incisor` | `overjet`, `overbite`, `anterior_crossbite` |
| lateral | `anchor` | `molar` | `angle` |
| lateral | `anchor` | `canine` | `angle` |
| lateral | `anchor` | `det canine` | `angle` |
| lateral | `anchor` | `det distal` | `angle` |
| lateral | `measurement` | – | `overjet`, `overbite`, `anterior_crossbite` |
| frontal | `tooth` | – | `[]` |
| frontal | `flagged` | – | `crossbite_posterior` |
| frontal | `gap` | – | `missing` |
| oklusal | `tooth` | – | `[]` |
| oklusal | `archCurve` | – | `[]` |
| oklusal | `flagged` | indeks gigi | `crowding` |
| oklusal | `gap` | – | `missing` |

Catatan: gigi yang ter-flag **displacement** di frontal untuk sementara tidak kami kirim, karena `displacement` bukan salah satu parameter di response utama. Kalau app ingin menampilkannya, beri tahu kami dan akan kami masukkan dengan `params: ["displacement"]`.

---

## 5. Yang berubah dari kiriman sekarang

**Tambahan bentuk baru: box gigi yang dipakai mengukur.** Sekarang `role: anchor` hanya berisi box dari detector (kaninus & distal). Box insisivus — gigi yang mendasari Overjet/Overbite — **belum dikirim sama sekali**.

Ini penting, dan sejalan dengan alasan terkuat di addendum kalian ("failures inspectable"). Kasus overjet 9.33 di audit kami **bukan** kegagalan detector: detector menemukan kaninusnya dengan benar. Yang salah adalah insisivus, yang diturunkan dengan menghitung posisi dari kaninus lalu mendarat di serpihan mask di luar mulut.

Artinya pada kasus seperti itu, box `anchor` detector akan terlihat wajar sementara angkanya ngawur — dan klinisi tidak punya petunjuk visual apa pun tentang gigi mana yang keliru dianggap insisivus. Dengan box insisivus tergambar, kesalahannya langsung terlihat.

**Label detector dibedakan.** Karena box kaninus dari detector dan gigi kaninus yang dipakai Angle bisa **berbeda** (dan kalau berbeda, itu sendiri informasi penting), keduanya perlu label berbeda: `det canine` / `det distal` untuk keluaran detector, `canine` / `molar` / `incisor` untuk gigi yang dipakai mengukur.

**Dampak ukuran: kecil.** Sekitar +6 box per foto lateral. Payload sekarang rata-rata 19.7 kB per pasien (maksimum 23.4 kB dari 22 pasien) terhadap anggaran 40 kB — masih lega.

---

## 6. Kompatibilitas

- Field `params` bersifat **tambahan**. App yang mengabaikannya akan berperilaku persis seperti sekarang.
- Tidak ada `role` baru. Palet warna kalian tidak berubah.
- Tidak ada bentuk yang dihapus.
- Mode stub akan ikut diperbarui supaya app bisa mengembangkan filternya tanpa menunggu server asli.

---

## 7. Yang kami butuhkan dari kalian

1. Setuju dengan nama field `params` dan daftar nilainya? Kalau ada nama lain yang lebih cocok dengan model data app, silakan — bagi kami penamaannya tidak mengikat.
2. Perlu gigi ter-flag **displacement** di frontal ikut dikirim?
3. Label `det canine` / `det distal` cukup jelas, atau ada penamaan yang lebih pas untuk UI?

Begitu tiga hal ini disepakati, implementasinya singkat — pemetaannya sudah ada, tinggal disematkan ke tiap bentuk.
