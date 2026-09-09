# Payment Setup

Project menyediakan dua pilihan callback otomatis:

- Cashi → **QR Otomatis 1**
- BayarGG → **QR Otomatis 2**

## Cashi

Variables:

```text
CASHI_API_KEY=
CASHI_SECRET_KEY=
CASHI_BASE_URL=https://cashi.id
CASHI_PAYMENT_CHANNEL=QRIS_CUSTOM
PAYMENT_MODE=both
```

Gunakan endpoint/credential yang diberikan akun Cashi aktif. Jangan menyalin credential ke source code.

## BayarGG

Variables:

```text
BAYARGG_API_KEY=
BAYARGG_MERCHANT=
BAYARGG_WEBHOOK_SECRET=
PUBLIC_BASE_URL=https://domain-kamu
```

Webhook path project:

```text
/bayargg/webhook
```

## Prinsip keamanan

- Validasi signature/secret callback.
- Jangan menganggap redirect browser sebagai bukti pembayaran.
- Gunakan invoice/order ID unik.
- Proses callback secara idempotent.
- Jangan mengkredit saldo dua kali jika provider melakukan retry webhook.
