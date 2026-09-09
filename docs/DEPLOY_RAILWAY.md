# Deploy Railway — Ringkas

1. Upload project ke GitHub.
2. Buat Railway Project → Deploy from GitHub.
3. Tambahkan Variables dari `.env.example`.
4. Jangan upload `.env`.
5. Railway menjalankan:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

6. Setelah deployment, tes `/health`.
7. Pasang webhook provider ke domain HTTPS Railway.
8. Tes Telegram `/start`.

Jika memakai custom domain, update `PUBLIC_BASE_URL` ke domain tersebut.
