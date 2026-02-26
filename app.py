"""
Mansion Video Generator — Two-Pass Rendering
=============================================
Pass 1 : Gabungkan klip mentah + logo → simpan video_pass1_{SID}.mp4
Pass 2 : Baca Pass 1 → overlay caption (dari deskripsi) + CTA + progress bar
         → simpan output final

Struktur folder:
  /assets   — logo, font, dll
  /output   — hasil render final
"""

import streamlit as st
import os, glob, uuid, random, shutil, subprocess, gc
from pathlib import Path

from moviepy import VideoFileClip, concatenate_videoclips, VideoClip, AudioFileClip
from moviepy import CompositeAudioClip
from moviepy.video.fx import Crop, FadeIn, FadeOut
from moviepy.audio.fx import AudioFadeOut, MultiplyVolume

from PIL import Image, ImageFilter, ImageDraw, ImageFont, ImageEnhance
import numpy as np

# ── NLP Engine Detection ─────────────────────────────────────────────────────
import sys, os

# Tambahkan folder project ke sys.path agar NLTK/TextBlob lokal terdeteksi
_project_dir = os.path.dirname(os.path.abspath(__file__))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

# Cari juga subfolder umum tempat pip install --target menyimpan package
for _sub in ["lib", "Lib", "site-packages",
             os.path.join("lib", "python3", "site-packages"),
             os.path.join("Lib", "site-packages")]:
    _p = os.path.join(_project_dir, _sub)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

NLP_ENGINE = "builtin"   # default fallback

try:
    import nltk

    # Arahkan NLTK ke folder data lokal project jika ada
    _nltk_local = os.path.join(_project_dir, "nltk_data")
    if os.path.isdir(_nltk_local) and _nltk_local not in nltk.data.path:
        nltk.data.path.insert(0, _nltk_local)

    from nltk.tokenize import sent_tokenize

    # Verifikasi punkt tersedia (coba tokenize dulu)
    try:
        sent_tokenize("test sentence.")
        NLP_ENGINE = "nltk"
    except LookupError:
        # Coba download ke folder lokal project
        nltk.download("punkt",     download_dir=_nltk_local, quiet=True)
        nltk.download("punkt_tab", download_dir=_nltk_local, quiet=True)
        nltk.data.path.insert(0, _nltk_local)
        sent_tokenize("test sentence.")   # coba lagi
        NLP_ENGINE = "nltk"

except (ImportError, Exception):
    try:
        from textblob import TextBlob
        TextBlob("test").sentences   # verifikasi bisa jalan
        NLP_ENGINE = "textblob"
    except (ImportError, Exception):
        NLP_ENGINE = "builtin"

# ── folder setup ──────────────────────────────────────────────────────────────
Path("assets").mkdir(exist_ok=True)
Path("output").mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# KONSTANTA
# ─────────────────────────────────────────────────────────────────────────────
CAPTION_COLORS = [
    (255, 215,   0),   # Gold   — HOOK
    (255, 255, 255),   # White
    (192, 192, 192),   # Silver
    (255, 223, 128),   # Champagne
    (210, 180, 140),   # Rose Gold
]
HOOK_COLOR   = (255, 215, 0)    # Caption pertama selalu Gold (HOOK)
STROKE_COLOR = (0, 0, 0)
STROKE_W     = 1

# ── Safe zone TikTok / Reels (9:16) ──────────────────────────────────────────
# TikTok UI: username + caption + tombol mulai ~82% dari atas
# Reels  UI: tombol + caption mulai ~80% dari atas
# → Konten penting harus selesai sebelum 78% dari atas agar aman di semua platform
#
#   0%  ┌─────────────────┐
#   3%  │  LOGO           │  ← logo aman
#   12% │  [safe top]     │
#       │                 │
#   62% │  CAPTION        │  ← caption selesai max di ~72%
#   72% │  CTA block      │  ← CTA selesai max di ~78%
#   78% ├ ─ ─ ─ ─ ─ ─ ─ ┤  ← BATAS AMAN
#   80% │  [Reels UI]     │  zona berbahaya
#   82% │  [TikTok UI]    │
#  100% └─────────────────┘

CAPTION_Y    = 0.60   # posisi TOP caption — dihitung dari bawah agar tidak tabrakan TikTok/Reels UI
CTA_Y        = 0.66   # posisi TOP CTA block — bawah CTA max di SAFE_BOTTOM (78%)
SAFE_BOTTOM  = 0.78   # batas bawah aman — Reels UI mulai 80%, TikTok mulai 82%

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Mansion Video Generator", layout="centered")
st.title("🎬 Mansion Video Generator")
st.caption("Aplikasi untuk membuat Video Konten Sosial Media")

# ─── SESSION ID ───────────────────────────────────────────────────────────────
if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex[:8]
SID = st.session_state.session_id
st.caption(f"🔑 Session: `{SID}`")

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:

    # ── Deskripsi Properti ────────────────────────────────────────────────────
    st.header("📝 Deskripsi Properti")
    deskripsi = st.text_area(
        "Tuliskan deskripsi lengkap properti",
        value=(
            "Rumah 2 Lantai Citraland Surabaya. "
            "Luas Tanah 8x15, 4 KT. "
            "Full Renovasi + Roof Top. "
            "Lokasi strategis dekat pusat bisnis dan sekolah internasional ."
            "Harga Rp 5.5 M, nego."
        ),
        height=160,
    )
    n_caption = st.slider("Jumlah Caption (dari Deskripsi)", 1, 5, 3,
                          help="Deskripsi akan dipecah menjadi N caption otomatis")

    # ── CTA ───────────────────────────────────────────────────────────────────
    st.header("📞 CTA (Caption Akhir)")
    cta_label = st.text_input("Teks Label", "Hubungi :")
    cta_nama  = st.text_input("Nama Agen", "Budi Santoso")
    cta_wa    = st.text_input("Nomor WhatsApp", "0812-3456-7890")
    cta_dur   = st.slider("Durasi CTA (detik terakhir)", 2, 8, 4)

    # ── Warna Caption ─────────────────────────────────────────────────────────
    st.header("🎨 Warna Caption 2–5")
    color_names  = ["Gold", "White", "Silver", "Champagne", "Rose Gold"]
    detail_colors = []
    for i in range(1, 5):   # caption 2-5 (caption 1 = HOOK, selalu Gold)
        c = st.selectbox(f"Caption {i+1}", options=color_names,
                         index=i % len(color_names), key=f"color_{i}")
        detail_colors.append(CAPTION_COLORS[color_names.index(c)])

    # ── Auto Color Grading ────────────────────────────────────────────────────
    st.header("✨ Auto Color Grading")
    do_grade   = st.toggle("Aktifkan", value=False)
    brightness = st.slider("Brightness",  0.7, 1.5, 1.05, 0.05)
    contrast   = st.slider("Contrast",    0.7, 1.5, 1.10, 0.05)
    saturation = st.slider("Saturation",  0.7, 1.5, 1.05, 0.05)
    sharpness  = st.slider("Sharpness",   0.7, 2.0, 1.10, 0.05)

    # ── Logo ──────────────────────────────────────────────────────────────────
    st.header("🖼️ Logo")
    logo_file = st.file_uploader("Upload Logo (PNG)", type=["png"])

    # ── BGM ───────────────────────────────────────────────────────────────────
    st.header("🎵 Background Music")
    bgm_file   = st.file_uploader("Upload MP3/WAV", type=["mp3", "wav"])
    bgm_volume = st.slider("Volume BGM", 0.1, 1.0, 0.5, 0.05)
    orig_vol   = st.slider("Volume Video (jika ada BGM)", 0.0, 1.0, 0.8, 0.05)

    # ── Durasi & Resolusi ─────────────────────────────────────────────────────
    st.header("⏱️ Durasi Target")
    durasi_target = st.slider("Detik", 15, 60, 30)

    st.header("🎞️ Resolusi Output")
    resolusi = st.radio("Resolusi", [
        "360p  (202×360)",
        "720p  (720×1280) - Best",
        "1080p (1080×1920)",
        "Original",
    ], index=1)

    st.header("🎬 Transisi Antar Klip")
    jenis_transisi = st.radio("Jenis", [
        "Crossfade", "Fade to Black", "Tanpa Transisi",
    ], index=0)
    fade_dur = st.slider("Durasi Transisi (detik)", 0.2, 1.5, 0.5, 0.1)

# ── Upload Video ──────────────────────────────────────────────────────────────
video_files = st.file_uploader(
    "Upload Video (bisa lebih dari 1)",
    type=["mp4", "mov", "avi"],
    accept_multiple_files=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS — NLP: pecah deskripsi jadi N caption
# ─────────────────────────────────────────────────────────────────────────────
def split_description_to_captions(text: str, n: int) -> list[str]:
    """
    Pecah teks deskripsi menjadi N caption.
    - NLTK / TextBlob jika tersedia (lebih akurat)
    - Builtin regex sebagai fallback
    Caption[0] = HOOK = kalimat pertama (pendek & kuat).
    Caption[1..n] = distribusi merata sisa kalimat.
    """
    import re
    text = text.strip()
    if not text:
        return [f"CAPTION {i+1}" for i in range(n)]

    # ── Tokenize kalimat ──────────────────────────────────────────────────────
    sentences = []
    if NLP_ENGINE == "nltk":
        try:
            from nltk.tokenize import sent_tokenize
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
        # Builtin: split hanya sebelum huruf kapital (hindari potong "Rp 5.5")
        sentences = [s.strip()
                     for s in re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
                     if s.strip()]

    if not sentences:
        sentences = [text]

    # ── HOOK = kalimat pertama selalu berdiri sendiri di caption[0] ───────────
    hook      = sentences[0].upper()
    rest      = sentences[1:]          # sisa kalimat dibagi ke caption 2..n

    if n == 1:
        return [hook]

    n_rest    = n - 1                  # slot untuk caption 2..n
    captions  = [hook]

    if not rest:
        # Hanya 1 kalimat, duplikasi atau kosongkan sisanya
        captions += [""] * n_rest
    elif len(rest) <= n_rest:
        # Sisa kalimat ≤ slot: 1 kalimat per slot, sisanya kosong
        captions += [s.upper() for s in rest]
        while len(captions) < n:
            captions.append("")
    else:
        # Sisa kalimat > slot: distribusi merata ke n_rest bucket
        bucket = len(rest) / n_rest
        for i in range(n_rest):
            start = int(i * bucket)
            end   = int((i + 1) * bucket)
            end   = max(end, start + 1)   # minimal 1 kalimat per bucket
            chunk = " ".join(rest[start:end])
            captions.append(chunk.upper())

    return captions[:n]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS — Font
# ─────────────────────────────────────────────────────────────────────────────
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/roboto/Roboto-Black.ttf",
    "/usr/share/fonts/truetype/roboto/RobotoCondensed-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "assets/font.ttf",
]

def get_font_path() -> str:
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return ""

def get_font(size: int, font_path: str = "") -> ImageFont.FreeTypeFont:
    p = font_path or get_font_path()
    if p:
        try:
            return ImageFont.truetype(p, max(8, size))
        except Exception:
            pass
    return ImageFont.load_default()

def fit_text_font(text: str, max_w: int, font_path: str, start_size: int):
    """Shrink font sampai satu baris muat. Fallback 8px."""
    dummy  = Image.new("RGBA", (1, 1))
    draw   = ImageDraw.Draw(dummy)
    size   = max(8, start_size)
    prev_w = None
    while size >= 8:
        f  = get_font(size, font_path)
        bb = draw.textbbox((0, 0), text, font=f)
        tw = bb[2] - bb[0]
        if tw <= max_w:
            return f, size
        if prev_w is not None and tw >= prev_w:
            break
        prev_w = tw
        size  -= 2
    return get_font(8, font_path), 8


def wrap_text(text: str, font, max_w: int, draw: ImageDraw.ImageDraw,
              max_lines: int = 3) -> list[str]:
    """
    Pecah teks menjadi baris-baris agar setiap baris muat dalam max_w.
    Maksimal max_lines baris. Jika masih melebihi, kata terakhir diganti '…'.
    """
    words = text.split()
    if not words:
        return [""]

    lines, current = [], ""
    for word in words:
        test = (current + " " + word).strip()
        bb   = draw.textbbox((0, 0), test, font=font)
        if (bb[2] - bb[0]) <= max_w:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)

    # Potong ke max_lines, tambah … jika kepotong
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if lines:
        last = lines[-1]
        bb   = draw.textbbox((0, 0), last, font=font)
        if (bb[2] - bb[0]) > max_w:
            # Potong kata terakhir sampai muat + …
            words_last = last.split()
            while words_last:
                candidate = " ".join(words_last) + "…"
                bb2 = draw.textbbox((0, 0), candidate, font=font)
                if (bb2[2] - bb2[0]) <= max_w:
                    lines[-1] = candidate
                    break
                words_last.pop()
    return lines if lines else [""]


def wrap_text_complete(text: str, font, max_w: int,
                       draw: ImageDraw.ImageDraw) -> list:
    """
    Word-wrap tanpa membuang kata.
    Setiap kata dijamin masuk — tidak ada yang terpotong/dibuang.
    """
    words = text.split()
    if not words:
        return [""]
    lines, current = [], ""
    for word in words:
        test = (current + " " + word).strip()
        bb   = draw.textbbox((0, 0), test, font=font)
        if (bb[2] - bb[0]) <= max_w:
            current = test
        else:
            if current:
                lines.append(current)
            current = word   # mulai baris baru dengan kata ini
    if current:
        lines.append(current)
    return lines if lines else [""]


def fit_and_wrap(text: str, max_w: int, font_path: str, start_size: int,
                 max_lines: int = 3) -> tuple:
    """
    Shrink font 1px per iterasi sampai semua kata muat dalam max_lines.
    TIDAK ADA kata yang dibuang — semua kata selalu ditampilkan.
    Jika font sudah 8px tapi masih > max_lines, tampilkan semua baris
    (lebih panjang dari max_lines, tapi lebih baik daripada terpotong).
    """
    dummy = Image.new("RGBA", (1, 1))
    draw  = ImageDraw.Draw(dummy)
    size  = max(8, start_size)

    while size >= 8:
        f     = get_font(size, font_path)
        lines = wrap_text_complete(text, f, max_w, draw)
        if len(lines) <= max_lines:
            return f, lines
        size -= 1   # turun 1px agar lebih halus

    # Last resort: font 8px, tampilkan semua baris walau > max_lines
    f     = get_font(8, font_path)
    lines = wrap_text_complete(text, f, max_w, draw)
    return f, lines

def compute_layout(out_w: int):
    font_size      = max(13, int(out_w * 0.040))
    hook_font_size = max(15, int(out_w * 0.055))   # HOOK lebih besar
    pad_x = max(8,  int(out_w * 0.045))
    pad_y = max(4,  int(out_w * 0.018))
    return font_size, hook_font_size, pad_x, pad_y


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS — Render Overlay
# ─────────────────────────────────────────────────────────────────────────────
def _draw_text_with_stroke(draw, tx, ty, text, font, color_rgb):
    """Gambar teks dengan stroke hitam tipis di 8 arah."""
    for dx in range(-STROKE_W, STROKE_W + 1):
        for dy in range(-STROKE_W, STROKE_W + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((tx + dx, ty + dy), text, font=font,
                      fill=(*STROKE_COLOR, 255))
    r, g, b = color_rgb
    draw.text((tx, ty), text, font=font, fill=(r, g, b, 255))


def render_caption_overlay(text: str, out_w: int, out_h: int,
                            start_size: int, pad_x: int, pad_y: int,
                            color_rgb=(255,255,255), font_path="",
                            logo_pil=None, max_lines: int = 3) -> np.ndarray:
    """
    Render caption sebagai overlay RGBA.
    Teks di-wrap otomatis maks max_lines baris.
    Jika masih terlalu panjang, font di-shrink dulu baru wrap ulang.
    """
    canvas = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)

    if text.strip():
        box_w  = max(1, out_w - pad_x * 2)
        usable = max(1, box_w - 8)   # 4px margin kiri+kanan, tidak terlalu sempit

        # Dapatkan font + wrapped lines sekaligus
        font, lines = fit_and_wrap(text, usable, font_path, start_size, max_lines)

        # Ukur tinggi total semua baris
        line_h   = max(1, draw.textbbox((0,0), "Ag", font=font)[3])
        line_gap = max(2, int(line_h * 0.07))
        total_h  = line_h * len(lines) + line_gap * (len(lines) - 1)

        # Posisi blok teks — safe zone TikTok/Reels
        # TOP caption dimulai di CAPTION_Y, tapi bawah blok tidak boleh lewat SAFE_BOTTOM
        safe_bottom_px = int(out_h * SAFE_BOTTOM)
        ty_block = int(out_h * CAPTION_Y)
        # Geser ke atas jika blok teks melewati batas aman
        if ty_block + total_h > safe_bottom_px:
            ty_block = max(0, safe_bottom_px - total_h - pad_y)

        # Gambar setiap baris
        cur_y = ty_block
        for line in lines:
            if not line.strip():
                cur_y += line_h + line_gap
                continue
            bb = draw.textbbox((0, 0), line, font=font)
            lw = bb[2] - bb[0]
            tx = pad_x + (box_w - lw) // 2
            tx = max(pad_x, tx)   # jangan sampai keluar kiri
            _draw_text_with_stroke(draw, tx, cur_y, line, font, color_rgb)
            cur_y += line_h + line_gap

    _paste_logo(canvas, out_w, out_h, logo_pil)
    return np.array(canvas).astype(np.float32)


def render_cta_overlay(nama: str, wa: str, out_w: int, out_h: int,
                       start_size: int, pad_x: int, pad_y: int,
                       font_path="", logo_pil=None,
                       label: str = "HUBUNGI :") -> np.ndarray:
    canvas = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)

    lines = []
    if label: lines.append((label.upper(), (255, 255, 255)))  # White
    if nama:  lines.append((nama.upper(),  (255, 215, 0)))    # Gold
    if wa:    lines.append((f"WA: {wa}",   (255, 255, 255)))  # White

    if lines:
        box_w  = max(1, out_w - pad_x * 2)
        usable = max(1, box_w - pad_x)
        rendered = []
        for idx_l, (text, color) in enumerate(lines):
            if idx_l == 0 and label:                                       # "HUBUNGI :"
                sz = max(8, int(start_size * 0.60))
            elif (idx_l == 1 and label) or (idx_l == 0 and not label):    # nama
                sz = max(8, int(start_size * 0.80))
            else:                                                           # WA
                sz = max(8, int(start_size * 0.60))
            font, _ = fit_text_font(text, usable, font_path, sz)
            bb   = draw.textbbox((0, 0), text, font=font)
            rendered.append((text, color, font,
                             max(1, bb[2]-bb[0]), max(1, bb[3]-bb[1])))

        line_gap    = max(4, pad_y)
        total_txt_h = sum(r[4] for r in rendered) + line_gap * (len(rendered)-1)

        # Hitung posisi blok CTA — safe zone TikTok/Reels
        safe_bottom_px = int(out_h * SAFE_BOTTOM)
        x_left = pad_x
        # Total tinggi = teks + garis emas + padding atas
        gold_line_h = max(2, int(out_h * 0.003))
        block_total = total_txt_h + gold_line_h + pad_y * 3
        # Mulai dari CTA_Y, tapi geser ke atas jika blok melewati SAFE_BOTTOM
        y_top = int(out_h * CTA_Y)
        if y_top + block_total > safe_bottom_px:
            y_top = max(0, safe_bottom_px - block_total)

        # ── Garis emas tipis di atas blok CTA ────────────────────────────────
        draw.rectangle([x_left, y_top,
                        x_left + box_w, y_top + gold_line_h],
                       fill=(255, 215, 0, 255))
        y_top = y_top + gold_line_h + pad_y   # geser teks ke bawah garis

        # ── Teks tanpa background ─────────────────────────────────────────────
        cur_y = y_top   # y_top sudah include garis emas + pad
        for text, color, font, tw, th in rendered:
            tx = x_left + (box_w - tw) // 2
            # Stroke hitam agar teks terbaca di video apapun
            for dx in range(-STROKE_W, STROKE_W + 1):
                for dy in range(-STROKE_W, STROKE_W + 1):
                    if dx == 0 and dy == 0: continue
                    draw.text((tx+dx, cur_y+dy), text, font=font, fill=(0,0,0,255))
            r, g, b = color
            draw.text((tx, cur_y), text, font=font, fill=(r,g,b,255))
            cur_y += th + line_gap

    _paste_logo(canvas, out_w, out_h, logo_pil)
    return np.array(canvas).astype(np.float32)


def _paste_logo(canvas, out_w, out_h, logo_pil):
    if logo_pil is None:
        return
    try:
        logo_w = max(20, int(out_w * 0.25))
        logo_h = max(1, int(logo_pil.height * logo_w / logo_pil.width))
        logo_r = logo_pil.resize((logo_w, logo_h), Image.LANCZOS).convert("RGBA")
        lx     = (out_w - logo_w) // 2
        ly     = min(max(4, int(out_h * 0.03)), out_h - logo_h - 4)
        canvas.paste(logo_r, (lx, ly), logo_r)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS — Frame Processing
# ─────────────────────────────────────────────────────────────────────────────
def blend(frame: np.ndarray, overlay: np.ndarray) -> np.ndarray:
    if frame.shape[:2] != overlay.shape[:2]:
        return frame
    rgb   = overlay[:, :, :3]
    alpha = overlay[:, :, 3:] / 255.0
    return np.clip(
        frame.astype(np.float32) * (1-alpha) + rgb * alpha,
        0, 255
    ).astype(np.uint8)

def grade_frame(frame, br, co, sa, sh):
    img = Image.fromarray(frame.astype(np.uint8))
    img = ImageEnhance.Brightness(img).enhance(br)
    img = ImageEnhance.Contrast(img).enhance(co)
    img = ImageEnhance.Color(img).enhance(sa)
    img = ImageEnhance.Sharpness(img).enhance(sh)
    return np.array(img)

def draw_progress_bar(frame, t, total_dur, out_w, out_h, bar_h=4):
    if total_dur <= 0: return frame
    result  = frame.copy()
    bar_w   = int(out_w * min(max(t/total_dur, 0), 1))
    bar_y0  = max(0, out_h - bar_h)
    result[bar_y0:out_h, :, :]      = (result[bar_y0:out_h,:,:] * 0.3).astype(np.uint8)
    if bar_w > 0:
        result[bar_y0:out_h, :bar_w, :] = 255
    return result


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS — Video Processing
# ─────────────────────────────────────────────────────────────────────────────
def blur_clip(clip, radius=25):
    def _blur(f):
        return np.array(Image.fromarray(f).filter(ImageFilter.GaussianBlur(radius)))
    return clip.image_transform(_blur)

def fit_to_916(clip, out_w, out_h):
    """Resize klip ke 9:16. Landscape → blur background + center foreground."""
    try:
        cw, ch    = clip.size
        src_ratio = cw / ch
        dst_ratio = out_w / out_h

        if abs(src_ratio - dst_ratio) < 0.05:
            return clip.resized((out_w, out_h))

        scale_h  = out_h / ch
        bg_w_raw = max(out_w, int(cw * scale_h))
        bg       = blur_clip(clip.resized((bg_w_raw, out_h)), radius=25)

        if bg_w_raw > out_w:
            x1 = (bg_w_raw - out_w) // 2
            bg = bg.with_effects([Crop(x1=x1, x2=x1+out_w, y1=0, y2=out_h)])

        fg_h  = max(1, int(out_w / src_ratio))
        fg    = clip.resized((out_w, fg_h))
        fg_y0 = (out_h - fg_h) // 2
        fg_y1 = fg_y0 + fg_h

        def compose(t):
            res             = bg.get_frame(t).copy()
            res[fg_y0:fg_y1] = fg.get_frame(t)
            return res

        out = VideoClip(compose, duration=clip.duration).with_fps(clip.fps or 24)
        if clip.audio is not None:
            out = out.with_audio(clip.audio)
        return out
    except Exception as e:
        st.warning(f"fit_to_916 fallback: {e}")
        return clip.resized((out_w, out_h))

def crossfade_concat(clips, fade_d):
    if len(clips) == 1:
        return clips[0]
    min_dur = min(c.duration for c in clips)
    fd      = min(fade_d, min_dur * 0.4)
    starts  = [0.0]
    for c in clips[:-1]:
        starts.append(starts[-1] + c.duration - fd)
    total_dur = starts[-1] + clips[-1].duration

    def frame_func(t):
        result = None
        for i, clip in enumerate(clips):
            cs, ce = starts[i], starts[i] + clip.duration
            if t < cs or t >= ce: continue
            lt    = min(t - cs, clip.duration - 1e-4)
            frame = clip.get_frame(lt)
            if result is None:
                result = frame.astype(np.float32)
            else:
                alpha = min(1.0, (t - cs) / max(fd, 1e-6))
                result = result*(1-alpha) + frame.astype(np.float32)*alpha
        if result is None:
            result = clips[-1].get_frame(clips[-1].duration - 1e-4).astype(np.float32)
        return np.clip(result, 0, 255).astype(np.uint8)

    out   = VideoClip(frame_func, duration=total_dur)
    audio = [c.audio.with_start(starts[i])
             for i, c in enumerate(clips) if c.audio is not None]
    if audio:
        out = out.with_audio(CompositeAudioClip(audio))
    return out.with_fps(clips[0].fps or 24)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS — Cleanup
# ─────────────────────────────────────────────────────────────────────────────
def cleanup_session(sid: str):
    patterns = [
        f"tmp_{sid}_*",
        f"output/out_{sid}_*.mp4",
        f"output/pass1_{sid}.mp4",
    ]
    for pat in patterns:
        for f in glob.glob(pat):
            try: os.remove(f)
            except Exception: pass


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — Pass 2 (dapat dipanggil ulang tanpa Pass 1)
# ─────────────────────────────────────────────────────────────────────────────
def run_pass2(pass1_path, out_path, deskripsi, n_caption, detail_colors,
              cta_nama, cta_wa, cta_dur, cta_label, do_grade, brightness, contrast,
              saturation, sharpness, bgm_file, bgm_volume, orig_vol,
              OUT_W, OUT_H, logo_pil):
    """
    Jalankan Pass 2: baca pass1_path, overlay caption + CTA + grading,
    simpan ke out_path. Return: (success: bool, captions: list, error: str)
    """
    open_clips = []
    bgm_tmp    = None
    try:
        # ── NLP: pecah deskripsi → captions ──────────────────────────────────
        engine_label = {
            "nltk"    : "🟢 NLTK",
            "textblob": "🟡 TextBlob",
            "builtin" : "🔵 Regex"
        }
        st.write(f"🧠 NLP: **{engine_label.get(NLP_ENGINE, NLP_ENGINE)}** "
                 f"| {n_caption} caption dari deskripsi")
        captions = split_description_to_captions(deskripsi, n_caption)

        # ── Preview caption di expander ───────────────────────────────────────
        with st.expander("📋 Preview Caption (klik untuk lihat/sembunyikan)", expanded=True):
            for i, cap in enumerate(captions):
                tag = "🪝 HOOK" if i == 0 else f"📌 Detail {i}"
                st.markdown(f"**Caption {i+1}** `[{tag}]`")
                st.info(cap)
            if cta_nama.strip() or cta_wa.strip():
                st.markdown("**CTA (4 detik terakhir)**")
                st.success(f"📞 {cta_nama}  |  WA: {cta_wa}")

        # ── Layout & font ─────────────────────────────────────────────────────
        font_size, hook_size, pad_x, pad_y = compute_layout(OUT_W)
        font_path = get_font_path()
        bar_h     = max(3, int(OUT_H * 0.006))

        # ── Pre-render overlays ───────────────────────────────────────────────
        all_colors = [HOOK_COLOR] + list(detail_colors)
        overlays   = []
        for idx, cap in enumerate(captions):
            color = all_colors[idx % len(all_colors)]
            sz    = hook_size if idx == 0 else font_size
            ov    = render_caption_overlay(
                cap, OUT_W, OUT_H, sz, pad_x, pad_y,
                color_rgb=color, font_path=font_path, logo_pil=logo_pil)
            overlays.append(ov)

        # ── CTA overlay ───────────────────────────────────────────────────────
        cta_overlay = None
        if cta_nama.strip() or cta_wa.strip():
            cta_overlay = render_cta_overlay(
                cta_nama.strip(), cta_wa.strip(),
                OUT_W, OUT_H, font_size, pad_x, pad_y,
                font_path=font_path, logo_pil=logo_pil,
                label=cta_label.strip() if cta_label.strip() else "")

        # ── Baca Pass 1 ───────────────────────────────────────────────────────
        st.write(f"📂 Membaca Pass 1...")
        p1_clip   = VideoFileClip(pass1_path)
        open_clips.append(p1_clip)
        total_dur = p1_clip.duration
        n_cap     = len(captions)
        interval  = total_dur / max(n_cap, 1)
        cta_start = max(0.0, total_dur - cta_dur)
        audio_src = p1_clip.audio

        schedule = " | ".join([
            f"{i+1}. {i*interval:.0f}s–{(i+1)*interval:.0f}s"
            for i in range(n_cap)
        ])
        st.write(f"🕐 {schedule}")

        # ── BGM ───────────────────────────────────────────────────────────────
        if bgm_file:
            try:
                bgm_tmp = f"tmp_bgm_{os.getpid()}.mp3"
                with open(bgm_tmp, "wb") as f: f.write(bgm_file.read())
                bgm_raw   = AudioFileClip(bgm_tmp)
                if bgm_raw.duration > total_dur:
                    bgm_raw = bgm_raw.subclipped(0, total_dur)
                fo_dur    = min(3.0, bgm_raw.duration * 0.3)
                bgm_audio = bgm_raw.with_effects([
                    AudioFadeOut(fo_dur), MultiplyVolume(bgm_volume)
                ])
                if audio_src is not None:
                    audio_src = audio_src.with_effects([MultiplyVolume(orig_vol)])
                mixed = [a for a in [audio_src, bgm_audio] if a is not None]
                if mixed:
                    audio_src = CompositeAudioClip(mixed)
                st.write(f"  ✅ BGM {bgm_raw.duration:.1f}s, fade-out {fo_dur:.1f}s")
            except Exception as e:
                st.warning(f"BGM gagal: {e}")

        # ── Capture closure vars ──────────────────────────────────────────────
        _do  = bool(do_grade)
        _br  = float(brightness) if _do else 1.0
        _co  = float(contrast)   if _do else 1.0
        _sa  = float(saturation) if _do else 1.0
        _sh  = float(sharpness)  if _do else 1.0
        _ovs = list(overlays)
        _cta = cta_overlay
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
                frame = blend(frame, _cta)
            else:
                idx   = min(int(t / _iv), _nc - 1)
                frame = blend(frame, _ovs[idx])
            return draw_progress_bar(frame, t, _td, _ow, _oh, _bh)

        # ── Render Pass 2 ─────────────────────────────────────────────────────
        st.write("🎬 Render Pass 2...")
        final_video = p1_clip.transform(pass2_proc)
        if audio_src is not None:
            final_video = final_video.with_audio(audio_src)

        final_video.write_videofile(
            out_path,
            codec="libx264", audio_codec="aac", fps=24,
            ffmpeg_params=["-pix_fmt", "yuv420p"],
            logger=None,
        )
        return True, captions, ""

    except Exception as e:
        return False, [], str(e)

    finally:
        for oc in open_clips:
            try: oc.close()
            except Exception: pass
        if bgm_tmp and os.path.exists(bgm_tmp):
            try: os.remove(bgm_tmp)
            except Exception: pass
        gc.collect()


# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE — inisialisasi variabel state
# ─────────────────────────────────────────────────────────────────────────────
if "pass1_ready"  not in st.session_state: st.session_state.pass1_ready  = False
if "pass1_path"   not in st.session_state: st.session_state.pass1_path   = ""
if "pass2_done"   not in st.session_state: st.session_state.pass2_done   = False
if "out_path"     not in st.session_state: st.session_state.out_path     = ""
if "video_bytes"  not in st.session_state: st.session_state.video_bytes  = None
if "p1_out_w"     not in st.session_state: st.session_state.p1_out_w     = 202
if "p1_out_h"     not in st.session_state: st.session_state.p1_out_h     = 360
if "p1_logo_pil"  not in st.session_state: st.session_state.p1_logo_pil  = None


# ─────────────────────────────────────────────────────────────────────────────
# MAIN — TWO-PASS RENDER dengan Re-render Pass 2
# ─────────────────────────────────────────────────────────────────────────────
st.divider()

# ── STATUS BANNER ─────────────────────────────────────────────────────────────
if st.session_state.pass1_ready:
    p1_exists = os.path.exists(st.session_state.pass1_path)
    if p1_exists:
        p1_mb = os.path.getsize(st.session_state.pass1_path) / (1024*1024)
        st.success(
            f"✅ **Pass 1 tersimpan** — `{st.session_state.pass1_path}` "
            f"({p1_mb:.1f} MB) · "
            f"{st.session_state.p1_out_w}×{st.session_state.p1_out_h}"
        )
    else:
        st.warning("⚠️ File Pass 1 tidak ditemukan. Jalankan ulang Pass 1.")
        st.session_state.pass1_ready = False

# ── TOMBOL AKSI ───────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns([2, 2, 1])

with col1:
    btn_full   = st.button(
        "🚀Buat Video ",
        disabled=not bool(video_files),
        use_container_width=True,
        help="Proses penuh dari awal — wajib jika ini pertama kali atau ganti video"
    )
with col2:
    btn_pass2  = st.button(
        "✍️ Re-Render ulang (caption saja)",
        disabled=not st.session_state.pass1_ready,
        use_container_width=True,
        help="Pakai video Pass 1 yang sudah ada, hanya render ulang caption/teks"
    )
with col3:
    btn_reset  = st.button(
        "🗑️ Reset",
        use_container_width=True,
        help="Hapus semua file session ini dan mulai dari nol"
    )

# ── RESET ─────────────────────────────────────────────────────────────────────
if btn_reset:
    cleanup_session(SID)
    for key in ["pass1_ready", "pass1_path", "pass2_done",
                "out_path", "video_bytes", "p1_out_w",
                "p1_out_h", "p1_logo_pil"]:
        if key in st.session_state:
            del st.session_state[key]
    st.success("🗑️ Session direset.")
    st.rerun()


# ── PASS 1 + PASS 2 PENUH ─────────────────────────────────────────────────────
if btn_full and video_files:

    # Reset state dulu
    cleanup_session(SID)
    st.session_state.pass1_ready = False
    st.session_state.pass2_done  = False
    st.session_state.video_bytes = None

    pass1_path = f"tmp_{SID}_pass1.mp4"
    out_path   = f"output/out_{SID}.mp4"

    with st.status("⏳ Pass 1: Menyiapkan klip...", expanded=True) as status:
        open_clips = []
        temp_paths = []
        try:
            # ── 1. Load & compress ────────────────────────────────────────────
            st.write("## 🎬 Pass 1: Gabungkan Klip")
            SIZE_LIMIT_MB = 500
            clips = []

            for i, vf in enumerate(video_files):
                raw = f"tmp_{SID}_raw_{i}.mp4"
                fin = f"tmp_{SID}_v_{i}.mp4"
                with open(raw, "wb") as f: f.write(vf.read())
                temp_paths += [raw, fin]

                size_mb = os.path.getsize(raw) / (1024*1024)
                if size_mb > SIZE_LIMIT_MB:
                    st.write(f"  ⚠️ Video {i+1}: {size_mb:.0f}MB → kompres...")
                    res = subprocess.run([
                        "ffmpeg", "-y", "-i", raw,
                        "-vf", "scale=720:-2",
                        "-vcodec", "libx264", "-crf", "22",
                        "-preset", "fast",
                        "-acodec", "aac", "-b:a", "128k", fin
                    ], capture_output=True, text=True)
                    if res.returncode != 0:
                        st.warning("Kompres gagal, pakai original.")
                        shutil.copy(raw, fin)
                    else:
                        st.write(f"  ✅ {size_mb:.0f}MB → {os.path.getsize(fin)/1024/1024:.0f}MB")
                else:
                    shutil.copy(raw, fin)
                    st.write(f"  ✅ Video {i+1}: {size_mb:.0f}MB")

                vc = VideoFileClip(fin)
                open_clips.append(vc)
                clips.append(vc)

            # ── 2. Resolusi ───────────────────────────────────────────────────
            first_w, first_h = clips[0].size
            if   "360p"     in resolusi: OUT_W, OUT_H = 202, 360
            elif "720p"     in resolusi: OUT_W, OUT_H = 720, 1280
            elif "Original" in resolusi:
                OUT_W = first_w if first_w <= first_h else first_h * 9 // 16
                OUT_H = first_h if first_w <= first_h else first_h
            else: OUT_W, OUT_H = 1080, 1920
            st.write(f"📐 Resolusi: **{OUT_W}×{OUT_H}**")

            # ── 3. Shuffle + trim ─────────────────────────────────────────────
            combined = list(zip(clips,
                [f"tmp_{SID}_v_{i}.mp4" for i in range(len(clips))]))
            random.shuffle(combined)
            clips, clip_paths = zip(*combined)
            clips = list(clips)

            n_clips   = len(clips)
            total_dur = sum(c.duration for c in clips)
            st.write(f"🔀 {n_clips} klip | Total {total_dur:.1f}s → target {durasi_target}s")

            dur_per_clip = (durasi_target / n_clips) if total_dur > durasi_target else None
            trimmed = []
            for i, c in enumerate(clips):
                need      = min(dur_per_clip or c.duration, c.duration)
                max_start = max(0.0, c.duration - need)
                start     = random.uniform(0, max_start) if max_start > 0.1 else 0.0
                end       = min(start + need, c.duration)
                trimmed.append(c.subclipped(start, end))
                st.write(f"  ✂️ Klip {i+1}: ambil {start:.1f}s–{end:.1f}s")
            clips = trimmed

            # ── 4. Fit 9:16 ───────────────────────────────────────────────────
            st.write("🔄 Konversi 9:16...")
            clips_916 = [fit_to_916(c, OUT_W, OUT_H) for c in clips]

            # ── 5. Logo ───────────────────────────────────────────────────────
            logo_pil = None
            if logo_file:
                logo_tmp = f"tmp_{SID}_logo.png"
                with open(logo_tmp, "wb") as f: f.write(logo_file.read())
                temp_paths.append(logo_tmp)
                try:
                    logo_pil = Image.open(logo_tmp).convert("RGBA")
                except Exception as e:
                    st.warning(f"Logo gagal: {e}")

            if logo_pil is not None:
                logo_w  = max(20, int(OUT_W * 0.20))
                logo_h  = max(1, int(logo_pil.height * logo_w / logo_pil.width))
                logo_r  = logo_pil.resize((logo_w, logo_h), Image.LANCZOS).convert("RGBA")
                logo_np = np.array(logo_r).astype(np.float32)
                lx = (OUT_W - logo_w) // 2
                ly = min(max(4, int(OUT_H * 0.03)), OUT_H - logo_h - 4)

                def add_logo(frame):
                    if frame.shape[0] < ly+logo_h or frame.shape[1] < lx+logo_w:
                        return frame
                    out   = frame.copy().astype(np.float32)
                    patch = out[ly:ly+logo_h, lx:lx+logo_w]
                    alpha = logo_np[:,:,3:] / 255.0
                    out[ly:ly+logo_h, lx:lx+logo_w] = (
                        patch*(1-alpha) + logo_np[:,:,:3]*alpha)
                    return out.astype(np.uint8)

                clips_916 = [c.image_transform(add_logo) for c in clips_916]
                st.write("🖼️ Logo OK.")

            # ── 6. Transisi & gabung ──────────────────────────────────────────
            st.write("🔗 Menggabungkan...")
            if jenis_transisi == "Crossfade":
                base = crossfade_concat(clips_916, fade_d=fade_dur)
            elif jenis_transisi == "Fade to Black":
                faded = []
                for i, c in enumerate(clips_916):
                    fx = ([] if i==0 else [FadeIn(fade_dur)]) + [FadeOut(fade_dur)]
                    faded.append(c.with_effects(fx))
                base = concatenate_videoclips(faded, method="chain")
            else:
                base = concatenate_videoclips(clips_916, method="chain")

            # ── 7. Render Pass 1 → disk ───────────────────────────────────────
            status.update(label="⏳ Pass 1: Rendering...")
            st.write(f"💾 Render Pass 1 → `{pass1_path}`...")
            base.write_videofile(
                pass1_path,
                codec="libx264", audio_codec="aac", fps=24,
                ffmpeg_params=["-pix_fmt", "yuv420p"],
                logger=None,
            )

            # ── 8. Bersihkan memori Pass 1 ────────────────────────────────────
            st.write("🧹 Bersihkan memori Pass 1...")
            try: base.close()
            except: pass
            for oc in open_clips:
                try: oc.close()
                except: pass
            open_clips.clear()
            del base, clips, clips_916, trimmed
            gc.collect()

            # ── Simpan state Pass 1 ───────────────────────────────────────────
            st.session_state.pass1_ready = True
            st.session_state.pass1_path  = pass1_path
            st.session_state.p1_out_w    = OUT_W
            st.session_state.p1_out_h    = OUT_H
            st.session_state.p1_logo_pil = logo_pil
            st.write("✅ **Pass 1 selesai & tersimpan di session.**")

            # ── 9. Langsung lanjut Pass 2 ─────────────────────────────────────
            status.update(label="⏳ Pass 2: Overlay caption...")
            st.write("## ✍️ Pass 2: Overlay Caption")
            ok, captions, err = run_pass2(
                pass1_path   = pass1_path,
                out_path     = out_path,
                deskripsi    = deskripsi,
                n_caption    = n_caption,
                detail_colors= detail_colors,
                cta_nama     = cta_nama,
                cta_wa       = cta_wa,
                cta_dur      = cta_dur,
                cta_label    = cta_label,
                do_grade     = do_grade,
                brightness   = brightness,
                contrast     = contrast,
                saturation   = saturation,
                sharpness    = sharpness,
                bgm_file     = bgm_file,
                bgm_volume   = bgm_volume,
                orig_vol     = orig_vol,
                OUT_W        = OUT_W,
                OUT_H        = OUT_H,
                logo_pil     = logo_pil,
            )

            if not ok:
                status.update(label=f"❌ Pass 2 error: {err}", state="error")
                st.error(err)
            else:
                with open(out_path, "rb") as f:
                    st.session_state.video_bytes = f.read()
                st.session_state.pass2_done = True
                st.session_state.out_path   = out_path
                status.update(label="✅ Selesai!", state="complete")

        except Exception as e:
            status.update(label=f"❌ Error: {e}", state="error")
            st.exception(e)
        finally:
            for oc in open_clips:
                try: oc.close()
                except: pass
            for p in temp_paths:
                if os.path.exists(p):
                    try: os.remove(p)
                    except: pass
            gc.collect()


# ── RE-RENDER PASS 2 SAJA (caption diperbaiki, Pass 1 dipakai ulang) ──────────
if btn_pass2 and st.session_state.pass1_ready:

    pass1_path = st.session_state.pass1_path
    out_path   = f"output/out_{SID}.mp4"
    OUT_W      = st.session_state.p1_out_w
    OUT_H      = st.session_state.p1_out_h
    logo_pil   = st.session_state.p1_logo_pil

    if not os.path.exists(pass1_path):
        st.error(f"❌ File Pass 1 `{pass1_path}` tidak ditemukan. Jalankan Pass 1 ulang.")
    else:
        st.session_state.pass2_done  = False
        st.session_state.video_bytes = None

        with st.status("⏳ Re-render Pass 2...", expanded=True) as status:
            st.write("## ✍️ Re-render Pass 2 (Pass 1 dipakai ulang)")
            ok, captions, err = run_pass2(
                pass1_path   = pass1_path,
                out_path     = out_path,
                deskripsi    = deskripsi,
                n_caption    = n_caption,
                detail_colors= detail_colors,
                cta_nama     = cta_nama,
                cta_wa       = cta_wa,
                cta_dur      = cta_dur,
                cta_label    = cta_label,
                do_grade     = do_grade,
                brightness   = brightness,
                contrast     = contrast,
                saturation   = saturation,
                sharpness    = sharpness,
                bgm_file     = bgm_file,
                bgm_volume   = bgm_volume,
                orig_vol     = orig_vol,
                OUT_W        = OUT_W,
                OUT_H        = OUT_H,
                logo_pil     = logo_pil,
            )
            if not ok:
                status.update(label=f"❌ Error: {err}", state="error")
                st.error(err)
            else:
                with open(out_path, "rb") as f:
                    st.session_state.video_bytes = f.read()
                st.session_state.pass2_done = True
                st.session_state.out_path   = out_path
                status.update(label="✅ Re-render selesai!", state="complete")


# ── PREVIEW & DOWNLOAD (tampil jika Pass 2 sudah selesai) ────────────────────
if st.session_state.pass2_done and st.session_state.video_bytes:
    st.divider()
    st.subheader("🎬 Preview & Download")

    out_path = st.session_state.out_path
    if os.path.exists(out_path):
        st.video(out_path)

    col_a, col_b = st.columns([3, 1])
    with col_a:
        st.download_button(
            label    = "⬇️ Download Video Final",
            data     = st.session_state.video_bytes,
            file_name= f"mansion_{SID}_{st.session_state.p1_out_w}x{st.session_state.p1_out_h}.mp4",
            mime     = "video/mp4",
            use_container_width=True,
        )
    with col_b:
        if st.button("🔄 Perbaiki Caption", use_container_width=True):
            st.info("💡 Edit **Deskripsi** atau **jumlah caption** di sidebar, "
                    "lalu klik **✍️ Re-render Pass 2** — Pass 1 tidak perlu diulang.")

    st.caption(
        f"💡 **Caption salah?** Ubah deskripsi di sidebar → klik "
        f"**✍️ Re-render Pass 2** (Pass 1 tidak diulang, hemat waktu)"
    )