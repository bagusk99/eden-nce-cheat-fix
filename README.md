# eden-cheat-tools

Memperbaiki cheat Atmosphere yang tidak jalan / bikin crash di **Eden (Android) mode CPU NCE**.

## Masalahnya

Di mode NCE, Eden kadang menaruh satu halaman patch miliknya **di depan** kode game (`main`),
tapi cheat engine Eden masih memakai alamat awal yang lama. Semua alamat `main+XXXX` di cheat
jadi meleset sebesar ukuran halaman itu:

- cheat yang **membaca/menulis data** (HP, gold, dll.) → tidak berefek
- cheat yang **menulis kode** (master code, code cave) → menimpa kode asli → game crash (`SIGILL`)

Di mode JIT (Dynarmic) masalah ini tidak ada.

Besar geseran **bukan konstanta global**: bisa beda per game dan per versi Eden.
Contoh terukur: Octopath Traveler II (v1.0.0 & v1.1.1), Eden nightly `ceadc10` → `0x1000`.

## Kebutuhan

- `adb` tersambung ke HP (`adb devices`)
- Python 3 (stdlib saja)
- **Build ID** game (lihat di EDC / Eden cheat manager). Nama file cheat = build ID.

## Cara pakai

```bash
cd ~/apps/eden-cheat-tools

# 1. pasang detector (cheat read-only, tidak menulis apa pun)
python3 nce_detect.py install <TitleID> <BuildID>

# 2. di HP: CPU backend = NCE, jalankan game ±10 detik, lalu TUTUP game
#    (Eden baru menulis log ke file saat game ditutup)

# 3. baca hasil + perbaiki otomatis
python3 nce_detect.py read <TitleID> <BuildID>
#    → "no shift"      : cheat aman dipakai apa adanya, selesai
#    → "... confirmed" : detector dihapus, geseran disimpan di HP, semua cheat build itu digeser
#    → "not confirmed" : tidak ada yang diubah, detector dibiarkan

# nanti pasang cheat baru untuk game yang sama → cukup:
python3 nce_detect.py fix <TitleID> <BuildID>
```

Contoh OT2 v1.1.1:

```bash
python3 nce_detect.py install 0100A3501946E000 0D9649011312F62E
python3 nce_detect.py read    0100A3501946E000 0D9649011312F62E
```

TitleID / BuildID boleh **ujungnya saja** (dicocokkan dengan isi HP: folder `load/` dan
nama file cheat). Tidak ketemu atau lebih dari satu yang cocok → error + daftar kandidat.

```bash
python3 nce_detect.py fix ...E000 ...F62E      # = 0100A3501946E000 0D9649011312F62E
```

`install` untuk build yang belum punya file cheat sama sekali → BuildID harus lengkap.

Konversi manual satu file (tanpa HP):

```bash
python3 nce_shift.py input.txt output.txt 1000
```

Self-test:

```bash
python3 nce_detect.py --test
python3 nce_shift.py --test
```

## Cara kerja

### Detector (`nce_detect.py install` / `read`)

Detector adalah cheat berisi 16 opcode `DebugLog` yang membaca 8 byte di
`main+0x0000, +0x1000, … +0xF000` dan menulisnya ke log Eden. Lalu `read` menganalisis:

1. **`main+0` adalah awal modul asli** → tidak ada geseran.
   Ciri awal modul NSO: kata 32-bit kedua = offset header `MOD0` (kecil, kelipatan 4).
2. **`main+0` berisi instruksi `B +X`** (`0x14xxxxxx`) → itu halaman patch Eden; kata pertamanya
   selalu lompatan ke kode game. `X = imm26 × 4` = besar geseran.
   Lalu dicek: apakah di `main+X` benar ada awal modul? Kalau ya → **confirmed**.
3. Selain itu → **tidak dikonfirmasi**, tool tidak menyarankan geseran apa pun.

Contoh nyata OT2: `main+0 = F90007FE 14000400` → `B +0x400×4 = +0x1000`,
dan `main+0x1000 = 00000008 00000000` (offset MOD0 = 8) → confirmed.

Setelah confirmed: folder detector dihapus, geseran disimpan di
`load/<TitleID>/.nce_shift_<BuildID>` (diabaikan Eden), lalu `fix` dijalankan otomatis.
`fix` tanpa angka memakai geseran yang tersimpan itu; `fix <TitleID> <BuildID> <hex>` untuk
memaksa angka lain.

### Converter (`nce_shift.py`, dipakai oleh `fix`)

Format cheat: deretan kata hex 8 digit. **Baris & spasi tidak berarti** bagi Eden; jumlah kata
per opcode ditentukan oleh digit pertama. Converter mem-parse per opcode (bukan per baris),
menambah geseran ke alamat yang relatif terhadap `main`, lalu menulis ulang satu opcode per baris.

| Opcode | Arti | Digeser bila |
|---|---|---|
| `0TMR00AA AAAAAAAA V…` | tulis nilai tetap ke memori | `M = 0` (main) |
| `1TMC00AA AAAAAAAA V…` | `if` memori vs nilai | `M = 0` |
| `5TMR00AA AAAAAAAA` | baca memori ke register | `M = 0`, mode alamat absolut |
| `FFFTI0Ma aaaaaaaa` | debug log dari memori | `M = 0` |
| `2…`, `3…`, `4…`, `6…`, `7…`, `8…`, `C0TcS4…` | kontrol / register | tidak pernah |

Yang **tidak** digeser: alamat relatif register (`580F1000 …`), heap (`M = 1`), dan isi
instruksi ARM64 yang ditulis cheat (branch `B` itu relatif, jadi tetap benar).
Opcode yang belum dikenal → converter **berhenti dengan error**, tidak menebak.

### Pengaman `fix`

- File asli di-backup ke `/sdcard/Download/nce_backup/<TitleID>-<waktu>/`.
- Tiap folder `cheats/` yang sudah digeser diberi penanda `.nce_shifted`; `fix` berikutnya
  melewatinya, jadi aman dijalankan ulang (tidak tergeser dua kali).
- Pasang cheat baru dari EDC → jalankan `fix` lagi; hanya yang belum ditandai yang digeser.

## Batasan

- Geseran > `0xF000` terdeteksi tapi tidak bisa dikonfirmasi.
- Opcode jarang (`9…` aritmetika register, `A…` store register, `C1`–`C3`, dll.) belum didukung.
- Kalau mode CPU diganti ke JIT, atau Eden memperbaiki bug ini, cheat yang sudah digeser
  jadi salah → kembalikan dari backup.
- Folder cheat dijalankan Eden **urut abjad**. Master code harus jalan paling awal
  (mis. beri nama `00 master code`).
