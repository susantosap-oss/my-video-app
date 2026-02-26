"""
╔══════════════════════════════════════════════════════════════════════════════╗
║        Mansion Video Generator  —  Two-Pass Rendering                       ║
║        Versi Final Definitif · Linux / Streamlit Cloud Ready                ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Pass 1 : Clip mentah + Logo      →  /tmp/tmp_{SID}_pass1.mp4              ║
║  Pass 2 : Pass1 + Caption + CTA   →  output/out_{SID}.mp4                  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Repo GitHub:                                                                ║
║    /fonts   — file .ttf  (upload ke GitHub untuk font custom)               ║
║    /assets  — logo, backup font (opsional)                                  ║
║    /output  — video hasil render (dibuat otomatis saat runtime)             ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 1 — IMPORTS
# ═══════════════════════════════════════════════════════════════════════════════
import os, sys, gc, glob, time, uuid, random, shutil, subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

# ── NLTK: unduh data bahasa sebelum semua hal lain ───────────────────────────
import nltk
for _nltk_pkg in ["punkt", "punkt_tab", "averaged_perceptron_tagger", "stopwords"]:
    try:
        nltk.download(_nltk_pkg, quiet=True)
    except Exception:
        pass

# ── MoviePy ──────────────────────────────────────────────────────────────────
from moviepy import (
    VideoFileClip, AudioFileClip,
    VideoClip, concatenate_videoclips, CompositeAudioClip,
)
from moviepy.video.fx import Crop, FadeIn, FadeOut
from moviepy.audio.fx import AudioFadeIn, AudioFadeOut, MultiplyVolume

# ── [Linux] ImageMagick binary untuk MoviePy TextClip ────────────────────────
try:
    from moviepy.config import change_settings
    change_settings({"IMAGEMAGICK_BINARY": "/usr/bin/convert"})
except Exception:
    pass

# ── Streamlit (import setelah semua dependency) ───────────────────────────────
import streamlit as st


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 2 — STORAGE MANAGEMENT
# HARUS DIDEFINISIKAN DI SINI, SEBELUM DIPANGGIL DI BAWAH
# ═══════════════════════════════════════════════════════════════════════════════
TMP_DIR          = "/tmp"
_MAX_AGE_SECONDS = 30 * 60   # 30 menit


def _tmp(filename: str) -> str:
    """Kembalikan path absolut di /tmp untuk file temporary session."""
    return os.path.join(TMP_DIR, filename)


def _safe_remove(filepath: str) -> bool:
    """
    Hapus satu file dengan aman — tidak pernah raise Exception.
    Return True jika berhasil, False jika file terkunci / tidak ada.
    """
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            return True
    except (PermissionError, OSError, Exception):
        pass
    return False


def auto_cleanup(tmp_dir: str = TMP_DIR, output_dir: str = "output",
                 max_age: int = _MAX_AGE_SECONDS) -> dict:
    """
    Pindai /tmp dan output/, hapus file sampah yang sudah > max_age detik.

    Aturan keamanan:
      - File sesi AKTIF (umur < 30 menit) TIDAK tersentuh.
      - File yang terkunci saat render di-skip via PermissionError.
      - Tidak pernah crash — semua error ditangkap.

    Return: dict { scanned, deleted, skipped, freed_mb }
    """
    now     = time.time()
    scanned = deleted = skipped = 0
    freed_b = 0

    patterns = [
        os.path.join(tmp_dir,    "tmp_*"),
        os.path.join(output_dir, "out_*.mp4"),
    ]

    for pattern in patterns:
        for fp in glob.glob(pattern):
            scanned += 1
            try:
                age = now - os.path.getmtime(fp)
                if age > max_age:
                    sz = 0
                    try:
                        sz = os.path.getsize(fp)
                    except Exception:
                        pass
                    if _safe_remove(fp):
                        deleted += 1
                        freed_b += sz
                    else:
                        skipped += 1   # file terkunci render aktif
                else:
                    skipped += 1       # masih aktif, jangan hapus
            except FileNotFoundError:
                scanned -= 1           # dihapus proses lain secara bersamaan
            except Exception:
                skipped += 1

    gc.collect()
    return {
        "scanned" : scanned,
        "deleted" : deleted,
        "skipped" : skipped,
        "freed_mb": round(freed_b / 1_048_576, 2),
    }


def cleanup_session(sid: str, tmp_dir: str = TMP_DIR,
                    output_dir: str = "output") -> None:
    """
    Hapus SEMUA file milik session SID tertentu tanpa cek umur.
    Dipanggil saat user klik tombol Reset.
    """
    for pattern in [
        os.path.join(tmp_dir,    f"tmp_{sid}_*"),
        os.path.join(output_dir, f"out_{sid}*.mp4"),
    ]:
        for fp in glob.glob(pattern):
            _safe_remove(fp)
    gc.collect()


# ── Buat folder yang diperlukan ───────────────────────────────────────────────
Path("assets").mkdir(exist_ok=True)
Path("fonts").mkdir(exist_ok=True)
Path("output").mkdir(exist_ok=True)

# ── Jalankan cleanup SEBELUM set_page_config ─────────────────────────────────
# Ini memastikan server bersih setiap kali user baru buka/refresh halaman.
# File sesi aktif TIDAK tersentuh. File terkunci di-skip.
_STARTUP_CLEANUP = auto_cleanup()


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 3 — STREAMLIT PAGE CONFIG & MOBILE CSS
# ═══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Mansion Video Generator",
    page_icon="🎬",
    layout="centered",
)

st.markdown("""
<style>
/* Sidebar tidak terlalu sempit di tablet */
[data-testid="stSidebar"] { min-width: 280px; }

/* Responsive: kolom stack ke 100% width di layar < 640px */
@media (max-width: 640px) {
    div[data-testid="column"]      { width: 100% !important; flex: 1 1 100% !important; }
    .stButton > button              { width: 100%; }
    .main .block-container          { padding-left: .8rem; padding-right: .8rem; }
}

/* Video player tidak overflow di mobile */
video { max-width: 100%; height: auto; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 4 — NLP ENGINE DETECTION
# ═══════════════════════════════════════════════════════════════════════════════
_project_dir = os.path.dirname(os.path.abspath(__file__))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

NLP_ENGINE = "builtin"
try:
    from nltk.tokenize import sent_tokenize
    sent_tokenize("test.")
    NLP_ENGINE = "nltk"
except Exception:
    try:
        nltk.download("punkt",     quiet=True)
        nltk.download("punkt_tab", quiet=True)
        from nltk.tokenize import sent_tokenize
        sent_tokenize("test.")
        NLP_ENGINE = "nltk"
    except Exception:
        try:
            from textblob import TextBlob
            TextBlob("test").sentences
            NLP_ENGINE = "textblob"
        except Exception:
            NLP_ENGINE = "builtin"


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 5 — KONSTANTA VISUAL
# ═══════════════════════════════════════════════════════════════════════════════
CAPTION_COLORS = [
    (255, 215,   0),   # Gold      — selalu dipakai untuk HOOK
    (255, 255, 255),   # White
    (192, 192, 192),   # Silver
    (255, 223, 128),   # Champagne
    (210, 180, 140),   # Rose Gold
]
HOOK_COLOR      = (255, 215, 0)
STROKE_COLOR    = (0, 0, 0)
STROKE_W        = 2
VERT_LINE_W     = 6     # lebar garis vertikal Gold (px) untuk align Left/Right
VERT_LINE_GAP   = 10    # jarak antara garis dan teks
VERT_LINE_COLOR = (255, 215, 0)
CAPTION_Y       = 0.52  # posisi vertikal caption (fraksi dari tinggi frame)
CTA_Y           = 0.66  # posisi vertikal CTA
SAFE_BOTTOM     = 0.78  # batas bawah aman (safe zone TikTok/Reels)


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 6 — FONT HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
_FONT_LABELS = {
    "DejaVuSans-Bold.ttf"       : "DejaVu Sans Bold",
    "DejaVuSans.ttf"            : "DejaVu Sans",
    "LiberationSans-Bold.ttf"   : "Liberation Sans Bold",
    "LiberationSans.ttf"        : "Liberation Sans",
    "FreeSansBold.ttf"          : "Free Sans Bold",
    "FreeSans.ttf"              : "Free Sans",
    "NotoSans-Bold.ttf"         : "Noto Sans Bold",
    "NotoSans-Regular.ttf"      : "Noto Sans",
    "Roboto-Black.ttf"          : "Roboto Black",
    "RobotoCondensed-Bold.ttf"  : "Roboto Condensed Bold",
    "Ubuntu-Bold.ttf"           : "Ubuntu Bold",
    "Montserrat-Bold.ttf"       : "Montserrat Bold",
    "Oswald-Bold.ttf"           : "Oswald Bold",
    "PlayfairDisplay-Bold.ttf"  : "Playfair Display Bold",
}

_SYSTEM_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/roboto/Roboto-Black.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf",
]


def scan_fonts() -> list[dict]:
    """
    Kembalikan list font yang tersedia.
    Prioritas: fonts/ (repo GitHub) > assets/ > sistem Linux.
    """
    found, seen = [], set()

    def _add(path: str, label: str):
        p = os.path.normpath(path)
        if p not in seen and os.path.exists(p):
            seen.add(p)
            found.append({"label": label, "path": p})

    for folder, prefix in [("fonts", "📁 "), ("assets", "📁 ")]:
        for ext in ("*.ttf", "*.TTF", "*.otf", "*.OTF"):
            for fp in sorted(glob.glob(os.path.join(folder, ext))):
                fname = os.path.basename(fp)
                lbl   = _FONT_LABELS.get(
                    fname,
                    os.path.splitext(fname)[0].replace("_", " ").replace("-", " ").title()
                )
                _add(fp, f"{prefix}{lbl}")

    for fp in _SYSTEM_FONTS:
        fname = os.path.basename(fp)
        _add(fp, _FONT_LABELS.get(fname, os.path.splitext(fname)[0]))

    return found


def get_font(size: int, path: str = "") -> ImageFont.FreeTypeFont:
    """Muat font dari path. Fallback ke sistem Linux, lalu PIL default."""
    candidates = ([{"path": path}] if path and os.path.exists(path) else []) + scan_fonts()
    for c in candidates:
        try:
            return ImageFont.truetype(c["path"], max(8, size))
        except Exception:
            continue
    return ImageFont.load_default()


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 7 — NLP: PECAH DESKRIPSI → N CAPTION
# ═══════════════════════════════════════════════════════════════════════════════
def split_captions(text: str, n: int) -> list[str]:
    """
    Pecah deskripsi menjadi tepat n caption.
    Caption 1 = HOOK (huruf besar), sisanya = detail.
    Setiap caption dibatasi maksimal 8 kata.
    """
    import re
    text = text.strip()
    if not text:
        return [f"CAPTION {i+1}" for i in range(n)]

    sentences = []
    if NLP_ENGINE == "nltk":
        try:
            sentences = [s.strip() for s in sent_tokenize(text) if s.strip()]
        except Exception:
            pass
    if not sentences and NLP_ENGINE == "textblob":
        try:
            from textblob import TextBlob
            sentences = [str(s).strip() for s in TextBlob(text).sentences if str(s).strip()]
        except Exception:
            pass
    if not sentences:
        sentences = [s.strip()
                     for s in re.split(r'(?<=[.!?])\s+(?=[A-Z\d])', text)
                     if s.strip()]
    if not sentences:
        sentences = [text]

    sentences = [s.rstrip(".!?").strip() for s in sentences]
    hook = sentences[0].upper()
    rest = sentences[1:]

    if n == 1:
        return [hook]

    captions = [hook]
    n_rest   = n - 1
    if not rest:
        captions += [""] * n_rest
    elif len(rest) <= n_rest:
        captions += [s.upper() for s in rest]
        while len(captions) < n:
            captions.append("")
    else:
        bucket = len(rest) / n_rest
        for i in range(n_rest):
            start = int(i * bucket)
            end   = max(int((i + 1) * bucket), start + 1)
            captions.append(" ".join(rest[start:end]).upper())

    MAX_WORDS = 8
    result = []
    for cap in captions[:n]:
        words = cap.split()
        result.append((" ".join(words[:MAX_WORDS]) + "…") if len(words) > MAX_WORDS else cap)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 8 — RENDER OVERLAY (Caption · CTA · Logo · Progress Bar)
# ═══════════════════════════════════════════════════════════════════════════════
def _compute_layout(out_w: int) -> tuple[int, int, int, int]:
    """Hitung ukuran font dan padding berdasarkan lebar output."""
    return (
        max(18, int(out_w * 0.065)),   # font_size  (caption detail)
        max(22, int(out_w * 0.080)),   # hook_size  (caption 1/HOOK)
        max(8,  int(out_w * 0.045)),   # pad_x
        max(4,  int(out_w * 0.018)),   # pad_y
    )


def _wrap_text(text: str, font, max_w: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """Bungkus teks ke beberapa baris agar tidak melebihi max_w piksel."""
    words = text.split()
    if not words:
        return [""]
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def _fit_wrap(text: str, max_w: int, font_path: str,
              size: int, max_lines: int = 4) -> tuple:
    """Kurangi ukuran font sampai teks muat dalam max_lines baris."""
    dummy = Image.new("RGBA", (1, 1))
    draw  = ImageDraw.Draw(dummy)
    s     = max(8, size)
    while s >= 8:
        f     = get_font(s, font_path)
        lines = _wrap_text(text, f, max_w, draw)
        if len(lines) <= max_lines:
            return f, lines
        s -= 1
    f = get_font(8, font_path)
    return f, _wrap_text(text, f, max_w, draw)


def _fit_single(text: str, max_w: int, font_path: str, size: int) -> tuple:
    """Kurangi ukuran font sampai teks muat dalam satu baris."""
    dummy = Image.new("RGBA", (1, 1))
    draw  = ImageDraw.Draw(dummy)
    s, prev = max(8, size), None
    while s >= 8:
        f  = get_font(s, font_path)
        tw = draw.textbbox((0, 0), text, font=f)[2]
        if tw <= max_w:
            return f, s
        if prev is not None and tw >= prev:
            break
        prev = tw
        s   -= 2
    return get_font(8, font_path), 8


def _stroke_text(draw: ImageDraw.ImageDraw, x: int, y: int,
                 text: str, font, rgb: tuple) -> None:
    """Gambar teks dengan outline hitam agar terbaca di atas video apapun."""
    for dx in range(-STROKE_W, STROKE_W + 1):
        for dy in range(-STROKE_W, STROKE_W + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((x + dx, y + dy), text, font=font,
                      fill=(*STROKE_COLOR, 255))
    draw.text((x, y), text, font=font, fill=(*rgb, 255))


def _paste_logo(canvas: Image.Image, out_w: int, out_h: int,
                logo_pil) -> None:
    """Tempel logo di tengah atas frame (safe zone). Diam-diam jika gagal."""
    if logo_pil is None:
        return
    try:
        lw = max(20, int(out_w * 0.25))
        lh = max(1,  int(logo_pil.height * lw / logo_pil.width))
        lr = logo_pil.resize((lw, lh), Image.LANCZOS).convert("RGBA")
        lx = (out_w - lw) // 2
        ly = min(max(4, int(out_h * 0.03)), out_h - lh - 4)
        canvas.paste(lr, (lx, ly), lr)
    except Exception:
        pass


def render_caption(
    text: str, out_w: int, out_h: int,
    size: int, pad_x: int, pad_y: int,
    color: tuple = (255, 255, 255),
    font_path: str = "",
    logo_pil=None,
    max_lines: int = 4,
    align: str = "Center",
) -> np.ndarray:
    """
    Render caption sebagai RGBA overlay (numpy float32).

    align:
      "Center"  → teks di tengah, tanpa garis vertikal.
      "Left"    → teks rata kiri + garis vertikal Gold di sisi kiri.
      "Right"   → teks rata kanan + garis vertikal Gold di sisi kanan.
    """
    canvas = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)

    if text.strip():
        # Kurangi lebar usable jika ada garis vertikal
        lm     = (VERT_LINE_W + VERT_LINE_GAP) if align != "Center" else 0
        box_w  = max(1, out_w - pad_x * 2)
        usable = max(1, box_w - lm - 8)

        font, lines = _fit_wrap(text, usable, font_path, size, max_lines)
        lh   = max(1, draw.textbbox((0, 0), "Ag", font=font)[3])
        lgap = max(2, int(lh * 0.10))
        th   = lh * len(lines) + lgap * (len(lines) - 1)

        # Posisi vertikal: jaga agar tidak keluar safe zone
        safe_px = int(out_h * SAFE_BOTTOM)
        ty      = int(out_h * CAPTION_Y)
        if ty + th > safe_px:
            ty = max(0, safe_px - th - pad_y)

        # Gambar garis vertikal Gold (hanya untuk Left / Right)
        text_x_anchor = text_x_end = None
        if align == "Left":
            gx0 = pad_x
            gx1 = pad_x + VERT_LINE_W
            draw.rectangle([gx0, ty, gx1, ty + th],
                           fill=(*VERT_LINE_COLOR, 255))
            text_x_anchor = gx1 + VERT_LINE_GAP

        elif align == "Right":
            gx1 = out_w - pad_x
            gx0 = gx1 - VERT_LINE_W
            draw.rectangle([gx0, ty, gx1, ty + th],
                           fill=(*VERT_LINE_COLOR, 255))
            text_x_end = gx0 - VERT_LINE_GAP

        # Gambar setiap baris teks
        cy = ty
        for line in lines:
            if not line.strip():
                cy += lh + lgap
                continue
            lw = draw.textbbox((0, 0), line, font=font)[2]
            if align == "Left":
                tx = text_x_anchor
            elif align == "Right":
                tx = max(pad_x, text_x_end - lw)
            else:
                tx = max(pad_x, pad_x + (box_w - lw) // 2)
            _stroke_text(draw, tx, cy, line, font, color)
            cy += lh + lgap

    _paste_logo(canvas, out_w, out_h, logo_pil)
    return np.array(canvas).astype(np.float32)


def render_cta(
    nama: str, wa: str,
    out_w: int, out_h: int,
    size: int, pad_x: int, pad_y: int,
    font_path: str = "",
    logo_pil=None,
    label: str = "HUBUNGI :",
) -> np.ndarray:
    """
    Render CTA (nama agen + WA) sebagai RGBA overlay.
    Diletakkan di zona tengah-bawah dengan garis separator Gold di atasnya.
    """
    canvas = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)

    items = []
    if label: items.append((label.upper(), (255, 255, 255)))
    if nama:  items.append((nama.upper(),  (255, 215, 0)))
    if wa:    items.append((f"WA: {wa}",   (255, 255, 255)))

    if items:
        box_w  = max(1, out_w - pad_x * 2)
        usable = max(1, box_w - pad_x)

        rendered = []
        for i, (txt, clr) in enumerate(items):
            # Label lebih kecil, nama agen lebih besar
            sz = max(8, int(size * (0.80 if i == 1 else 0.60)))
            f, _ = _fit_single(txt, usable, font_path, sz)
            bb   = draw.textbbox((0, 0), txt, font=f)
            rendered.append((txt, clr, f,
                             max(1, bb[2] - bb[0]),
                             max(1, bb[3] - bb[1])))

        lgap    = max(4, pad_y)
        tot_h   = sum(r[4] for r in rendered) + lgap * (len(rendered) - 1)
        gold_h  = max(2, int(out_h * 0.003))
        block_h = tot_h + gold_h + pad_y * 3

        safe_px = int(out_h * SAFE_BOTTOM)
        y_top   = int(out_h * CTA_Y)
        if y_top + block_h > safe_px:
            y_top = max(0, safe_px - block_h)

        # Garis separator Gold
        draw.rectangle([pad_x, y_top, pad_x + box_w, y_top + gold_h],
                       fill=(255, 215, 0, 255))
        cy = y_top + gold_h + pad_y

        for txt, clr, f, tw, th in rendered:
            tx = pad_x + (box_w - tw) // 2
            _stroke_text(draw, tx, cy, txt, f, clr)
            cy += th + lgap

    _paste_logo(canvas, out_w, out_h, logo_pil)
    return np.array(canvas).astype(np.float32)


def blend_overlay(frame: np.ndarray, overlay: np.ndarray) -> np.ndarray:
    """Alpha-composite overlay RGBA (float32) ke atas frame RGB (uint8)."""
    if frame.shape[:2] != overlay.shape[:2]:
        return frame
    alpha = overlay[:, :, 3:] / 255.0
    return np.clip(
        frame.astype(np.float32) * (1.0 - alpha) + overlay[:, :, :3] * alpha,
        0, 255,
    ).astype(np.uint8)


def grade_frame(frame: np.ndarray,
                br: float, co: float, sa: float, sh: float) -> np.ndarray:
    """Terapkan brightness, contrast, saturation, sharpness ke satu frame."""
    img = Image.fromarray(frame.astype(np.uint8))
    img = ImageEnhance.Brightness(img).enhance(br)
    img = ImageEnhance.Contrast(img).enhance(co)
    img = ImageEnhance.Color(img).enhance(sa)
    img = ImageEnhance.Sharpness(img).enhance(sh)
    return np.array(img)


def draw_progress_bar(frame: np.ndarray, t: float, total: float,
                      out_w: int, out_h: int, bar_h: int = 4) -> np.ndarray:
    """
    Gambar progress bar putih tipis di bagian paling bawah frame.
    Latar belakang bar diredupkan 70% agar bar terlihat jelas.
    """
    if total <= 0:
        return frame
    result = frame.copy()
    bar_w  = int(out_w * min(max(t / total, 0.0), 1.0))
    y0     = max(0, out_h - bar_h)
    result[y0:out_h, :, :]      = (result[y0:out_h, :, :] * 0.3).astype(np.uint8)
    if bar_w > 0:
        result[y0:out_h, :bar_w, :] = 255
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 9 — VIDEO PROCESSING HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def _blur_clip(clip, radius: int = 25):
    """Terapkan Gaussian blur ke setiap frame clip."""
    def _blur(f):
        return np.array(Image.fromarray(f).filter(ImageFilter.GaussianBlur(radius)))
    return clip.image_transform(_blur)


def fit_to_916(clip, out_w: int, out_h: int):
    """
    Resize clip ke rasio 9:16 (Portrait).
    Jika clip landscape/square: foreground di tengah, background di-blur.
    """
    try:
        cw, ch = clip.size
        sr, dr = cw / ch, out_w / out_h

        if abs(sr - dr) < 0.05:
            return clip.resized((out_w, out_h))

        # Latar belakang: blur clip yang diperlebar memenuhi tinggi
        scale_h  = out_h / ch
        bg_w_raw = max(out_w, int(cw * scale_h))
        bg       = _blur_clip(clip.resized((bg_w_raw, out_h)), radius=25)
        if bg_w_raw > out_w:
            x1 = (bg_w_raw - out_w) // 2
            bg = bg.with_effects([Crop(x1=x1, x2=x1 + out_w, y1=0, y2=out_h)])

        # Foreground: clip asli, diletakkan di tengah vertikal
        fg_h  = max(1, int(out_w / sr))
        fg    = clip.resized((out_w, fg_h))
        fg_y0 = (out_h - fg_h) // 2
        fg_y1 = fg_y0 + fg_h

        def _compose(t):
            res              = bg.get_frame(t).copy()
            res[fg_y0:fg_y1] = fg.get_frame(t)
            return res

        out = VideoClip(_compose, duration=clip.duration).with_fps(clip.fps or 24)
        if clip.audio is not None:
            out = out.with_audio(clip.audio)
        return out

    except Exception as e:
        st.warning(f"⚠️ fit_to_916 fallback: {e}")
        return clip.resized((out_w, out_h))


def crossfade_concat(clips: list, fade_d: float) -> VideoClip:
    """
    Gabungkan clips[] dengan transisi crossfade halus.
    Guard: raise ValueError jika clips kosong.
    """
    if not clips:
        raise ValueError("crossfade_concat: daftar klip tidak boleh kosong")
    if len(clips) == 1:
        return clips[0]

    min_dur = min(c.duration for c in clips)
    fd      = min(fade_d, min_dur * 0.4)

    # Hitung start time setiap clip (overlap sebesar fd detik)
    starts = [0.0]
    for c in clips[:-1]:
        starts.append(starts[-1] + c.duration - fd)
    total_dur = starts[-1] + clips[-1].duration

    def _frame(t):
        result = None
        for i, clip in enumerate(clips):
            cs, ce = starts[i], starts[i] + clip.duration
            if t < cs or t >= ce:
                continue
            lt    = min(t - cs, clip.duration - 1e-4)
            frame = clip.get_frame(lt)
            if result is None:
                result = frame.astype(np.float32)
            else:
                alpha  = min(1.0, (t - cs) / max(fd, 1e-6))
                result = result * (1.0 - alpha) + frame.astype(np.float32) * alpha
        if result is None:
            result = clips[-1].get_frame(clips[-1].duration - 1e-4).astype(np.float32)
        return np.clip(result, 0, 255).astype(np.uint8)

    out   = VideoClip(_frame, duration=total_dur)
    audio = [c.audio.with_start(starts[i])
             for i, c in enumerate(clips) if c.audio is not None]
    if audio:
        out = out.with_audio(CompositeAudioClip(audio))
    return out.with_fps(clips[0].fps or 24)


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 10 — SMART CLIP CUTTER
# ═══════════════════════════════════════════════════════════════════════════════
def smart_cut_clips(video_clips: list, target_dur: int,
                    min_seg: float = 4.0, max_seg: float = 6.0) -> list:
    """
    Potong setiap VideoFileClip menjadi segmen 4–6 detik, dikocok acak,
    dipilih sampai total durasi ≥ target_dur.

    Guard:
      - Video < 2 detik  → warning + skip (bukan crash)
      - Video 2–4 detik  → ambil utuh sebagai 1 segmen
      - Semua video < 2 detik → raise ValueError dengan pesan jelas
    """
    pool = []
    for src_idx, vc in enumerate(video_clips):
        dur = vc.duration
        if dur < 2.0:
            st.warning(
                f"⚠️ Video #{src_idx + 1} terlalu pendek ({dur:.1f}s < 2s) — dilewati."
            )
            continue
        if dur < min_seg:
            # Ambil seluruh clip utuh
            pool.append({
                "src_idx" : src_idx,
                "start"   : 0.0,
                "end"     : round(dur, 2),
                "duration": round(dur, 2),
            })
            continue
        # Potong menjadi segmen min_seg–max_seg detik
        t = 0.0
        while t < dur - 1.0:
            end    = min(t + max_seg, dur)
            actual = round(end - t, 2)
            if actual < min_seg:
                break
            pool.append({
                "src_idx" : src_idx,
                "start"   : round(t, 2),
                "end"     : round(end, 2),
                "duration": actual,
            })
            t += max_seg

    if not pool:
        raise ValueError(
            "Semua video terlalu pendek (< 2 detik). "
            "Upload video dengan durasi minimal 2–4 detik."
        )

    random.shuffle(pool)
    selected, total = [], 0.0
    for s in pool:
        if total >= target_dur:
            break
        selected.append(s)
        total += s["duration"]
    for i, s in enumerate(selected):
        s["seg_idx"] = i
    return selected


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 11 — KEN BURNS PHOTO SLIDESHOW
# ═══════════════════════════════════════════════════════════════════════════════
def photo_to_clip(img_path: str, duration: float,
                  out_w: int, out_h: int,
                  zoom_end: float = 1.15) -> VideoClip:
    """
    Buat VideoClip dari satu foto dengan Ken Burns Effect (slow zoom-in).

    Mekanisme:
      1. Render base_frame pada ukuran yang lebih besar (out_w * zoom_end).
         Foto landscape di-fit dengan foreground center + background blur.
      2. Setiap frame(t): crop area yang makin mengecil seiring waktu.
         t=0 → crop = base (ukuran terbesar, skala 1.0)
         t=dur → crop = output (ukuran target, skala zoom_end)
         Efek visual: objek terlihat perlahan membesar / zoom-in.
    """
    MAX_SCALE = zoom_end
    base_w    = int(out_w * MAX_SCALE)
    base_h    = int(out_h * MAX_SCALE)

    # ── Render base frame pada ukuran diperbesar ──────────────────────────────
    img      = Image.open(img_path).convert("RGB")
    iw, ih   = img.size
    sr, dr   = iw / ih, base_w / base_h

    if abs(sr - dr) < 0.05:
        base_frame = np.array(img.resize((base_w, base_h), Image.LANCZOS))
    else:
        # Buat latar belakang blur
        scale_h  = base_h / ih
        bg_w_raw = max(base_w, int(iw * scale_h))
        bg       = img.resize((bg_w_raw, base_h), Image.LANCZOS)
        bg       = bg.filter(ImageFilter.GaussianBlur(radius=25))
        if bg_w_raw > base_w:
            x1 = (bg_w_raw - base_w) // 2
            bg = bg.crop((x1, 0, x1 + base_w, base_h))
        # Tempel foreground di tengah vertikal
        fg_h   = max(1, int(base_w / sr))
        fg_img = img.resize((base_w, fg_h), Image.LANCZOS)
        fg_y0  = (base_h - fg_h) // 2
        canvas = bg.copy()
        canvas.paste(fg_img, (0, fg_y0))
        base_frame = np.array(canvas)

    base_frame = base_frame.astype(np.uint8)
    _bw, _bh   = base_w, base_h
    _ow, _oh   = out_w, out_h

    def make_frame(t: float) -> np.ndarray:
        progress = min(t / max(duration, 1e-6), 1.0)
        # t=0 → crop seluruh base; t=dur → crop hanya area output
        crop_w = max(_ow, int(_bw - (_bw - _ow) * progress))
        crop_h = max(_oh, int(_bh - (_bh - _oh) * progress))
        x1 = max(0, (_bw - crop_w) // 2)
        y1 = max(0, (_bh - crop_h) // 2)
        cropped = base_frame[y1:y1 + crop_h, x1:x1 + crop_w]
        return np.array(
            Image.fromarray(cropped).resize((_ow, _oh), Image.BILINEAR)
        ).astype(np.uint8)

    return VideoClip(make_frame, duration=duration).with_fps(24)


def build_photo_slideshow(photo_paths: list, target_dur: int,
                           out_w: int, out_h: int,
                           fade_dur: float = 0.5,
                           zoom_end: float = 1.15) -> VideoClip:
    """
    Bangun slideshow dari foto dengan Ken Burns Effect + crossfade antar foto.
    Guard: raise ValueError jika photo_paths kosong.
    """
    if not photo_paths:
        raise ValueError("build_photo_slideshow: daftar foto tidak boleh kosong")

    n      = len(photo_paths)
    per_ph = max(5.0, min(8.0, target_dur / n))

    clips = [photo_to_clip(p, per_ph, out_w, out_h, zoom_end=zoom_end)
             for p in photo_paths]

    faded = []
    for i, c in enumerate(clips):
        fx = []
        if i > 0:     fx.append(FadeIn(fade_dur))
        if i < n - 1: fx.append(FadeOut(fade_dur))
        faded.append(c.with_effects(fx) if fx else c)

    return concatenate_videoclips(faded, method="chain")


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 12 — PASS 2: OVERLAY + AUDIO + GRADING (Bulletproof Pipeline)
# ═══════════════════════════════════════════════════════════════════════════════
def run_pass2(
    pass1_path: str,
    out_path:   str,
    deskripsi:  str,
    n_caption:  int,
    detail_colors: list,
    cta_nama:   str,
    cta_wa:     str,
    cta_dur:    float,
    cta_label:  str,
    do_grade:   bool,
    brightness: float,
    contrast:   float,
    saturation: float,
    sharpness:  float,
    bgm_file,
    bgm_volume: float,
    orig_vol:   float,
    OUT_W:      int,
    OUT_H:      int,
    logo_pil,
    font_path:  str,
    caption_align: str = "Center",
) -> tuple[bool, list, str]:
    """
    Pass 2: baca Pass 1 → overlay caption + CTA + progress bar → tulis output.

    Return: (success: bool, captions: list, error_msg: str)

    BULLETPROOF:
      - open_clips[] mencatat SEMUA resource terbuka.
      - finally: loop tutup semua + gc.collect() (WAJIB, harga mati).
      - bgm_file.seek(0) sebelum read → cegah 0-bytes saat Re-render.
    """
    open_clips  = []           # ← semua resource dicatat di sini
    bgm_tmp     = _tmp(f"tmp_{SID}_bgm.mp3")
    bgm_created = False

    try:
        # ── Info NLP ────────────────────────────────────────────────────────────
        _nlp = {"nltk": "🟢 NLTK", "textblob": "🟡 TextBlob", "builtin": "🔵 Regex"}
        st.write(
            f"🧠 NLP: **{_nlp.get(NLP_ENGINE, NLP_ENGINE)}** "
            f"| {n_caption} caption · align **{caption_align}**"
        )

        # ── Pecah deskripsi → caption ────────────────────────────────────────
        captions = split_captions(deskripsi, n_caption)
        with st.expander("📋 Preview Caption", expanded=True):
            for i, cap in enumerate(captions):
                tag = "🪝 HOOK" if i == 0 else f"📌 Detail {i}"
                st.markdown(f"**Caption {i+1}** `[{tag}]`")
                st.info(cap if cap else "_(kosong)_")
            if cta_nama.strip() or cta_wa.strip():
                st.markdown("**CTA (detik terakhir)**")
                st.success(f"📞 {cta_nama}  |  WA: {cta_wa}")

        # ── Layout & pre-render overlay ──────────────────────────────────────
        font_size, hook_size, pad_x, pad_y = _compute_layout(OUT_W)
        bar_h    = max(3, int(OUT_H * 0.006))
        all_clr  = [HOOK_COLOR] + list(detail_colors)

        overlays = []
        for idx, cap in enumerate(captions):
            clr = all_clr[idx % len(all_clr)]
            sz  = hook_size if idx == 0 else font_size
            overlays.append(render_caption(
                cap, OUT_W, OUT_H, sz, pad_x, pad_y,
                color=clr, font_path=font_path,
                logo_pil=None,        # ← LOGO TIDAK di sini: sudah di-bake Pass 1
                align=caption_align,
            ))

        cta_ov = None
        if cta_nama.strip() or cta_wa.strip():
            cta_ov = render_cta(
                cta_nama.strip(), cta_wa.strip(),
                OUT_W, OUT_H, font_size, pad_x, pad_y,
                font_path=font_path,
                logo_pil=None,        # ← LOGO TIDAK di sini: sudah di-bake Pass 1
                label=cta_label.strip(),
            )

        # ── Baca Pass 1 ──────────────────────────────────────────────────────
        st.write("📂 Membaca Pass 1...")
        p1 = VideoFileClip(pass1_path)
        open_clips.append(p1)          # ← catat

        total_dur = p1.duration
        n_cap     = len(captions)
        interval  = total_dur / max(n_cap, 1)
        cta_start = max(0.0, total_dur - cta_dur)
        audio_src = p1.audio

        sched = " | ".join(
            [f"{i+1}. {i*interval:.0f}s–{(i+1)*interval:.0f}s" for i in range(n_cap)]
        )
        st.write(f"🕐 {sched}")

        # ── BGM (opsional) ───────────────────────────────────────────────────
        if bgm_file:
            try:
                bgm_file.seek(0)       # ← WAJIB: reset pointer st.file_uploader
                with open(bgm_tmp, "wb") as fh:
                    fh.write(bgm_file.read())
                bgm_created = True

                bgm_raw = AudioFileClip(bgm_tmp)
                open_clips.append(bgm_raw)   # ← catat untuk ditutup di finally

                if bgm_raw.duration > total_dur:
                    bgm_raw = bgm_raw.subclipped(0, total_dur)
                fi_dur    = min(3.0, bgm_raw.duration * 0.15)   # Fade In 3 dtk
                fo_dur    = min(3.0, bgm_raw.duration * 0.30)   # Fade Out 3 dtk
                bgm_audio = bgm_raw.with_effects([
                    AudioFadeIn(fi_dur),
                    AudioFadeOut(fo_dur),
                    MultiplyVolume(bgm_volume),
                ])
                if audio_src is not None:
                    audio_src = audio_src.with_effects([MultiplyVolume(orig_vol)])
                mixed = [a for a in [audio_src, bgm_audio] if a is not None]
                if mixed:
                    audio_src = CompositeAudioClip(mixed)
                st.write(f"  ✅ BGM {bgm_raw.duration:.1f}s · fade-in {fi_dur:.1f}s · fade-out {fo_dur:.1f}s")

            except Exception as e:
                st.warning(f"⚠️ BGM gagal dimuat: {e}")

        # ── Freeze closure variables untuk frame processor ───────────────────
        _do  = bool(do_grade)
        _br  = float(brightness) if _do else 1.0
        _co  = float(contrast)   if _do else 1.0
        _sa  = float(saturation) if _do else 1.0
        _sh  = float(sharpness)  if _do else 1.0
        _ovs = list(overlays)
        _cta = cta_ov
        _cs  = float(cta_start)
        _iv  = float(interval)
        _nc  = int(n_cap)
        _td  = float(total_dur)
        _bh  = int(bar_h)
        _ow  = int(OUT_W)
        _oh  = int(OUT_H)

        def pass2_proc(get_frame, t):
            frame = get_frame(t)
            if _do:
                frame = grade_frame(frame, _br, _co, _sa, _sh)
            if _cta is not None and t >= _cs:
                frame = blend_overlay(frame, _cta)
            else:
                idx   = min(int(t / _iv), _nc - 1)
                frame = blend_overlay(frame, _ovs[idx])
            return draw_progress_bar(frame, t, _td, _ow, _oh, _bh)

        # ── Render & tulis video final ───────────────────────────────────────
        st.write("🎬 Render Pass 2...")
        final = p1.transform(pass2_proc)
        if audio_src is not None:
            final = final.with_audio(audio_src)

        final.write_videofile(
            out_path,
            codec="libx264",
            audio_codec="aac",
            fps=24,
            ffmpeg_params=["-pix_fmt", "yuv420p"],
            logger=None,
        )
        try:
            final.close()              # tutup segera setelah tulis selesai
        except Exception:
            pass

        return True, captions, ""

    except Exception as e:
        return False, [], str(e)

    finally:
        # ── WAJIB: tutup SEMUA resource — cegah memory leak & OOM ────────────
        for oc in open_clips:
            try:
                oc.close()
            except Exception:
                pass
        if bgm_created:
            _safe_remove(bgm_tmp)
        gc.collect()


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 13 — HEADER, SESSION, TOAST
# ═══════════════════════════════════════════════════════════════════════════════
st.title("🎬 Mansion Video Generator")
st.caption("Aplikasi membuat video Konten Sosial Media dalam Format Portrait · 9:16")

# Toast notifikasi cleanup jika ada file yang berhasil dihapus
if _STARTUP_CLEANUP["deleted"] > 0:
    st.toast(
        f"🧹 Auto-cleanup: {_STARTUP_CLEANUP['deleted']} file lama dihapus "
        f"· {_STARTUP_CLEANUP['freed_mb']} MB dibebaskan",
        icon="✅",
    )

# Session ID unik per tab browser
if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex[:8]
SID = st.session_state.session_id
st.caption(f"🔑 Session: `{SID}`")


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 14 — SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════
with st.sidebar:

    # ── Deskripsi ─────────────────────────────────────────────────────────────
    st.header("📝 Deskripsi Properti")
    deskripsi = st.text_area(
        "Tuliskan deskripsi lengkap properti",
        value=(
            "Rumah 1 Lantai Citraland Surabaya. "
            "LT 150m2 KT 3. "
            "Desain Arsitektur Modern dengan Rooftop. "
            "Lokasi strategis dekat pusat bisnis dan sekolah internasional. "
            "Harga Rp 5.5 M, nego."
        ),
        height=160,
    )
    n_caption = st.slider("Jumlah Caption", 1, 5, 3,
                          help="Deskripsi dipecah otomatis menjadi N caption")

    # ── CTA ───────────────────────────────────────────────────────────────────
    st.header("📞 CTA (Caption Akhir)")
    cta_label = st.text_input("Teks Label",      "Hubungi :")
    cta_nama  = st.text_input("Nama Agen",       "Nama Agen")
    cta_wa    = st.text_input("Nomor WhatsApp",  "0812-xxxx-xxxx")
    cta_dur   = st.slider("Durasi CTA (detik terakhir)", 2, 8, 4)

    # ── Warna Caption ─────────────────────────────────────────────────────────
    st.header("🎨 Warna Caption 2–5")
    _color_names  = ["Gold", "White", "Silver", "Champagne", "Rose Gold"]
    detail_colors = []
    for i in range(1, 5):
        c = st.selectbox(f"Caption {i+1}", options=_color_names,
                         index=i % len(_color_names), key=f"clr_{i}")
        detail_colors.append(CAPTION_COLORS[_color_names.index(c)])

    # ── Color Grading ─────────────────────────────────────────────────────────
    st.header("✨ Color Grading")
    do_grade   = st.toggle("Aktifkan", value=False)
    brightness = st.slider("Brightness",  0.7, 1.5, 1.05, 0.05)
    contrast   = st.slider("Contrast",    0.7, 1.5, 1.10, 0.05)
    saturation = st.slider("Saturation",  0.7, 1.5, 1.05, 0.05)
    sharpness  = st.slider("Sharpness",   0.7, 2.0, 1.10, 0.05)

    # ── Font & Caption Alignment ──────────────────────────────────────────────
    st.header("🔤 Font & Alignment")
    _avail_fonts = scan_fonts()
    if _avail_fonts:
        _font_labels = [f["label"] for f in _avail_fonts]
        _font_paths  = [f["path"]  for f in _avail_fonts]
        _font_choice = st.selectbox(
            "Font",
            options=range(len(_font_labels)),
            format_func=lambda i: _font_labels[i],
            index=0,
        )
        selected_font_path = _font_paths[_font_choice]
        st.caption(f"`{os.path.basename(selected_font_path)}`")
    else:
        selected_font_path = ""
        st.warning("Tidak ada font. Upload file `.ttf` ke folder `fonts/` di GitHub.")

    caption_align = st.selectbox(
        "Caption Align",
        options=["Center", "Left", "Right"],
        index=0,
        help=(
            "Center : teks di tengah (tanpa garis).\n"
            "Left   : teks rata kiri + garis Gold di kiri.\n"
            "Right  : teks rata kanan + garis Gold di kanan."
        ),
    )
    st.caption("💡 Upload `.ttf` ke folder `fonts/` di GitHub untuk font custom.")

    # ── Logo & BGM ───────────────────────────────────────────────────────────
    st.header("🖼️ Logo")
    logo_file = st.file_uploader("Upload Logo (PNG)", type=["png"])

    st.header("🎵 Background Music")
    bgm_file   = st.file_uploader("Upload MP3/WAV", type=["mp3", "wav"])
    bgm_volume = st.slider("Volume BGM",              0.1, 1.0, 0.50, 0.05)
    orig_vol   = st.slider("Volume Video Asli (+ BGM)", 0.0, 1.0, 0.80, 0.05)

    # ── Render Settings ───────────────────────────────────────────────────────
    st.header("⏱️ Durasi Target")
    durasi_target = st.slider("Detik", 15, 60, 30)

    st.header("🎞️ Resolusi Output")
    resolusi = st.radio("Resolusi", [
        "360p  (202×360)",
        "720p  (720×1280) Best",
        "1080p (1080×1920)",
        "Original",
    ], index=1)

    st.header("🎬 Transisi Antar Klip")
    jenis_transisi = st.radio("Jenis",
        ["Crossfade", "Fade to Black", "Tanpa Transisi"], index=0)
    fade_dur = st.slider("Durasi Transisi (detik)", 0.2, 1.5, 0.4, 0.1)

    # ── Storage Widget ────────────────────────────────────────────────────────
    st.divider()
    st.caption("🗄️ **Storage Server**")
    _sc = _STARTUP_CLEANUP
    if _sc["deleted"] > 0:
        st.caption(
            f"✅ Auto-cleanup: **{_sc['deleted']}** file dihapus "
            f"· **{_sc['freed_mb']} MB** dibebaskan"
        )
    else:
        st.caption(f"✨ Bersih · {_sc['scanned']} file diperiksa")

    if st.button("🔍 Bersihkan Sekarang", use_container_width=True,
                 help="Hapus file temp/output sesi lama (> 30 menit) secara manual"):
        _res = auto_cleanup()
        if _res["deleted"] > 0:
            st.success(f"✅ {_res['deleted']} file dihapus · {_res['freed_mb']} MB dibebaskan")
        else:
            st.info(f"✨ Bersih · {_res['scanned']} file diperiksa")
        gc.collect()


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 15 — TAB INPUT: VIDEO / PHOTO SLIDE
# ═══════════════════════════════════════════════════════════════════════════════
tab_video, tab_photo = st.tabs(["🎬  A · Buat Video", "🖼️  B · Photo Slide"])

with tab_video:
    st.caption("Upload beberapa file video. Setiap file dipotong otomatis 4–6 detik.")
    video_files = st.file_uploader(
        "Upload Video (bisa lebih dari 1)",
        type=["mp4", "mov", "avi"],
        accept_multiple_files=True,
        key="up_video",
    )

with tab_photo:
    st.caption(
        "Upload foto (maks 6). "
        "**Ken Burns Effect** (slow zoom 100% → 115%) diterapkan otomatis."
    )
    photo_files = st.file_uploader(
        "Upload Foto (maks 6)",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        key="up_photo",
    )
    if photo_files and len(photo_files) > 6:
        st.warning("⚠️ Maksimal 6 foto. Hanya 6 pertama yang dipakai.")
        photo_files = photo_files[:6]

video_files = video_files or []
photo_files = photo_files or []
input_mode  = "photo" if (photo_files and not video_files) else "video"


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 16 — SESSION STATE
# ═══════════════════════════════════════════════════════════════════════════════
_SS_DEFAULTS = {
    "pass1_ready"  : False,
    "pass1_path"   : "",
    "pass2_done"   : False,
    "out_path"     : "",
    "video_bytes"  : None,
    "p1_out_w"     : 720,
    "p1_out_h"     : 1280,
    "p1_logo_pil"  : None,
    "p1_font_path" : "",
    "trim_segs"    : [],
    "trim_approved": False,
    "trim_vcs"     : [],   # open VideoFileClip handles
    "input_mode"   : "video",
    "photo_paths"  : [],
}
for _k, _v in _SS_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 17 — TOMBOL KONTROL UTAMA
# ═══════════════════════════════════════════════════════════════════════════════
st.divider()

# Status Pass 1 jika sudah ada
if st.session_state.pass1_ready:
    p1_path = st.session_state.pass1_path
    if os.path.exists(p1_path):
        sz = os.path.getsize(p1_path) / 1_048_576
        st.success(
            f"✅ **Pass 1 tersimpan** — `{p1_path}` ({sz:.1f} MB) · "
            f"{st.session_state.p1_out_w}×{st.session_state.p1_out_h}"
        )
    else:
        st.warning("⚠️ File Pass 1 tidak ditemukan. Jalankan ulang Pass 1.")
        st.session_state.pass1_ready = False

has_input = bool(video_files) or bool(photo_files)

c1, c2, c3 = st.columns([2, 2, 1])
with c1:
    btn_full  = st.button("🔍 Preview Trim & Siapkan",
                          disabled=not has_input, use_container_width=True)
with c2:
    btn_pass2 = st.button("✍️ Re-render Pass 2 (caption saja)",
                          disabled=not st.session_state.pass1_ready,
                          use_container_width=True)
with c3:
    btn_reset = st.button("🗑️ Reset", use_container_width=True)

# ── Tombol Reset ──────────────────────────────────────────────────────────────
if btn_reset:
    for vc in st.session_state.get("trim_vcs", []):
        try:
            vc.close()
        except Exception:
            pass
    cleanup_session(SID)
    gc.collect()
    for k in list(_SS_DEFAULTS.keys()):
        if k in st.session_state:
            del st.session_state[k]
    st.success("🗑️ Session direset.")
    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 18 — STEP 1: ANALISIS & PREVIEW TRIM / FOTO
# ═══════════════════════════════════════════════════════════════════════════════
if btn_full and has_input:
    # Tutup handle video lama
    for vc in st.session_state.get("trim_vcs", []):
        try:
            vc.close()
        except Exception:
            pass

    # Reset state untuk sesi render baru
    st.session_state.trim_segs     = []
    st.session_state.trim_approved = False
    st.session_state.trim_vcs      = []
    st.session_state.pass1_ready   = False
    st.session_state.pass2_done    = False
    st.session_state.video_bytes   = None
    st.session_state.input_mode    = input_mode

    # ── MODE A: Video ─────────────────────────────────────────────────────────
    if input_mode == "video":
        with st.status("🔍 Menganalisis video...", expanded=True) as status:
            open_vcs = []
            try:
                raw_clips = []
                for i, vf in enumerate(video_files):
                    raw = _tmp(f"tmp_{SID}_raw_{i}.mp4")
                    fin = _tmp(f"tmp_{SID}_v_{i}.mp4")

                    vf.seek(0)   # ← WAJIB: reset pointer file uploader
                    with open(raw, "wb") as fh:
                        fh.write(vf.read())

                    size_mb = os.path.getsize(raw) / 1_048_576
                    if size_mb > 400:
                        st.write(f"  ⚠️ Video {i+1}: {size_mb:.0f} MB → kompres...")
                        r = subprocess.run([
                            "ffmpeg", "-y", "-i", raw,
                            "-vf", "scale=720:-2",
                            "-vcodec", "libx264", "-crf", "28", "-preset", "ultrafast",
                            "-acodec", "aac", "-b:a", "128k",
                            fin,
                        ], capture_output=True, text=True)
                        if r.returncode != 0:
                            shutil.copy(raw, fin)
                        else:
                            st.write(f"  ✅ {size_mb:.0f}MB → {os.path.getsize(fin)/1_048_576:.0f}MB")
                    else:
                        shutil.copy(raw, fin)

                    _safe_remove(raw)   # hapus raw segera, hemat /tmp

                    vc = VideoFileClip(fin)
                    open_vcs.append(vc)
                    raw_clips.append(vc)
                    st.write(f"  📹 Video {i+1}: `{vf.name}` — {vc.duration:.1f}s")

                segments  = smart_cut_clips(raw_clips, durasi_target)
                fin_paths = [_tmp(f"tmp_{SID}_v_{i}.mp4")
                             for i in range(len(video_files))]

                st.session_state.trim_segs = [
                    {
                        **s,
                        "src_name": video_files[s["src_idx"]].name,
                        "src_path": fin_paths[s["src_idx"]],
                    }
                    for s in segments
                ]
                st.session_state.trim_vcs = open_vcs
                status.update(label=f"✅ {len(segments)} segmen siap di-preview",
                              state="complete")

            except Exception as e:
                status.update(label=f"❌ {e}", state="error")
                st.exception(e)
                for vc in open_vcs:
                    try:
                        vc.close()
                    except Exception:
                        pass

    # ── MODE B: Photo Slide ───────────────────────────────────────────────────
    else:
        with st.status("🖼️ Menyiapkan foto...", expanded=True) as status:
            try:
                photo_paths = []
                for i, pf in enumerate(photo_files[:6]):
                    ext = os.path.splitext(pf.name)[1]
                    p   = _tmp(f"tmp_{SID}_photo_{i}{ext}")
                    pf.seek(0)   # ← WAJIB
                    with open(p, "wb") as fh:
                        fh.write(pf.read())
                    photo_paths.append(p)
                    st.write(f"  🖼️ Foto {i+1}: `{pf.name}`")

                n     = len(photo_paths)
                per_s = max(5.0, min(8.0, durasi_target / n))
                segs  = [
                    {
                        "src_name": photo_files[i].name,
                        "seg_idx" : i,
                        "start"   : 0,
                        "end"     : per_s,
                        "duration": per_s,
                        "src_idx" : i,
                    }
                    for i in range(n)
                ]
                st.session_state.trim_segs   = segs
                st.session_state.photo_paths = photo_paths
                status.update(
                    label=f"✅ {n} foto · {per_s:.1f}s/slide · Ken Burns zoom 100%→115% 🎥",
                    state="complete",
                )
            except Exception as e:
                status.update(label=f"❌ {e}", state="error")

    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 19 — STEP 2: PREVIEW GRID SEGMEN / FOTO
# ═══════════════════════════════════════════════════════════════════════════════
def _extract_thumb(src: str, t: float, out_path: str) -> bool:
    """Ekstrak 1 frame thumbnail dari video via ffmpeg."""
    try:
        r = subprocess.run([
            "ffmpeg", "-y",
            "-ss", str(round(t, 2)), "-i", src,
            "-vframes", "1", "-vf", "scale=240:-2", "-q:v", "4",
            out_path,
        ], capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and os.path.exists(out_path)
    except Exception:
        return False


def _extract_mini(src: str, start: float, end: float, out_path: str) -> bool:
    """
    Ekstrak mini clip untuk preview — skala ke max 360px lebar/tinggi,
    aman untuk video portrait maupun landscape.
    """
    try:
        dur = max(0.5, round(end - start, 2))
        # scale=360:-2  → lebar max 360, tinggi auto (genap)
        # Untuk portrait (tinggi > lebar), gunakan -2:360
        # Tapi ffmpeg bisa handle keduanya dengan vf scale jika pakai min():
        # Pakai cara paling simpel & reliable: resize ke 360px lebar saja
        r = subprocess.run([
            "ffmpeg", "-y",
            "-ss", str(round(start, 2)),
            "-i",  src,
            "-t",  str(dur),
            "-vf", "scale=360:-2",        # 360px lebar, tinggi auto-even
            "-c:v", "libx264", "-crf", "28", "-preset", "ultrafast",
            "-an",                         # tanpa audio — lebih cepat
            "-movflags", "+faststart",
            out_path,
        ], capture_output=True, text=True, timeout=30)
        return r.returncode == 0 and os.path.exists(out_path)
    except Exception:
        return False


def _detect_scenes(src: str, threshold: float = 0.35, max_scenes: int = 20) -> list[float]:
    """
    Deteksi scene change dari video menggunakan ffmpeg select filter.
    Return list timestamp (detik) setiap scene change.
    Fallback ke [] jika ffmpeg gagal.
    """
    try:
        r = subprocess.run([
            "ffmpeg", "-i", src,
            "-filter:v", f"select='gt(scene,{threshold})',showinfo",
            "-frames:v", str(max_scenes),
            "-f", "null", "-",
        ], capture_output=True, text=True, timeout=20)
        # Parse "pts_time:" dari stderr
        import re
        times = [float(m) for m in re.findall(r"pts_time:([\d.]+)", r.stderr)]
        return sorted(set(times))
    except Exception:
        return []


if st.session_state.trim_segs and not st.session_state.pass1_ready:
    segs = st.session_state.trim_segs
    mode = st.session_state.input_mode

    st.subheader("📋 Preview Segmen" if mode == "video" else "🖼️ Preview Urutan Foto")
    if mode == "photo":
        st.info("✨ Ken Burns Effect (zoom 100% → 115%) akan diterapkan otomatis saat render.")

    # ── Panel Trim Manual (hanya mode video) ───────────────────────────────
    if mode == "video":
        with st.expander("✂️ Trim Manual — atur ulang IN/OUT setiap segmen", expanded=False):
            st.caption(
                "Geser slider **Start** dan **End** untuk mengubah titik potong. "
                "Klik **Terapkan Trim** setelah selesai."
            )
            updated_segs  = list(segs)
            needs_refresh = False

            for i, s in enumerate(segs):
                vc_list = st.session_state.get("trim_vcs", [])
                src_idx = s.get("src_idx", 0)
                try:
                    max_dur = vc_list[src_idx].duration if src_idx < len(vc_list) else s["end"] + 10
                except Exception:
                    max_dur = s["end"] + 10

                st.markdown(f"**Segmen #{i+1}** · `{s['src_name'][:24]}`")
                c_s, c_e = st.columns(2)
                new_start = c_s.number_input(
                    "Start (dtk)", min_value=0.0,
                    max_value=float(max_dur) - 0.5,
                    value=float(s["start"]),
                    step=0.5, key=f"trim_s_{i}",
                )
                new_end = c_e.number_input(
                    "End (dtk)", min_value=new_start + 0.5,
                    max_value=float(max_dur),
                    value=float(s["end"]),
                    step=0.5, key=f"trim_e_{i}",
                )
                if new_start != s["start"] or new_end != s["end"]:
                    updated_segs[i] = {
                        **s,
                        "start"   : round(new_start, 2),
                        "end"     : round(new_end,   2),
                        "duration": round(new_end - new_start, 2),
                    }
                    needs_refresh = True

            col_apply, col_scene = st.columns(2)
            if col_apply.button("✅ Terapkan Trim", use_container_width=True, type="primary"):
                # Re-assign seg_idx urut setelah trim
                for i, seg in enumerate(updated_segs):
                    seg["seg_idx"] = i
                # Hapus cache mini clips agar di-generate ulang dengan titik baru
                for i in range(len(segs) + 5):
                    _safe_remove(_tmp(f"tmp_{SID}_mn_{i}.mp4"))
                    _safe_remove(_tmp(f"tmp_{SID}_th_{i}.jpg"))
                st.session_state.trim_segs = updated_segs
                st.rerun()

            # ── Deteksi Scene Change ────────────────────────────────────────
            if col_scene.button("🎬 Deteksi Scene Change", use_container_width=True,
                                help="Temukan titik potong alami berdasarkan perubahan adegan"):
                with st.spinner("Menganalisis scene change..."):
                    # Buat map src_idx → {path, name, duration}
                    src_info = {}
                    for s in segs:
                        si = s.get("src_idx", 0)
                        if si not in src_info:
                            src_info[si] = {
                                "path": s.get("src_path", ""),
                                "name": s.get("src_name", f"Video {si+1}"),
                            }

                    vc_list = st.session_state.get("trim_vcs", [])
                    new_segs = []

                    for si, sinfo in src_info.items():
                        sp = sinfo["path"]
                        sname = sinfo["name"]
                        if not sp or not os.path.exists(sp):
                            continue
                        try:
                            vid_dur = vc_list[si].duration if si < len(vc_list) else 0
                        except Exception:
                            vid_dur = 0
                        if vid_dur <= 0:
                            continue

                        scene_times = _detect_scenes(sp, threshold=0.35)

                        def _make_segs_from_boundaries(boundaries, si, sp, sname, max_seg_dur=8.0):
                            result = []
                            for k in range(len(boundaries) - 1):
                                seg_start = boundaries[k]
                                seg_end   = boundaries[k + 1]
                                seg_dur   = seg_end - seg_start
                                if seg_dur < 1.5:
                                    continue
                                # Sub-potong jika terlalu panjang
                                t = seg_start
                                while t < seg_end - 0.5:
                                    end_t = min(t + max_seg_dur, seg_end)
                                    result.append({
                                        "src_idx" : si,
                                        "src_name": sname,
                                        "src_path": sp,
                                        "start"   : round(t, 2),
                                        "end"     : round(end_t, 2),
                                        "duration": round(end_t - t, 2),
                                    })
                                    t += max_seg_dur
                            return result

                        if len(scene_times) < 2:
                            # Fallback: potong uniform 5 detik
                            boundaries = list(range(0, int(vid_dur), 5)) + [vid_dur]
                        else:
                            boundaries = [0.0] + scene_times + [vid_dur]

                        new_segs += _make_segs_from_boundaries(
                            boundaries, si, sp, sname
                        )

                    if new_segs:
                        for i, s in enumerate(new_segs):
                            s["seg_idx"] = i
                        # Hapus semua cache
                        for i in range(len(segs) + len(new_segs) + 10):
                            _safe_remove(_tmp(f"tmp_{SID}_mn_{i}.mp4"))
                            _safe_remove(_tmp(f"tmp_{SID}_th_{i}.jpg"))
                        st.session_state.trim_segs = new_segs
                        st.success(
                            f"✅ Ditemukan **{len(new_segs)} segmen** "
                            f"berdasarkan {len([t for si,sinfo in src_info.items() for t in _detect_scenes(sinfo['path'])])} scene change."
                        )
                        st.rerun()
                    else:
                        st.warning("Tidak ada segmen valid. Coba turunkan threshold atau cek durasi video.")

    # ── Grid Preview ───────────────────────────────────────────────────────
    N_COLS = 3
    for row in [segs[i:i + N_COLS] for i in range(0, len(segs), N_COLS)]:
        cols = st.columns(N_COLS)
        for col, s in zip(cols, row):
            with col:
                if mode == "video":
                    idx     = s["seg_idx"]
                    src     = s.get("src_path", "")
                    thumb_p = _tmp(f"tmp_{SID}_th_{idx}.jpg")
                    mini_p  = _tmp(f"tmp_{SID}_mn_{idx}.mp4")

                    if not os.path.exists(thumb_p):
                        _extract_thumb(src, s["start"] + s["duration"] / 2, thumb_p)
                    if os.path.exists(thumb_p):
                        st.image(thumb_p, use_container_width=True)
                    else:
                        st.markdown("🎬")

                    st.caption("**#{}** {}  \n{:.1f}s – {:.1f}s · **{:.1f}s**".format(
                        idx + 1, s["src_name"][:16],
                        s["start"], s["end"], s["duration"],
                    ))
                    with st.expander("▶ Play clip"):
                        if not os.path.exists(mini_p):
                            with st.spinner("Memotong clip..."):
                                ok_mini = _extract_mini(src, s["start"], s["end"], mini_p)
                        # ← FIX: baca sebagai bytes agar bisa di-serve Streamlit Cloud
                        if os.path.exists(mini_p):
                            try:
                                with open(mini_p, "rb") as fv:
                                    st.video(fv.read(), format="video/mp4")
                            except Exception:
                                st.warning("Gagal memutar clip.")
                        else:
                            st.warning("Gagal mengekstrak clip.")

                else:  # photo
                    photo_paths = st.session_state.get("photo_paths", [])
                    if s["src_idx"] < len(photo_paths):
                        st.image(photo_paths[s["src_idx"]], use_container_width=True)
                    st.caption("**Slide {}** {}  \n**{:.1f}s**/slide 🎥".format(
                        s["seg_idx"] + 1, s["src_name"][:16], s["duration"],
                    ))

    st.divider()
    total_seg = sum(s["duration"] for s in segs)
    st.info(
        f"📊 **{len(segs)} segmen** · total **{total_seg:.1f}s** "
        f"(target: {durasi_target}s)"
    )

    ca, cb = st.columns(2)
    btn_ok    = ca.button("✅ OK — Lanjut Render", use_container_width=True, type="primary")
    btn_retry = cb.button("🔄 Acak Ulang Urutan",   use_container_width=True)

    if btn_retry:
        random.shuffle(st.session_state.trim_segs)
        st.rerun()
    if btn_ok:
        st.session_state.trim_approved = True
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 20 — STEP 3: RENDER PASS 1 (BULLETPROOF PIPELINE)
# ═══════════════════════════════════════════════════════════════════════════════
if st.session_state.trim_approved and not st.session_state.pass1_ready:

    segs       = st.session_state.trim_segs
    mode       = st.session_state.input_mode
    pass1_path = _tmp(f"tmp_{SID}_pass1.mp4")
    out_path   = f"output/out_{SID}.mp4"

    # Tentukan resolusi output
    if   "360p"  in resolusi: OUT_W, OUT_H = 202,  360
    elif "720p"  in resolusi: OUT_W, OUT_H = 720,  1280
    elif "1080p" in resolusi: OUT_W, OUT_H = 1080, 1920
    else:
        # Original: gunakan dimensi video/foto pertama
        if mode == "video" and segs:
            src_vcs = st.session_state.get("trim_vcs", [])
            if src_vcs:
                _cw, _ch = src_vcs[0].size
                _ratio   = _cw / _ch
                if _ratio >= 1:   # landscape/square
                    OUT_W, OUT_H = 720, 1280
                else:
                    OUT_W  = min(1080, _cw)
                    OUT_H  = int(OUT_W / _ratio)
            else:
                OUT_W, OUT_H = 720, 1280
        else:
            OUT_W, OUT_H = 720, 1280

    with st.status("⏳ Pass 1: Render...", expanded=True) as status:
        open_clips = []   # ← SEMUA resource dicatat di sini
        try:
            # ── Proses logo (WAJIB seek(0)) ────────────────────────────────────
            logo_pil = None
            if logo_file:
                logo_tmp = _tmp(f"tmp_{SID}_logo.png")
                logo_file.seek(0)   # ← WAJIB
                with open(logo_tmp, "wb") as fh:
                    fh.write(logo_file.read())
                try:
                    logo_pil = Image.open(logo_tmp).convert("RGBA")
                    st.write("🖼️ Logo dimuat.")
                except Exception as e:
                    st.warning(f"⚠️ Logo gagal: {e}")

            # ── Bangun clips_916 ────────────────────────────────────────────────
            clips_916 = []

            if mode == "video":
                fin_vcs = st.session_state.get("trim_vcs", [])
                for s in segs:
                    try:
                        vc  = fin_vcs[s["src_idx"]]
                        sub = vc.subclipped(s["start"], s["end"])
                        f16 = fit_to_916(sub, OUT_W, OUT_H)
                        open_clips.append(f16)
                        clips_916.append(f16)
                        st.write(
                            f"  ✂️ {s['src_name'][:20]} "
                            f"[{s['start']:.1f}–{s['end']:.1f}s]"
                        )
                    except Exception as e:
                        st.warning(f"  ⚠️ Segmen {s.get('seg_idx','')+1} gagal: {e}")

            else:  # photo
                photo_paths = st.session_state.get("photo_paths", [])
                st.write("🖼️ Membangun slideshow Ken Burns (100%→115%)...")
                base_slide = build_photo_slideshow(
                    photo_paths, durasi_target, OUT_W, OUT_H,
                    fade_dur=0.5, zoom_end=1.15,
                )
                clips_916 = [base_slide]
                gc.collect()   # bebaskan frame buffer foto

            if not clips_916:
                raise ValueError(
                    "Tidak ada klip yang berhasil diproses. "
                    "Cek video/foto yang diupload."
                )

            # ── Overlay logo pada setiap clip (jika ada) ───────────────────────
            if logo_pil is not None:
                lw = max(20, int(OUT_W * 0.20))
                lh = max(1,  int(logo_pil.height * lw / logo_pil.width))
                lr = logo_pil.resize((lw, lh), Image.LANCZOS).convert("RGBA")
                ln = np.array(lr).astype(np.float32)
                lx = (OUT_W - lw) // 2
                ly = min(max(4, int(OUT_H * 0.03)), OUT_H - lh - 4)

                def _add_logo(frame,
                              _ln=ln, _lx=lx, _ly=ly, _lw=lw, _lh=lh):
                    if frame.shape[0] < _ly + _lh or frame.shape[1] < _lx + _lw:
                        return frame
                    out   = frame.copy().astype(np.float32)
                    patch = out[_ly:_ly + _lh, _lx:_lx + _lw]
                    alpha = _ln[:, :, 3:] / 255.0
                    out[_ly:_ly + _lh, _lx:_lx + _lw] = (
                        patch * (1.0 - alpha) + _ln[:, :, :3] * alpha
                    )
                    return out.astype(np.uint8)

                clips_916 = [c.image_transform(_add_logo) for c in clips_916]
                st.write("✅ Logo diterapkan ke semua klip.")

            # ── Gabungkan dengan transisi ───────────────────────────────────────
            st.write("🔗 Menggabungkan klip...")
            if len(clips_916) == 1:
                base = clips_916[0]
            elif jenis_transisi == "Crossfade":
                base = crossfade_concat(clips_916, fade_d=fade_dur)
            elif jenis_transisi == "Fade to Black":
                faded = []
                for i, c in enumerate(clips_916):
                    fx = ([] if i == 0 else [FadeIn(fade_dur)]) + [FadeOut(fade_dur)]
                    faded.append(c.with_effects(fx))
                base = concatenate_videoclips(faded, method="chain")
            else:
                base = concatenate_videoclips(clips_916, method="chain")

            # ── Render Pass 1 ke /tmp ───────────────────────────────────────────
            status.update(label="⏳ Rendering Pass 1...")
            st.write(f"💾 Render → `{pass1_path}`...")
            base.write_videofile(
                pass1_path,
                codec="libx264",
                audio_codec="aac",
                fps=24,
                ffmpeg_params=["-pix_fmt", "yuv420p"],
                logger=None,
            )
            try:
                base.close()
            except Exception:
                pass

            # Tutup trim_vcs setelah Pass 1 selesai (file tidak diperlukan lagi)
            for vc in st.session_state.get("trim_vcs", []):
                try:
                    vc.close()
                except Exception:
                    pass
            st.session_state.trim_vcs = []
            gc.collect()

            # Simpan metadata Pass 1 ke session state
            st.session_state.pass1_ready  = True
            st.session_state.pass1_path   = pass1_path
            st.session_state.p1_out_w     = OUT_W
            st.session_state.p1_out_h     = OUT_H
            st.session_state.p1_logo_pil  = logo_pil
            st.session_state.p1_font_path = selected_font_path
            st.write("✅ **Pass 1 selesai.**")

            # ── Lanjut Pass 2 segera ─────────────────────────────────────────
            status.update(label="⏳ Pass 2: Overlay caption + CTA...")
            st.write("## ✍️ Pass 2: Overlay Caption + CTA + Progress Bar")

            ok, captions, err = run_pass2(
                pass1_path    = pass1_path,
                out_path      = out_path,
                deskripsi     = deskripsi,
                n_caption     = n_caption,
                detail_colors = detail_colors,
                cta_nama      = cta_nama,
                cta_wa        = cta_wa,
                cta_dur       = cta_dur,
                cta_label     = cta_label,
                do_grade      = do_grade,
                brightness    = brightness,
                contrast      = contrast,
                saturation    = saturation,
                sharpness     = sharpness,
                bgm_file      = bgm_file,
                bgm_volume    = bgm_volume,
                orig_vol      = orig_vol,
                OUT_W         = OUT_W,
                OUT_H         = OUT_H,
                logo_pil      = logo_pil,
                font_path     = selected_font_path,
                caption_align = caption_align,
            )

            if not ok:
                status.update(label=f"❌ Pass 2 error: {err}", state="error")
                st.error(err)
            else:
                with open(out_path, "rb") as fh:
                    st.session_state.video_bytes = fh.read()
                gc.collect()   # bebaskan RAM setelah video besar dimuat
                st.session_state.pass2_done = True
                st.session_state.out_path   = out_path
                status.update(label="✅ Selesai! Video siap didownload.", state="complete")

        except Exception as e:
            status.update(label=f"❌ Error: {e}", state="error")
            st.exception(e)

        finally:
            # ── WAJIB: tutup SEMUA resource — cegah OOM / force close ──────────
            for oc in open_clips:
                try:
                    oc.close()
                except Exception:
                    pass
            gc.collect()


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 21 — RE-RENDER PASS 2 SAJA (edit caption tanpa ulang Pass 1)
# ═══════════════════════════════════════════════════════════════════════════════
if btn_pass2 and st.session_state.pass1_ready:
    p1   = st.session_state.pass1_path
    op   = f"output/out_{SID}.mp4"
    OW   = st.session_state.p1_out_w
    OH   = st.session_state.p1_out_h
    lpil = st.session_state.p1_logo_pil
    fpth = st.session_state.p1_font_path

    if not os.path.exists(p1):
        st.error(f"❌ File Pass 1 `{p1}` tidak ditemukan. Jalankan ulang Pass 1.")
    else:
        st.session_state.pass2_done  = False
        st.session_state.video_bytes = None

        with st.status("⏳ Re-render Pass 2...", expanded=True) as status:
            ok, captions, err = run_pass2(
                pass1_path    = p1,
                out_path      = op,
                deskripsi     = deskripsi,
                n_caption     = n_caption,
                detail_colors = detail_colors,
                cta_nama      = cta_nama,
                cta_wa        = cta_wa,
                cta_dur       = cta_dur,
                cta_label     = cta_label,
                do_grade      = do_grade,
                brightness    = brightness,
                contrast      = contrast,
                saturation    = saturation,
                sharpness     = sharpness,
                bgm_file      = bgm_file,
                bgm_volume    = bgm_volume,
                orig_vol      = orig_vol,
                OUT_W         = OW,
                OUT_H         = OH,
                logo_pil      = lpil,
                font_path     = fpth,
                caption_align = caption_align,
            )

            if not ok:
                status.update(label=f"❌ Error: {err}", state="error")
                st.error(err)
            else:
                with open(op, "rb") as fh:
                    st.session_state.video_bytes = fh.read()
                gc.collect()
                st.session_state.pass2_done = True
                st.session_state.out_path   = op
                status.update(label="✅ Re-render selesai!", state="complete")


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 22 — PREVIEW & DOWNLOAD
# ═══════════════════════════════════════════════════════════════════════════════
if st.session_state.pass2_done and st.session_state.video_bytes:
    st.divider()
    st.subheader("🎬 Preview & Download")

    # ← FIX: gunakan bytes agar reliable di Streamlit Cloud (path /tmp tidak di-serve)
    st.video(st.session_state.video_bytes, format="video/mp4")

    ca, cb = st.columns([3, 1])
    with ca:
        st.download_button(
            label="⬇️ Download Video Final",
            data=st.session_state.video_bytes,
            file_name=(
                f"mansion_{SID}_"
                f"{st.session_state.p1_out_w}x{st.session_state.p1_out_h}.mp4"
            ),
            mime="video/mp4",
            use_container_width=True,
        )
    with cb:
        if st.button("🔄 Perbaiki Caption", use_container_width=True):
            st.info("💡 Edit deskripsi di sidebar → klik **✍️ Re-render Pass 2**")

    st.caption(
        "💡 Caption salah? Edit deskripsi di sidebar → "
        "**✍️ Re-render Pass 2** (Pass 1 tidak diulang, lebih cepat)"
    )