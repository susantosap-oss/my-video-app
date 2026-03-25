# Video Generator — Dokumentasi Sistem

> **Status:** ✅ Local Test OK — 25 Mar 2026
> **Next:** Build & Deploy ke Google Cloud Run
> **Stack:** FastAPI + SQLite + Tailwind CSS + MoviePy + Gemini/Claude AI

---

## Daftar Isi

1. [Arsitektur Sistem](#1-arsitektur-sistem)
2. [Struktur File](#2-struktur-file)
3. [Database Schema](#3-database-schema)
4. [User Roles & Permissions](#4-user-roles--permissions)
5. [Paket Berlangganan](#5-paket-berlangganan)
6. [Alur Autentikasi](#6-alur-autentikasi)
7. [Alur Render Video](#7-alur-render-video)
8. [Full AI Mode](#8-full-ai-mode)
9. [Kuota & Billing AI](#9-kuota--billing-ai)
10. [API Endpoints](#10-api-endpoints)
11. [Frontend — Halaman & Fitur per Role](#11-frontend--halaman--fitur-per-role)
12. [Alur Pendaftaran Subscriber](#12-alur-pendaftaran-subscriber)
13. [Watermark Trial](#13-watermark-trial)
14. [Dashboard Owner](#14-dashboard-owner)
15. [Catatan Deploy](#15-catatan-deploy)

---

## 1. Arsitektur Sistem

```
┌─────────────────────────────────────────┐
│           Browser (Client)              │
│  login.html  /  index.html (Tailwind)   │
└─────────────────┬───────────────────────┘
                  │ HTTP/REST (Bearer Token)
┌─────────────────▼───────────────────────┐
│         FastAPI  (api.py)               │
│  Auth · Session · Upload · Render       │
│  Admin · AI-Spec · Download             │
└──────┬──────────┬──────────┬────────────┘
       │          │          │
  ┌────▼───┐ ┌───▼────┐ ┌──▼──────────────┐
  │SQLite  │ │Render  │ │ AI Providers     │
  │database│ │Engine  │ │ Gemini 2.0 Flash │
  │.db     │ │MoviePy │ │ Claude Haiku     │
  └────────┘ └────────┘ └──────────────────┘
```

**Deploy Target:** Google Cloud Run
**Start command:** `uvicorn api:app --host 0.0.0.0 --port $PORT`

---

## 2. Struktur File

| File | Fungsi |
|------|--------|
| `api.py` | FastAPI backend — semua endpoint REST |
| `render_engine.py` | Core render: clip processing, caption, color grade, pass1+2 |
| `ai_spec.py` | Full AI spec generator — Gemini & Anthropic client |
| `database.py` | SQLite ORM — users, sessions, packages, site_settings |
| `auth.py` | Login / logout / session token management |
| `static/index.html` | Main app UI (Tailwind dark+gold theme) |
| `static/login.html` | Halaman login — bersih, hanya form |
| `VidGen.py` | Streamlit app lama (dipertahankan, tetap bisa jalan terpisah) |
| `uploads/` | Temporary upload files per session |
| `output/` | Hasil render sementara (dihapus setelah download) |
| `vidgen_users.db` | SQLite database file |
| `fonts/` | Custom font files (.ttf) untuk caption |
| `nltk_data/` | NLTK offline data untuk NLP caption |

---

## 3. Database Schema

### Tabel `users`
| Kolom | Tipe | Keterangan |
|-------|------|------------|
| id | INTEGER PK | Auto increment |
| username | TEXT UNIQUE | Nama login |
| password_hash | TEXT | SHA-256 hash password |
| email | TEXT | Email atau nomor WA |
| user_type | TEXT | `owner` / `mansion_team` / `subscriber` / `trial` |
| package | TEXT | `unlimited` / `trial` / `basic` / `lite` / `pro` |
| videos_used | INTEGER | Jumlah video dirender bulan ini |
| billing_month | TEXT | Format `YYYY-MM` — reset hitungan tiap bulan baru |
| is_active | INTEGER | `1` = aktif, `0` = nonaktif |
| created_at | TEXT | Timestamp pembuatan akun |

### Tabel `sessions`
| Kolom | Tipe | Keterangan |
|-------|------|------------|
| token | TEXT PK | Token autentikasi (urlsafe 32 byte) |
| user_id | INTEGER FK | Referensi ke `users.id` |
| expires_at | TEXT | Expired 7 hari setelah login |

### Tabel `packages`
| Kolom | Tipe | Keterangan |
|-------|------|------------|
| key | TEXT PK | `unlimited` / `trial` / `basic` / `lite` / `pro` |
| label | TEXT | Nama tampil (editable oleh owner) |
| videos_limit | INTEGER | `-1` = unlimited, angka = batas per bulan |
| max_duration | INTEGER | Maks durasi video dalam detik |
| full_ai | INTEGER | `1` = Full AI tersedia, `0` = tidak |
| price | INTEGER | Harga dalam Rupiah (editable oleh owner) |

### Tabel `site_settings`
| Kolom | Tipe | Keterangan |
|-------|------|------------|
| key | TEXT PK | `subscribe_terms` / `subscribe_howto` / `contact_wa` |
| value | TEXT | Konten teks (editable oleh owner) |

---

## 4. User Roles & Permissions

### Hierarki Role

```
owner (Admin)
  └── Semua akses mansion_team
  └── + Manajemen Subscriber (tambah/edit/nonaktif/reset pw)
  └── + Pengaturan Paket (harga, limit, durasi)
  └── + Edit Info Berlangganan (ketentuan, cara subscribe, kontak WA)

mansion_team (Mansion tim)
  └── Akses penuh fitur render (tanpa batas kuota)
  └── Tidak bisa ubah paket / kelola subscriber
  └── Tidak ada fitur Ganti Password
  └── Footer: "Mansion Video Generator"

subscriber (Basic / Lite / Pro)
  └── Akses render sesuai kuota paket
  └── Full AI tersedia
  └── Bisa Ganti Password sendiri
  └── Footer: "Video Generator"

trial
  └── Akses render, max 10 detik, tanpa Full AI
  └── Video output diberi watermark "VieCut"
  └── Tampil Info Berlangganan (paket + cara subscribe)
  └── Tidak bisa Ganti Password
  └── Footer: "Video Generator"
```

### Default Akun Sistem

| Username | Password | Role | Package |
|----------|----------|------|---------|
| `Admin` | `adnin098765` | `owner` | unlimited |
| `Mansion tim` | `mansion2026` | `mansion_team` | unlimited |
| `Trial` | `Trial` | `trial` | trial |

> ⚠️ Password default sebaiknya diganti setelah deploy production.

---

## 5. Paket Berlangganan

### Konfigurasi Default

| Key | Label | Harga/bln | Video/bln | Max Durasi | Full AI |
|-----|-------|-----------|-----------|------------|---------|
| `unlimited` | Tim Mansion | Rp 0 | ∞ | 60 detik | ✓ |
| `trial` | Trial | Rp 0 | ∞ | 10 detik | ✗ |
| `basic` | Basic | Rp 25.000 | 5 | 60 detik | ✓ |
| `lite` | Lite | Rp 50.000 | 15 | 60 detik | ✓ |
| `pro` | Pro | Rp 75.000 | 25 | 60 detik | ✓ |

### Aturan Kuota
- Kuota dihitung **per download** (bukan per render)
- Reset otomatis setiap **bulan kalender baru** (`billing_month` berubah)
- `owner` dan `mansion_team` **tidak dihitung kuota** sama sekali
- Jika kuota habis, render ditolak dengan pesan upgrade paket

### Harga Editable
Harga, label, `videos_limit`, dan `max_duration` dapat diubah oleh **owner** melalui panel "⚙️ Pengaturan Paket" tanpa perlu deploy ulang — tersimpan di tabel `packages` SQLite.

---

## 6. Alur Autentikasi

```
Login (POST /api/login)
  → Verifikasi username + SHA-256(password)
  → Buat token urlsafe(32), expired 7 hari
  → Simpan ke tabel sessions
  → Return {token, user_info}

Setiap request ke endpoint protected:
  → Header: Authorization: Bearer <token>
  → Lookup token di DB, cek expires_at > NOW()
  → Return user info atau 401

Logout (POST /api/logout)
  → Hapus token dari tabel sessions

Auto-redirect:
  → login.html: jika sudah punya token valid → redirect ke /
  → index.html: jika token invalid/expired → redirect ke /login
```

---

## 7. Alur Render Video

### Overview 2-Pass System

```
Upload Clips/Photos
      ↓
[Pass 1] Assemble + Transitions
  - Smart cut / AI trim
  - Fit to 9:16 portrait
  - Crossfade / Fade to Black / Cut
  - Write: pass1_{sid}.mp4
      ↓
[Pass 2] Overlay + Effects
  - Color grading (per frame)
  - Caption overlay (rotating per interval)
  - CTA overlay (last N detik)
  - Watermark (Trial only, setiap frame)
  - BGM mix
  - Progress bar
  - Write: out_{sid}.mp4
      ↓
Download → increment video_used
```

### Smart Cut (Manual Mode)
- Sistem otomatis memilih segmen terbaik dari tiap klip berdasarkan motion score
- Total durasi segmen disesuaikan dengan `duration_target`

### AI Trim (Full AI Mode)
- AI menentukan `start` dan `end` tiap klip secara eksplisit
- Urutan klip mengikuti `segment_order` dari AI spec

### Caption Timing
- Video dibagi `n_caption` interval yang sama
- Setiap interval tampilkan caption berikutnya
- Caption pertama = hook (font lebih besar, warna Gold)
- CTA muncul di `total_duration - cta_dur` detik terakhir

### Output Format
- Codec: H.264 + AAC
- Format: MP4 (`yuv420p`)
- Aspect ratio: 9:16 portrait (vertikal)
- FPS: 24

---

## 8. Full AI Mode

### Yang Ditangani AI
| Parameter | Keterangan |
|-----------|------------|
| `segment_order` | Urutan index klip dari terbaik ke penutup |
| `trim` | Start & end tiap klip (4–6 detik per segmen) |
| `transition.type` | Crossfade / Fade to Black / Tanpa Transisi |
| `transition.duration` | 0.2–1.5 detik |
| `captions[]` | Teks, warna, dan alignment tiap caption |
| `font` | Pilihan font dari yang tersedia di sistem |
| `color_grade` | brightness / contrast / saturation / sharpness |

### Yang Selalu Manual (Di Luar Scope AI)
- BGM (file & volume)
- Resolusi output
- Durasi target
- CTA (nama & nomor WA)

### AI Spec Validation (`validate_and_fill`)
Setelah AI mengembalikan JSON, sistem memvalidasi dan mengisi default:
- `segment_order` — index invalid dibuang, index yang hilang ditambahkan di akhir
- `trim` — clamp ke range valid (≥0.3s dari awal, ≤durasi-0.3s dari akhir, min 2 detik)
- `transition.type` — jika tidak valid → default Crossfade
- `captions` — jumlah caption disesuaikan dengan `n_captions`, warna divalidasi
- `color_grade` — semua nilai di-clamp ke range aman

### Provider Priority
```
1. user_api_key (user input) → pakai key user (Gemini atau Anthropic)
2. GEMINI_API_KEY env var    → server free tier
3. Tidak ada key             → error 503
```

---

## 9. Kuota & Billing AI

### Kondisi Normal (Sehari-hari)
- **Cost owner = Rp 0**
- Server pakai `GEMINI_API_KEY` dari Google AI Studio (free tier)
- Free tier Gemini 2.0 Flash: **1.500 request/hari**, reset jam **07:00 WIB**
- Estimasi kapasitas: ~1.500 video Full AI per hari

### Kondisi Kuota Habis
- Sistem return HTTP `429` dengan pesan:
  > *"⚠️ Kuota server Gemini habis hari ini (reset jam 07:00 WIB). Silakan masukkan API Key sendiri."*
- User memasukkan key sendiri → langsung bisa render, **tidak tergantung kuota server**

### User Pakai Key Sendiri
| Provider | Daftar | Biaya |
|----------|--------|-------|
| Google Gemini | aistudio.google.com | Free (1.500 req/hari) |
| Anthropic Claude | console.anthropic.com | ~$0.001–0.003/request |

### Manual Mode
- Tidak memanggil API AI apapun
- Caption diproses lokal menggunakan NLTK / TextBlob / builtin
- **Nol kuota terpakai**

---

## 10. API Endpoints

### Auth
| Method | Path | Auth | Keterangan |
|--------|------|------|------------|
| POST | `/api/login` | ✗ | Login, return token |
| POST | `/api/logout` | ✓ | Invalidate token |
| GET | `/api/me` | ✓ | Info user + quota saat ini |
| PUT | `/api/user/password` | ✓ | Ganti password (verifikasi password lama) |

### Public
| Method | Path | Auth | Keterangan |
|--------|------|------|------------|
| GET | `/api/subscribe-info` | ✗ | Daftar paket + ketentuan + cara subscribe |
| GET | `/api/fonts` | ✗ | List font tersedia di sistem |

### Render Session
| Method | Path | Auth | Keterangan |
|--------|------|------|------------|
| POST | `/api/session` | ✓ | Buat sesi render baru, return `{sid}` |
| POST | `/api/upload/{sid}` | ✓ | Upload file (clip/photo/logo/bgm) |
| POST | `/api/ai-spec` | ✓ | Generate Full AI RenderSpec |
| POST | `/api/render/{sid}` | ✓ | Trigger background render |
| GET | `/api/status/{sid}` | ✓ | Poll status render |
| GET | `/api/download/{sid}` | ✓ | Download MP4 hasil render |
| DELETE | `/api/session/{sid}` | ✓ | Cleanup session & files |

### Admin (mansion_team + owner)
| Method | Path | Keterangan |
|--------|------|------------|
| GET | `/api/admin/users` | List semua user |
| POST | `/api/admin/users` | Tambah subscriber baru |
| PUT | `/api/admin/users/{id}` | Update package / is_active / email |
| PUT | `/api/admin/users/{id}/reset-password` | Reset password subscriber |

### Owner Only
| Method | Path | Keterangan |
|--------|------|------------|
| GET | `/api/admin/packages` | List semua paket dari DB |
| PUT | `/api/admin/packages/{key}` | Update harga/limit/durasi paket |
| GET | `/api/admin/settings` | Get site settings (ketentuan, WA, dll) |
| PUT | `/api/admin/settings` | Update site settings |

---

## 11. Frontend — Halaman & Fitur per Role

### login.html
- Bersih — hanya form login + tombol "Login as Trial"
- Tidak ada tabel paket (dipindah ke dalam app untuk Trial user)
- Auto-redirect ke `/` jika token masih valid

### index.html — Section visibility per role

| Section | Trial | Subscriber | Mansion tim | Admin/Owner |
|---------|-------|------------|-------------|-------------|
| Upload & Render | ✅ | ✅ | ✅ | ✅ |
| Full AI Mode | ❌ (locked) | ✅ | ✅ | ✅ |
| ⭐ Info Berlangganan | ✅ | ❌ | ❌ | ❌ |
| 🔑 Ganti Password | ❌ | ✅ | ❌ | ✅ |
| 👥 Manajemen Subscriber | ❌ | ❌ | ❌ | ✅ |
| ⚙️ Pengaturan Paket | ❌ | ❌ | ❌ | ✅ |
| 📖 Tutorial | ✅ | ✅ | ✅ | ✅ |

### Footer per role
| Role | Footer |
|------|--------|
| mansion_team / owner | `Mansion Video Generator · Full AI Mode powered by Claude` |
| Trial / Subscriber | `Video Generator · Full AI Mode powered by Claude` |

### App Title per role
| Role | Title |
|------|-------|
| mansion_team / owner | `Mansion Video Generator` |
| Trial / Subscriber | `Konten Video Generator` |

---

## 12. Alur Pendaftaran Subscriber

```
Calon subscriber
  → Hubungi via WA (+62 081703133252)
  → Sepakat paket (Basic/Lite/Pro)
  → Transfer pembayaran
  → Kirim bukti transfer ke WA

Admin/Owner (login sebagai Admin)
  → Buka panel "👥 Manajemen Subscriber"
  → Klik "+ Tambah Subscriber"
  → Isi: Username, Password, Email/WA, Paket
  → Klik "Daftarkan"
  → Berikan username & password ke subscriber

Subscriber aktif
  → Login dengan credentials yang diberikan
  → Bisa Ganti Password sendiri setelah login pertama
  → Kuota video mulai dihitung saat pertama download
```

### Manajemen Subscriber (Admin)
- **Toggle aktif/nonaktif** — blokir akses tanpa hapus data
- **Ganti paket** — upgrade/downgrade langsung dari tabel
- **Reset password** — jika subscriber lupa password
- Kuota reset otomatis tiap awal bulan baru

---

## 13. Watermark Trial

- Text: **"VieCut"**
- Posisi: pojok kanan bawah (88% dari atas)
- Style: putih semi-transparan (alpha 140/255) dengan dark stroke
- Diterapkan pada **setiap frame** video, termasuk saat CTA
- Hanya aktif jika `session.package == "trial"`
- Subscriber berbayar tidak mendapat watermark

---

## 14. Dashboard Owner

Dashboard ringkas tersedia di panel Admin/Owner — tanpa tabel tambahan, semua data dari schema yang sudah ada.

### Akses
- Hanya tampil untuk `user_type = "owner"`
- Endpoint: `GET /api/admin/dashboard`

### Data yang Ditampilkan

#### Summary Cards (bulan berjalan)
| Card | Sumber Data |
|------|-------------|
| Subscriber Aktif | `COUNT(users WHERE is_active=1)` |
| Video Bulan Ini | `SUM(videos_used WHERE billing_month=current)` |
| Subscriber Baru | `COUNT(users WHERE created_at LIKE 'YYYY-MM%')` |
| Nonaktif | `COUNT(users WHERE is_active=0)` |

#### Breakdown per Paket
- Nama paket, jumlah aktif/total, video dibuat bulan ini
- Exclude akun sistem (owner, mansion_team)

#### Top 10 User (Video Terbanyak Bulan Ini)
- Username, paket, jumlah video — sorted descending

### Keterbatasan Dashboard Ringkas
- Data **bulanan saja** — tidak ada drill-down harian/mingguan
- Tidak ada data per jam (peak hours)
- Tidak ada breakdown Full AI vs Manual mode

### Rencana Dashboard Lanjutan (Fase Berikutnya)
Jika traffic sudah ada dan perlu analitik lebih dalam, tambahkan tabel:
```sql
CREATE TABLE render_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    timestamp  TEXT DEFAULT (datetime('now')),
    duration   INTEGER,
    resolution TEXT,
    mode       TEXT,      -- 'full_ai' | 'manual'
    status     TEXT,      -- 'done' | 'error'
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```
Dengan tabel ini bisa dapat: harian, mingguan, peak hours, error rate, AI vs manual ratio.

---

## 15. Catatan Deploy

### Environment Variables yang Dibutuhkan
```env
GEMINI_API_KEY=<your_google_ai_studio_key>   # Wajib untuk Full AI server-side
```

### Cloud Run Deploy Command
```bash
uvicorn api:app --host 0.0.0.0 --port $PORT
```

### Dockerfile (perlu dibuat)
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD uvicorn api:app --host 0.0.0.0 --port $PORT
```

### Hal yang Perlu Diperhatikan Saat Deploy
- [ ] SQLite di Cloud Run = **ephemeral** (data hilang saat redeploy). Pertimbangkan mount persistent disk atau migrasi ke Cloud SQL
- [ ] Folder `uploads/` dan `output/` juga ephemeral — pertimbangkan Google Cloud Storage
- [ ] Ganti password default `Admin` dan `Mansion tim` setelah deploy pertama
- [ ] Set `GEMINI_API_KEY` sebagai environment variable di Cloud Run (bukan di code)
- [ ] Pertimbangkan `MAX_INSTANCES=1` di Cloud Run agar sesi render tidak conflict antar instance

### Keterbatasan Saat Ini
- Render session disimpan **in-memory** (`SESSIONS` dict) — tidak survive restart
- SQLite tidak cocok untuk multi-instance — aman untuk single instance Cloud Run
- File upload bersifat sementara dalam sesi — tidak ada persistent storage

---

## Changelog

| Tanggal | Keterangan |
|---------|------------|
| 25 Mar 2026 | ✅ Local test OK. Full AI + Manual render, Auth, Admin panel, Tutorial, Watermark Trial, Package editor, Subscribe info, Ganti password semua berfungsi. Belum deploy ke Cloud Run. |
| 25 Mar 2026 | ➕ Dashboard owner ringkas (summary cards + breakdown paket + top users). Data dari schema existing, tanpa tabel baru. |

---

*Dokumentasi ini dibuat otomatis berdasarkan state kode pada 25 Mar 2026.*
