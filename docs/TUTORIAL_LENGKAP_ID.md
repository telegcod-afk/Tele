# Tutorial Lengkap — MEKTPL Project Baru

## 1. Persiapan Telegram

### A. Buat bot
1. Buka BotFather.
2. `/newbot`.
3. Simpan token.
4. Isi `BOT_TOKEN`.
5. Isi `BOT_USERNAME` tanpa `@`.

### B. Storage Channel
Buat channel privat khusus penyimpanan media.

- Tambahkan bot sebagai administrator.
- Bot membutuhkan izin yang diperlukan untuk menerima/meng-copy media.
- Isi `STORAGE_CHANNEL_ID`.
- Jangan jadikan storage channel sebagai channel publik untuk pengguna.

### C. Force Subscribe
Gunakan tepat **2 channel**.

- Tambahkan bot sebagai admin pada kedua channel agar `get_chat_member` dapat digunakan.
- Isi `FORCE_CHANNEL_1` dan `FORCE_CHANNEL_2` jika handler/config proyek menggunakannya.
- Flow force-sub tidak menyediakan tombol share referral.
- Setelah kedua channel terpenuhi, user kembali ke Dashboard.

## 2. PostgreSQL / Supabase

1. Buat project PostgreSQL/Supabase baru.
2. Ambil connection string PostgreSQL.
3. Isi `DATABASE_URL`.
4. Buka SQL Editor.
5. Jalankan **hanya `database.sql`**.
6. Jangan memasukkan token Telegram/API key ke SQL.

SQL dibuat idempotent untuk objek utama (`IF NOT EXISTS`/compatibility logic), tetapi untuk project benar-benar baru tetap disarankan menjalankan SQL sekali dari database kosong.

## 3. Environment Variables

Salin `.env.example` menjadi `.env` untuk pengembangan lokal.

Minimum:

```text
BOT_TOKEN=
BOT_USERNAME=
DATABASE_URL=
STORAGE_CHANNEL_ID=
PUBLIC_BASE_URL=
FORCE_CHANNEL_1=
FORCE_CHANNEL_2=
OWNER_ID=
ADMIN_IDS=
NOTIF_CHANNEL_ID=
```

Jangan commit `.env` ke GitHub. `.gitignore` sudah disiapkan.

## 4. Payment Cashi — QR Otomatis 1

Isi:

```text
CASHI_API_KEY=
CASHI_SECRET_KEY=
CASHI_BASE_URL=https://cashi.id
CASHI_PAYMENT_CHANNEL=QRIS_CUSTOM
PAYMENT_MODE=both
```

Pastikan endpoint callback/webhook pada provider diarahkan ke public URL aplikasi sesuai konfigurasi handler Cashi.

Jangan menebak format signature/body provider. Gunakan dokumentasi/API account Cashi yang aktif saat deployment dan samakan secret/signature dengan handler di project.

## 5. Payment BayarGG — QR Otomatis 2

Isi:

```text
BAYARGG_API_KEY=
BAYARGG_MERCHANT=
BAYARGG_WEBHOOK_SECRET=
PUBLIC_BASE_URL=https://DOMAIN-RAILWAY-KAMU
```

Endpoint BayarGG yang digunakan project:

```text
POST /bayargg/webhook
```

URL lengkap:

```text
https://DOMAIN-RAILWAY-KAMU/bayargg/webhook
```

Jika provider mensyaratkan URL HTTPS publik, gunakan domain Railway yang aktif.

## 6. Jalankan lokal

Python 3.11+ disarankan.

```bash
python -m venv .venv
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Windows:

```powershell
.venv\Scripts\activate
```

Install:

```bash
pip install -r requirements.txt
```

Jalankan:

```bash
uvicorn main:app --host 0.0.0.0 --port 8080
```

Cek:

```text
http://127.0.0.1:8080/health
```

## 7. Deploy Railway

1. Push seluruh isi project ke repository baru.
2. Buat project baru di Railway.
3. Hubungkan repository.
4. Masukkan semua environment variables di Railway Variables.
5. Railway akan membaca `railway.toml`.
6. Pastikan port memakai `$PORT`.
7. Setelah deploy, buka:

```text
https://DOMAIN-RAILWAY-KAMU/health
```

Harus mengembalikan status `ok`.

## 8. Alur upload yang aman

Flow upload project:

```text
User pilih Up File
        ↓
Bot menerima media
        ↓
Queue / sequential processing
        ↓
1 media → storage channel
        ↓
Simpan message_id/file reference
        ↓
Media berikutnya
        ↓
Selesai
        ↓
Generate code + media codes
```

Jangan mengubah flow menjadi `asyncio.gather()` untuk mengirim banyak media sekaligus. Burst besar dapat memicu rate limit.

## 9. Alur Open All

```text
Open All
   ↓
Media #1
   ↓ 2 detik
Media #2
   ↓ 2 detik
...
   ↓
Media #10
   ↓
Pause
   ↓
[▶️ Lanjut Kirim] [⛔ Stop Kirim]
```

Jeda ini adalah mitigasi rate-limit, bukan jaminan bebas pembatasan Telegram.

## 10. Media Code

Contoh:

```text
ABC123-m001
ABC123-m002
ABC123-m003
```

Code utama tetap menjadi identifier file/marketplace; media code digunakan untuk mengidentifikasi item individual.

## 11. Marketplace

Fitur yang disediakan:

- daftar marketplace
- kategori
- detail item
- pencarian code
- favorit
- like/no-like
- rating
- pembelian
- statistik yang digunakan handler/database

Pastikan data rating/favorite di database berhasil dibuat setelah SQL dijalankan.

## 12. Pembayaran berhasil

Flow yang diharapkan:

```text
User pilih QR Otomatis 1 / 2
          ↓
Invoice dibuat
          ↓
User bayar
          ↓
Provider webhook
          ↓
Server verifikasi callback
          ↓
Database menandai payment sukses secara idempotent
          ↓
Akses media dibuka
          ↓
Notifikasi user
          ↓
[📄 Open Page] [📦 Open All]
          ↓
Notifikasi transaksi ke channel transaksi
```

Jangan menganggap pembayaran sukses hanya karena user kembali dari halaman pembayaran. Status harus berasal dari callback/status API provider yang diverifikasi.

## 13. Checklist sebelum production

- [ ] Bot token benar.
- [ ] Bot username benar.
- [ ] Database SQL sukses tanpa error.
- [ ] Storage channel ID benar.
- [ ] Bot admin di storage.
- [ ] Dua force-sub channel benar.
- [ ] Bot dapat mengecek membership kedua channel.
- [ ] `PUBLIC_BASE_URL` HTTPS.
- [ ] Cashi API key/secret benar.
- [ ] BayarGG API key/webhook secret benar.
- [ ] Webhook provider mengarah ke Railway.
- [ ] `/health` = `ok`.
- [ ] Upload 1 media sukses.
- [ ] Upload 5+ media sukses secara sequential.
- [ ] Open All berhenti setelah 10 media.
- [ ] Lanjut/Stop berfungsi.
- [ ] Like/No Like/Favorit berfungsi.
- [ ] Rating muncul di marketplace.
- [ ] Cari Code berfungsi.
- [ ] Pembayaran Cashi sukses.
- [ ] Pembayaran BayarGG sukses.
- [ ] Webhook tidak menggandakan saldo/pembelian jika callback dikirim dua kali.
- [ ] Tidak ada secret di GitHub.

## 14. Troubleshooting

### Bot tidak start
Cek Railway logs dan cari:

```text
BOT_TOKEN
DATABASE_URL
```

### `/health` hidup tetapi bot tidak merespons
Periksa `MAIN_BOT STARTED` di logs dan pastikan tidak ada `TelegramConflictError` dari instance bot lain.

### Force-sub selalu gagal
Pastikan bot admin di kedua channel dan ID channel benar.

### Upload gagal
Pastikan bot admin storage channel dan `STORAGE_CHANNEL_ID` benar.

### Pembayaran pending
Periksa:

- invoice/order ID
- provider response
- webhook URL
- webhook secret/signature
- Railway logs

### Telegram RetryAfter
Jangan menghapus delay. `RetryAfter` harus dihormati. Hindari parallel send.

## 15. Backup

Backup database PostgreSQL/Supabase secara berkala. Storage Telegram hanya menyimpan media yang direferensikan oleh database; jangan menghapus record database tanpa memahami dampaknya terhadap code/media mapping.
