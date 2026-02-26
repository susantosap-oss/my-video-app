"""
Mansion Video Generator — Two-Pass Rendering
=============================================
Pass 1 : Gabungkan klip mentah + logo → simpan /tmp/pass1_{SID}.mp4
Pass 2 : Baca Pass 1 → overlay caption (dari deskripsi) + CTA + progress bar
         → simpan output final

Struktur folder:
  /assets   — logo, dll
  /fonts    — file .ttf (upload ke GitHub)
  /output   — hasil render final

Versi ini sudah disesuaikan untuk Linux / Streamlit Cloud.
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

# ── [LINUX] ImageMagick untuk MoviePy TextClip ───────────────────────────────
try:
    from moviepy.config import change_settings
    change_settings({"IMAGEMAGICK_BINARY": "/usr/bin/convert"})
except Exception:
    pass  # Tidak semua versi MoviePy memerlukan ini

# ── [LINUX] NLTK — unduh data bahasa otomatis saat deployment ─────────────────
import nltk
# Unduh semua resource yang diperlukan agar tidak gagal saat runtime
for _nltk_pkg in ["punkt", "punkt_tab", "averaged_perceptron_tagger",
                  "stopwords", "wordnet"]:
    try:
        nltk.download(_nltk_pkg, quiet=True)
    except Exception:
        pass

# ── NLP Engine Detection ───────────────────────────────────────────────────────
import sys
_project_dir = os.path.dirname(os.path.abspath(__file__))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

NLP_ENGINE = "builtin"
try:
    from nltk.tokenize import sent_tokenize
    try:
        sent_tokenize("test sentence.")
        NLP_ENGINE = "nltk"
    except LookupError:
        nltk.download("punkt",     quiet=True)
        nltk.download("punkt_tab", quiet=True)
        sent_tokenize("test sentence.")
        NLP_ENGINE = "nltk"
except (ImportError, Exception):
    try:
        from textblob import TextBlob
        TextBlob("test").sentences
        NLP_ENGINE = "textblob"
    except (ImportError, Exception):
        NLP_ENGINE = "builtin"

# ── [LINUX] Folder setup — gunakan path relatif (aman di Streamlit Cloud) ─────
Path("assets").mkdir(exist_ok=True)
Path("fonts").mkdir(exist_ok=True)
Path("output").mkdir(exist_ok=True)

# ── [LINUX] Direktori temp — gunakan /tmp agar tidak kotor di repo ────────────
TMP_DIR = "/tmp"

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
HOOK_COLOR   = (255, 215, 0)
STROKE_COLOR = (0, 0, 0)
STROKE_W     = 2

# ── Garis vertikal Gold untuk align Left / Right ──────────────────────────────
VERT_LINE_W     = 6
VERT_LINE_GAP   = 10
VERT_LINE_COLOR = (255, 215, 0)

# ── Safe zone TikTok / Reels (9:16) ───────────────────────────────────────────
CAPTION_Y    = 0.52
CTA_Y        = 0.66
SAFE_BOTTOM  = 0.78

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Mansion Video Generator", layout="centered")

# ── [MOBILE] CSS responsif agar rapi di handphone ─────────────────────────────
st.markdown("""
<style>
/* Lebar sidebar tidak terlalu sempit di mobile */
[data-testid="stSidebar"] { min-width: 280px; }

/* Tombol full-width di layar kecil */
@media (max-width: 640px) {
    div[data-testid="column"] { width: 100% !important; flex: 1 1 100% !important; }
    .stButton > button { width: 100%; }
    /* Kurangi padding konten utama */
    .main .block-container { padding-left: 0.8rem; padding-right: 0.8rem; }
}

/* Paksa video player tidak overflow */
video { max-width: 100%; height: auto; }
</style>
""", unsafe_allow_html=True)

st.title("🎬 Mansion Video Generator")
st.caption("Aplikasi membuat video Konten Sosial Media dalam Format Portrait")

# ─── SESSION ID ────────────────────────────────────────────────────────────────
if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex[:8]
SID = st.session_state.session_id
st.caption(f"🔑 Session: `{SID}`")

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS — Font  (Linux-ready)
# ─────────────────────────────────────────────────────────────────────────────

# Label untuk font Linux sistem
_LINUX_FONT_LABELS = {
    "Roboto-Black.ttf"            : "Roboto Black",
    "RobotoCondensed-Bold.ttf"    : "Roboto Condensed Bold",
    "DejaVuSans-Bold.ttf"         : "DejaVu Sans Bold",
    "DejaVuSans.ttf"              : "DejaVu Sans",
    "LiberationSans-Bold.ttf"     : "Liberation Sans Bold",
    "LiberationSans.ttf"          : "Liberation Sans",
    "FreeSansBold.ttf"            : "Free Sans Bold",
    "FreeSans.ttf"                : "Free Sans",
    "NotoSans-Bold.ttf"           : "Noto Sans Bold",
    "NotoSans-Regular.ttf"        : "Noto Sans",
    "Ubuntu-Bold.ttf"             : "Ubuntu Bold",
    "Ubuntu-Regular.ttf"          : "Ubuntu",
    "OpenSans-Bold.ttf"           : "Open Sans Bold",
    "Oswald-Bold.ttf"             : "Oswald Bold",
    "Montserrat-Bold.ttf"         : "Montserrat Bold",
    "PlayfairDisplay-Bold.ttf"    : "Playfair Display Bold",
    "SourceSansPro-Bold.ttf"      : "Source Sans Pro Bold",
}

# [LINUX] Path font sistem Linux — tidak ada C:/Windows
_SYSTEM_FONT_PATHS = [
    # DejaVu (biasanya sudah ada di Ubuntu)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    # Liberation (kompatibel Arial)
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans.ttf",
    # FreeFont
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    # Roboto
    "/usr/share/fonts/truetype/roboto/Roboto-Black.ttf",
    "/usr/share/fonts/truetype/roboto/RobotoCondensed-Bold.ttf",
    # Noto
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    # Ubuntu
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
]


def scan_available_fonts() -> list[dict]:
    found      = []
    seen_paths = set()

    def add(path: str, label: str):
        p = os.path.normpath(path)
        if p not in seen_paths and os.path.exists(p):
            seen_paths.add(p)
            found.append({"label": label, "path": p})

    # [PRIORITAS 1] Folder fonts/ di repo (file yang di-upload ke GitHub)
    for ext in ("*.ttf", "*.TTF", "*.otf", "*.OTF"):
        for fp in glob.glob(os.path.join("fonts", ext)):
            fname = os.path.basename(fp)
            label = _LINUX_FONT_LABELS.get(
                fname,
                os.path.splitext(fname)[0].replace("_", " ").replace("-", " ").title()
            )
            add(fp, f"📁 {label}")

    # [PRIORITAS 2] Folder assets/ (backward compat)
    for ext in ("*.ttf", "*.TTF", "*.otf", "*.OTF"):
        for fp in glob.glob(os.path.join("assets", ext)):
            fname = os.path.basename(fp)
            label = os.path.splitext(fname)[0].replace("_", " ").replace("-", " ").title()
            add(fp, f"📁 {label}")

    # [PRIORITAS 3] Font sistem Linux
    for fp in _SYSTEM_FONT_PATHS:
        fname = os.path.basename(fp)
        label = _LINUX_FONT_LABELS.get(fname, os.path.splitext(fname)[0])
        add(fp, label)

    return found


def get_font_path(selected_path: str = "") -> str:
    if selected_path and os.path.exists(selected_path):
        return selected_path
    fonts = scan_available_fonts()
    return fonts[0]["path"] if fonts else ""


def get_font_path_debug(selected_path: str = "") -> str:
    p = get_font_path(selected_path)
    if p:
        st.sidebar.caption(f"🔤 Font aktif: `{os.path.basename(p)}`")
    else:
        st.sidebar.warning(
            "Tidak ada font TTF. Upload file .ttf ke folder `fonts/` di GitHub."
        )
    return p


def get_font(size: int, font_path: str = "") -> ImageFont.FreeTypeFont:
    p = font_path or get_font_path()
    if p:
        try:
            return ImageFont.truetype(p, max(8, size))
        except Exception:
            pass
    return ImageFont.load_default()

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("📝 Deskripsi Properti")
    deskripsi = st.text_area(
        "Tuliskan deskripsi lengkap properti",
        value=(
            "Rumah 1 Lantai Citraland Surabaya. "
            "LT 150m2 KT 3. "
            "Disain Arsitektur Modern dengan Rooftop. "
            "Lokasi strategis dekat pusat bisnis dan sekolah internasional. "
            "Harga Rp 5.5 M, nego."
        ),
        height=160,
    )
    n_caption = st.slider("Jumlah Caption (dari Deskripsi)", 1, 5, 3,
                          help="Deskripsi akan dipecah menjadi N caption otomatis")

    st.header("📞 CTA (Caption Akhir)")
    cta_label = st.text_input("Teks Label", "Hubungi :")
    cta_nama  = st.text_input("Nama Agen", "Nama_Agen")
    cta_wa    = st.text_input("Nomor WhatsApp", "0812-xxxx-xxxx")
    cta_dur   = st.slider("Durasi CTA (detik terakhir)", 2, 8, 4)

    st.header("🎨 Warna Caption 2–5")
    color_names   = ["Gold", "White", "Silver", "Champagne", "Rose Gold"]
    detail_colors = []
    for i in range(1, 5):
        c = st.selectbox(f"Caption {i+1}", options=color_names,
                         index=i % len(color_names), key=f"color_{i}")
        detail_colors.append(CAPTION_COLORS[color_names.index(c)])

    st.header("✨ Auto Color Grading")
    do_grade   = st.toggle("Aktifkan", value=False)
    brightness = st.slider("Brightness",  0.7, 1.5, 1.05, 0.05)
    contrast   = st.slider("Contrast",    0.7, 1.5, 1.10, 0.05)
    saturation = st.slider("Saturation",  0.7, 1.5, 1.05, 0.05)
    sharpness  = st.slider("Sharpness",   0.7, 2.0, 1.10, 0.05)

    # ── Font & Caption Alignment ───────────────────────────────────────────────
    st.header("🔤 Font & Caption Alignment")
    _avail_fonts = scan_available_fonts()
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
        st.warning(
            "Tidak ada font TTF. Upload file `.ttf` ke folder `fonts/` "
            "di GitHub lalu deploy ulang."
        )

    # ── Caption Alignment ──────────────────────────────────────────────────────
    caption_align = st.selectbox(
        "Caption Align",
        options=["Center", "Left", "Right"],
        index=0,
        help=(
            "Center : teks di tengah (tanpa garis).\n"
            "Left   : teks rata kiri  + garis Gold di sisi kiri.\n"
            "Right  : teks rata kanan + garis Gold di sisi kanan."
        ),
    )
    st.caption(
        "💡 Tambah font: upload file `.ttf` ke folder `fonts/` di GitHub."
    )

    st.header("🖼️ Logo")
    logo_file = st.file_uploader("Upload Logo (PNG)", type=["png"])

    st.header("🎵 Background Music")
    bgm_file   = st.file_uploader("Upload MP3/WAV", type=["mp3", "wav"])
    bgm_volume = st.slider("Volume BGM", 0.1, 1.0, 0.5, 0.05)
    orig_vol   = st.slider("Volume Video (jika ada BGM)", 0.0, 1.0, 0.8, 0.05)

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
    jenis_transisi = st.radio("Jenis", [
        "Crossfade", "Fade to Black", "Tanpa Transisi",
    ], index=0)
    fade_dur = st.slider("Durasi Transisi (detik)", 0.2, 1.5, 0.4, 0.1)

# ── Mode Input: Tab A (Video) | Tab B (Photo Slide) ───────────────────────────
tab_video, tab_photo = st.tabs(["🎬  A · Buat Video", "🖼️  B · Photo Slide"])

with tab_video:
    st.caption("Upload beberapa file video. Setiap file akan dipotong otomatis per 4–6 detik.")
    video_files = st.file_uploader(
        "Upload Video (bisa lebih dari 1)",
        type=["mp4", "mov", "avi"],
        accept_multiple_files=True,
        key="upload_video",
    )

with tab_photo:
    st.caption("Upload foto (maks 6). **Ken Burns Effect** (slow zoom-in) diterapkan otomatis.")
    photo_files = st.file_uploader(
        "Upload Foto (maks 6)",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        key="upload_photo",
    )
    if photo_files and len(photo_files) > 6:
        st.warning("⚠️ Maksimal 6 foto. Hanya 6 pertama yang dipakai.")
        photo_files = photo_files[:6]

if 'video_files' not in dir(): video_files = []
if 'photo_files' not in dir(): photo_files = []

input_mode = "photo" if (photo_files and not video_files) else "video"

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS — NLP: pecah deskripsi jadi N caption
# ─────────────────────────────────────────────────────────────────────────────
def _strip_trailing_punct(text: str) -> str:
    return text.rstrip(".!?").rstrip()


def split_description_to_captions(text: str, n: int) -> list[str]:
    import re
    text = text.strip()
    if not text:
        return [f"CAPTION {i+1}" for i in range(n)]
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
        sentences = [s.strip()
                     for s in re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
                     if s.strip()]
    if not sentences:
        sentences = [text]
    sentences = [_strip_trailing_punct(s) for s in sentences]
    hook  = sentences[0].upper()
    rest  = sentences[1:]
    if n == 1:
        return [hook]
    n_rest   = n - 1
    captions = [hook]
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
            chunk = " ".join(rest[start:end])
            captions.append(chunk.upper())
    MAX_WORDS = 8
    result = []
    for cap in captions[:n]:
        words = cap.split()
        if len(words) > MAX_WORDS:
            cap = " ".join(words[:MAX_WORDS]) + "…"
        result.append(cap)
    return result


def fit_text_font(text: str, max_w: int, font_path: str, start_size: int):
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


def wrap_text_complete(text: str, font, max_w: int,
                       draw: ImageDraw.ImageDraw) -> list:
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
    if current:
        lines.append(current)
    return lines if lines else [""]


def fit_and_wrap(text: str, max_w: int, font_path: str, start_size: int,
                 max_lines: int = 4) -> tuple:
    dummy = Image.new("RGBA", (1, 1))
    draw  = ImageDraw.Draw(dummy)
    size  = max(8, start_size)
    while size >= 8:
        f     = get_font(size, font_path)
        lines = wrap_text_complete(text, f, max_w, draw)
        if len(lines) <= max_lines:
            return f, lines
        size -= 1
    f     = get_font(8, font_path)
    lines = wrap_text_complete(text, f, max_w, draw)
    return f, lines


def compute_layout(out_w: int):
    font_size      = max(18, int(out_w * 0.065))
    hook_font_size = max(22, int(out_w * 0.080))
    pad_x = max(8,  int(out_w * 0.045))
    pad_y = max(4,  int(out_w * 0.018))
    return font_size, hook_font_size, pad_x, pad_y

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS — Render Overlay
# ─────────────────────────────────────────────────────────────────────────────
def _draw_text_with_stroke(draw, tx, ty, text, font, color_rgb):
    for dx in range(-STROKE_W, STROKE_W + 1):
        for dy in range(-STROKE_W, STROKE_W + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((tx + dx, ty + dy), text, font=font,
                      fill=(*STROKE_COLOR, 255))
    r, g, b = color_rgb
    draw.text((tx, ty), text, font=font, fill=(r, g, b, 255))


def render_caption_overlay(
    text: str, out_w: int, out_h: int,
    start_size: int, pad_x: int, pad_y: int,
    color_rgb=(255, 255, 255), font_path="",
    logo_pil=None, max_lines: int = 4,
    align: str = "Center",
) -> np.ndarray:
    canvas = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)
    if text.strip():
        line_margin = (VERT_LINE_W + VERT_LINE_GAP) if align != "Center" else 0
        box_w  = max(1, out_w - pad_x * 2)
        usable = max(1, box_w - line_margin - 8)
        font, lines = fit_and_wrap(text, usable, font_path, start_size, max_lines)
        line_h   = max(1, draw.textbbox((0, 0), "Ag", font=font)[3])
        line_gap = max(2, int(line_h * 0.10))
        total_h  = line_h * len(lines) + line_gap * (len(lines) - 1)
        safe_bottom_px = int(out_h * SAFE_BOTTOM)
        ty_block = int(out_h * CAPTION_Y)
        if ty_block + total_h > safe_bottom_px:
            ty_block = max(0, safe_bottom_px - total_h - pad_y)
        if align == "Left":
            gx0 = pad_x
            gx1 = pad_x + VERT_LINE_W
            draw.rectangle([gx0, ty_block, gx1, ty_block + total_h],
                           fill=(*VERT_LINE_COLOR, 255))
            text_x_anchor = gx1 + VERT_LINE_GAP
        elif align == "Right":
            gx1 = out_w - pad_x
            gx0 = gx1 - VERT_LINE_W
            draw.rectangle([gx0, ty_block, gx1, ty_block + total_h],
                           fill=(*VERT_LINE_COLOR, 255))
            text_x_end = gx0 - VERT_LINE_GAP
        cur_y = ty_block
        for line in lines:
            if not line.strip():
                cur_y += line_h + line_gap
                continue
            bb = draw.textbbox((0, 0), line, font=font)
            lw = bb[2] - bb[0]
            if align == "Left":
                tx = text_x_anchor
            elif align == "Right":
                tx = max(pad_x, text_x_end - lw)
            else:
                tx = max(pad_x, pad_x + (box_w - lw) // 2)
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
    lines  = []
    if label: lines.append((label.upper(), (255, 255, 255)))
    if nama:  lines.append((nama.upper(),  (255, 215, 0)))
    if wa:    lines.append((f"WA: {wa}",   (255, 255, 255)))
    if lines:
        box_w  = max(1, out_w - pad_x * 2)
        usable = max(1, box_w - pad_x)
        rendered = []
        for idx_l, (text, color) in enumerate(lines):
            if idx_l == 0 and label:
                sz = max(8, int(start_size * 0.60))
            elif (idx_l == 1 and label) or (idx_l == 0 and not label):
                sz = max(8, int(start_size * 0.80))
            else:
                sz = max(8, int(start_size * 0.60))
            font, _ = fit_text_font(text, usable, font_path, sz)
            bb      = draw.textbbox((0, 0), text, font=font)
            rendered.append((text, color, font,
                             max(1, bb[2]-bb[0]), max(1, bb[3]-bb[1])))
        line_gap       = max(4, pad_y)
        total_txt_h    = sum(r[4] for r in rendered) + line_gap * (len(rendered)-1)
        safe_bottom_px = int(out_h * SAFE_BOTTOM)
        x_left         = pad_x
        gold_line_h    = max(2, int(out_h * 0.003))
        block_total    = total_txt_h + gold_line_h + pad_y * 3
        y_top          = int(out_h * CTA_Y)
        if y_top + block_total > safe_bottom_px:
            y_top = max(0, safe_bottom_px - block_total)
        draw.rectangle([x_left, y_top, x_left + box_w, y_top + gold_line_h],
                       fill=(255, 215, 0, 255))
        cur_y = y_top + gold_line_h + pad_y
        for text, color, font, tw, th in rendered:
            tx = x_left + (box_w - tw) // 2
            for dx in range(-STROKE_W, STROKE_W + 1):
                for dy in range(-STROKE_W, STROKE_W + 1):
                    if dx == 0 and dy == 0: continue
                    draw.text((tx+dx, cur_y+dy), text, font=font, fill=(0,0,0,255))
            r, g, b = color
            draw.text((tx, cur_y), text, font=font, fill=(r, g, b, 255))
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
        frame.astype(np.float32) * (1-alpha) + rgb * alpha, 0, 255
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
    result = frame.copy()
    bar_w  = int(out_w * min(max(t/total_dur, 0), 1))
    bar_y0 = max(0, out_h - bar_h)
    result[bar_y0:out_h, :, :]       = (result[bar_y0:out_h,:,:] * 0.3).astype(np.uint8)
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
            res              = bg.get_frame(t).copy()
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
                alpha  = min(1.0, (t - cs) / max(fd, 1e-6))
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
# [LINUX] HELPERS — Cleanup: hapus file di /tmp
# ─────────────────────────────────────────────────────────────────────────────
def _tmp(filename: str) -> str:
    """Kembalikan path absolut di /tmp untuk file temporary."""
    return os.path.join(TMP_DIR, filename)


def cleanup_session(sid: str):
    patterns = [
        _tmp(f"tmp_{sid}_*"),
        f"output/out_{sid}_*.mp4",
        f"output/pass1_{sid}.mp4",
    ]
    for pat in patterns:
        for f in glob.glob(pat):
            try: os.remove(f)
            except Exception: pass

# ─────────────────────────────────────────────────────────────────────────────
# HELPER — Pass 2
# ─────────────────────────────────────────────────────────────────────────────
def run_pass2(pass1_path, out_path, deskripsi, n_caption, detail_colors,
              cta_nama, cta_wa, cta_dur, cta_label, do_grade, brightness, contrast,
              saturation, sharpness, bgm_file, bgm_volume, orig_vol,
              OUT_W, OUT_H, logo_pil,
              caption_align="Center"):
    open_clips  = []
    # [LINUX] Simpan BGM temp ke /tmp
    bgm_tmp     = _tmp(f"tmp_{SID}_bgm.mp3")
    bgm_created = False
    try:
        engine_label = {
            "nltk"    : "🟢 NLTK",
            "textblob": "🟡 TextBlob",
            "builtin" : "🔵 Regex",
        }
        st.write(f"🧠 NLP: **{engine_label.get(NLP_ENGINE, NLP_ENGINE)}** "
                 f"| {n_caption} caption · align **{caption_align}**")
        captions = split_description_to_captions(deskripsi, n_caption)
        with st.expander("📋 Preview Caption", expanded=True):
            for i, cap in enumerate(captions):
                tag = "🪝 HOOK" if i == 0 else f"📌 Detail {i}"
                st.markdown(f"**Caption {i+1}** `[{tag}]`")
                st.info(cap)
            if cta_nama.strip() or cta_wa.strip():
                st.markdown("**CTA (4 detik terakhir)**")
                st.success(f"📞 {cta_nama}  |  WA: {cta_wa}")
        font_size, hook_size, pad_x, pad_y = compute_layout(OUT_W)
        font_path = get_font_path_debug(selected_font_path)
        bar_h     = max(3, int(OUT_H * 0.006))
        all_colors = [HOOK_COLOR] + list(detail_colors)
        overlays   = []
        for idx, cap in enumerate(captions):
            color = all_colors[idx % len(all_colors)]
            sz    = hook_size if idx == 0 else font_size
            ov    = render_caption_overlay(
                cap, OUT_W, OUT_H, sz, pad_x, pad_y,
                color_rgb=color, font_path=font_path, logo_pil=logo_pil,
                align=caption_align,
            )
            overlays.append(ov)
        cta_overlay = None
        if cta_nama.strip() or cta_wa.strip():
            cta_overlay = render_cta_overlay(
                cta_nama.strip(), cta_wa.strip(),
                OUT_W, OUT_H, font_size, pad_x, pad_y,
                font_path=font_path, logo_pil=logo_pil,
                label=cta_label.strip() if cta_label.strip() else "",
            )
        st.write("📂 Membaca Pass 1...")
        p1_clip   = VideoFileClip(pass1_path)
        open_clips.append(p1_clip)
        total_dur = p1_clip.duration
        n_cap     = len(captions)
        interval  = total_dur / max(n_cap, 1)
        cta_start = max(0.0, total_dur - cta_dur)
        audio_src = p1_clip.audio
        schedule  = " | ".join([
            f"{i+1}. {i*interval:.0f}s–{(i+1)*interval:.0f}s"
            for i in range(n_cap)
        ])
        st.write(f"🕐 {schedule}")
        if bgm_file:
            try:
                with open(bgm_tmp, "wb") as f: f.write(bgm_file.read())
                bgm_created = True
                bgm_raw     = AudioFileClip(bgm_tmp)
                if bgm_raw.duration > total_dur:
                    bgm_raw = bgm_raw.subclipped(0, total_dur)
                fo_dur    = min(3.0, bgm_raw.duration * 0.3)
                bgm_audio = bgm_raw.with_effects([
                    AudioFadeOut(fo_dur), MultiplyVolume(bgm_volume),
                ])
                if audio_src is not None:
                    audio_src = audio_src.with_effects([MultiplyVolume(orig_vol)])
                mixed = [a for a in [audio_src, bgm_audio] if a is not None]
                if mixed:
                    audio_src = CompositeAudioClip(mixed)
                st.write(f"  ✅ BGM {bgm_raw.duration:.1f}s, fade-out {fo_dur:.1f}s")
            except Exception as e:
                st.warning(f"BGM gagal: {e}")
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
        st.write("🎬 Render Pass 2...")
        final_video = p1_clip.transform(pass2_proc)
        if audio_src is not None:
            final_video = final_video.with_audio(audio_src)
        final_video.write_videofile(
            out_path, codec="libx264", audio_codec="aac", fps=24,
            ffmpeg_params=["-pix_fmt", "yuv420p"], logger=None,
        )
        return True, captions, ""
    except Exception as e:
        return False, [], str(e)
    finally:
        for oc in open_clips:
            try: oc.close()
            except Exception: pass
        if bgm_created and os.path.exists(bgm_tmp):
            try: os.remove(bgm_tmp)
            except Exception: pass
        gc.collect()

# ─────────────────────────────────────────────────────────────────────────────
# HELPER — Smart Clip Cutter
# ─────────────────────────────────────────────────────────────────────────────
def smart_cut_clips(video_clips: list, target_dur: int,
                    min_seg: float = 4.0, max_seg: float = 6.0) -> list:
    pool = []
    for src_idx, vc in enumerate(video_clips):
        dur = vc.duration
        t   = 0.0
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

# ─────────────────────────────────────────────────────────────────────────────
# HELPER — Photo Slide builder  ✦ KEN BURNS EFFECT ✦
# ─────────────────────────────────────────────────────────────────────────────
def photo_to_clip(img_path: str, duration: float,
                  out_w: int, out_h: int) -> VideoClip:
    MAX_SCALE = 1.10
    img = Image.open(img_path).convert("RGB")
    iw, ih    = img.size
    src_ratio = iw / ih
    dst_ratio = out_w / out_h
    base_w = int(out_w * MAX_SCALE)
    base_h = int(out_h * MAX_SCALE)
    if abs(src_ratio - dst_ratio) < 0.05:
        base_frame = np.array(img.resize((base_w, base_h), Image.LANCZOS))
    else:
        scale_h  = base_h / ih
        bg_w_raw = max(base_w, int(iw * scale_h))
        bg_img   = img.resize((bg_w_raw, base_h), Image.LANCZOS)
        bg_img   = bg_img.filter(ImageFilter.GaussianBlur(radius=25))
        if bg_w_raw > base_w:
            x1     = (bg_w_raw - base_w) // 2
            bg_img = bg_img.crop((x1, 0, x1 + base_w, base_h))
        fg_h   = max(1, int(base_w / src_ratio))
        fg_img = img.resize((base_w, fg_h), Image.LANCZOS)
        fg_y0  = (base_h - fg_h) // 2
        canvas = bg_img.copy()
        canvas.paste(fg_img, (0, fg_y0))
        base_frame = np.array(canvas)
    base_frame = base_frame.astype(np.uint8)
    _bw, _bh   = base_w, base_h
    _ow, _oh   = out_w, out_h
    def make_frame(t: float) -> np.ndarray:
        progress = min(t / max(duration, 1e-6), 1.0)
        crop_w   = max(_ow, int(_bw - (_bw - _ow) * progress))
        crop_h   = max(_oh, int(_bh - (_bh - _oh) * progress))
        x1       = max(0, (_bw - crop_w) // 2)
        y1       = max(0, (_bh - crop_h) // 2)
        cropped  = base_frame[y1:y1+crop_h, x1:x1+crop_w]
        return np.array(
            Image.fromarray(cropped).resize((_ow, _oh), Image.BILINEAR)
        ).astype(np.uint8)
    return VideoClip(make_frame, duration=duration).with_fps(24)


def build_photo_slideshow(photo_paths: list, target_dur: int,
                           out_w: int, out_h: int,
                           fade_dur: float = 0.5) -> VideoClip:
    n      = len(photo_paths)
    per_ph = max(5.0, min(8.0, target_dur / n))
    clips  = [photo_to_clip(p, per_ph, out_w, out_h) for p in photo_paths]
    faded  = []
    for i, c in enumerate(clips):
        fx = []
        if i > 0:     fx.append(FadeIn(fade_dur))
        if i < n - 1: fx.append(FadeOut(fade_dur))
        faded.append(c.with_effects(fx) if fx else c)
    return concatenate_videoclips(faded, method="chain")

# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────────────────
_ss_defaults = {
    "pass1_ready"   : False,
    "pass1_path"    : "",
    "pass2_done"    : False,
    "out_path"      : "",
    "video_bytes"   : None,
    "p1_out_w"      : 720,
    "p1_out_h"      : 1280,
    "p1_logo_pil"   : None,
    "trim_segments" : [],
    "trim_approved" : False,
    "trim_open_vcs" : [],
    "input_mode"    : "video",
    "photo_paths"   : [],
    "trim_temp_raw" : [],
}
for k, v in _ss_defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ─────────────────────────────────────────────────────────────────────────────
# MAIN — TWO-PASS RENDER
# ─────────────────────────────────────────────────────────────────────────────
st.divider()

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

has_input = bool(video_files) or bool(photo_files)

col1, col2, col3 = st.columns([2, 2, 1])
with col1:
    btn_full = st.button(
        "🔍 Preview Trim & Siapkan",
        disabled=not has_input,
        use_container_width=True,
    )
with col2:
    btn_pass2 = st.button(
        "✍️ Re-render Pass 2 (caption saja)",
        disabled=not st.session_state.pass1_ready,
        use_container_width=True,
    )
with col3:
    btn_reset = st.button(
        "🗑️ Reset",
        use_container_width=True,
    )

if btn_reset:
    for vc in st.session_state.get("trim_open_vcs", []):
        try: vc.close()
        except: pass
    cleanup_session(SID)
    for key in list(_ss_defaults.keys()):
        if key in st.session_state:
            del st.session_state[key]
    st.success("🗑️ Session direset.")
    st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1 — PREVIEW TRIM
# ═══════════════════════════════════════════════════════════════════════════════
if btn_full and has_input:
    for vc in st.session_state.get("trim_open_vcs", []):
        try: vc.close()
        except: pass
    st.session_state.trim_segments = []
    st.session_state.trim_approved = False
    st.session_state.trim_open_vcs = []
    st.session_state.pass1_ready   = False
    st.session_state.pass2_done    = False
    st.session_state.video_bytes   = None
    st.session_state.input_mode    = input_mode

    if input_mode == "video":
        with st.status("🔍 Menganalisis video...", expanded=True) as status:
            open_vcs = []
            temp_raw = []
            try:
                SIZE_LIMIT_MB = 500
                raw_clips     = []
                for i, vf in enumerate(video_files):
                    # [LINUX] Simpan file temp ke /tmp
                    raw = _tmp(f"tmp_{SID}_raw_{i}.mp4")
                    fin = _tmp(f"tmp_{SID}_v_{i}.mp4")
                    with open(raw, "wb") as f: f.write(vf.read())
                    temp_raw += [raw, fin]
                    size_mb = os.path.getsize(raw) / (1024*1024)
                    if size_mb > SIZE_LIMIT_MB:
                        st.write(f"  ⚠️ Video {i+1}: {size_mb:.0f}MB → kompres...")
                        res = subprocess.run([
                            "ffmpeg", "-y", "-i", raw,
                            "-vf", "scale=720:-2",
                            "-vcodec", "libx264", "-crf", "28",
                            "-preset", "ultrafast",
                            "-acodec", "aac", "-b:a", "128k", fin,
                        ], capture_output=True, text=True)
                        if res.returncode != 0:
                            shutil.copy(raw, fin)
                        else:
                            st.write(f"  ✅ {size_mb:.0f}MB → {os.path.getsize(fin)/1024/1024:.0f}MB")
                    else:
                        shutil.copy(raw, fin)
                    vc = VideoFileClip(fin)
                    open_vcs.append(vc)
                    raw_clips.append(vc)
                    st.write(f"  📹 Video {i+1}: `{vf.name}` — {vc.duration:.1f}s")
                segments  = smart_cut_clips(raw_clips, durasi_target)
                fin_paths = [_tmp(f"tmp_{SID}_v_{i}.mp4") for i in range(len(video_files))]
                st.session_state.trim_segments = [
                    {"src_idx" : s["src_idx"],
                     "seg_idx" : s["seg_idx"],
                     "start"   : s["start"],
                     "end"     : s["end"],
                     "duration": s["duration"],
                     "src_name": video_files[s["src_idx"]].name,
                     "src_path": fin_paths[s["src_idx"]]}
                    for s in segments
                ]
                st.session_state.trim_open_vcs     = open_vcs
                st.session_state["trim_fin_paths"] = fin_paths
                st.session_state["trim_temp_raw"]  = temp_raw
                status.update(label=f"✅ {len(segments)} segmen siap di-preview", state="complete")
            except Exception as e:
                status.update(label=f"❌ {e}", state="error")
                st.exception(e)
                for vc in open_vcs:
                    try: vc.close()
                    except: pass
    else:
        with st.status("🖼️ Menyiapkan foto...", expanded=True) as status:
            photo_paths = []
            try:
                for i, pf in enumerate(photo_files[:6]):
                    # [LINUX] Simpan foto temp ke /tmp
                    p = _tmp(f"tmp_{SID}_photo_{i}{os.path.splitext(pf.name)[1]}")
                    with open(p, "wb") as f: f.write(pf.read())
                    photo_paths.append(p)
                    st.write(f"  🖼️ Foto {i+1}: `{pf.name}`")
                n     = len(photo_paths)
                per_s = max(5.0, min(8.0, durasi_target / n))
                segs  = [{"src_name": photo_files[i].name,
                          "seg_idx": i, "start": 0, "end": per_s,
                          "duration": per_s, "src_idx": i}
                         for i in range(n)]
                st.session_state.trim_segments  = segs
                st.session_state["photo_paths"] = photo_paths
                status.update(
                    label=f"✅ {n} foto — {per_s:.1f}s/slide · Ken Burns aktif 🎥",
                    state="complete",
                )
            except Exception as e:
                status.update(label=f"❌ {e}", state="error")
    st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2 — TAMPILKAN PREVIEW TRIM
# ═══════════════════════════════════════════════════════════════════════════════
def extract_thumb(src_path: str, t_sec: float, thumb_path: str) -> bool:
    try:
        res = subprocess.run([
            "ffmpeg", "-y",
            "-ss", str(round(t_sec, 2)),
            "-i", src_path,
            "-vframes", "1",
            "-vf", "scale=240:-1",
            "-q:v", "4",
            thumb_path,
        ], capture_output=True, text=True, timeout=10)
        return res.returncode == 0 and os.path.exists(thumb_path)
    except Exception:
        return False


def extract_mini_clip(src_path: str, start: float, end: float,
                      out_path: str) -> bool:
    try:
        res = subprocess.run([
            "ffmpeg", "-y",
            "-ss", str(round(start, 2)),
            "-i", src_path,
            "-t",  str(round(end - start, 2)),
            "-vf", "scale=360:-2",
            "-c:v", "libx264", "-crf", "28", "-preset", "ultrafast",
            "-an",
            "-movflags", "+faststart",
            out_path,
        ], capture_output=True, text=True, timeout=30)
        return res.returncode == 0 and os.path.exists(out_path)
    except Exception:
        return False


if st.session_state.trim_segments and not st.session_state.pass1_ready:
    segs = st.session_state.trim_segments
    mode = st.session_state.get("input_mode", "video")
    st.subheader("📋 Preview Segmen" if mode == "video" else "🖼️ Preview Urutan Foto")
    if mode == "photo":
        st.info("✨ Ken Burns Effect (slow zoom-in 100% → 110%) akan diterapkan saat render.")
    N_COLS = 3
    rows   = [segs[i:i+N_COLS] for i in range(0, len(segs), N_COLS)]
    for row in rows:
        cols = st.columns(N_COLS)
        for col, s in zip(cols, row):
            with col:
                if mode == "video":
                    src     = s.get("src_path", "")
                    idx     = s["seg_idx"]
                    # [LINUX] Thumbnail di /tmp
                    thumb_p = _tmp(f"tmp_{SID}_thumb_{idx}.jpg")
                    mini_p  = _tmp(f"tmp_{SID}_mini_{idx}.mp4")
                    if not os.path.exists(thumb_p):
                        extract_thumb(src, s["start"] + s["duration"] / 2, thumb_p)
                    if os.path.exists(thumb_p):
                        st.image(thumb_p, use_container_width=True)
                    else:
                        st.markdown("🎬")
                    st.caption("**#{}** {}  \n{:.1f}s – {:.1f}s · **{:.1f}s**".format(
                        idx + 1, s["src_name"][:16],
                        s["start"], s["end"], s["duration"]))
                    with st.expander("▶ Play clip"):
                        if not os.path.exists(mini_p):
                            with st.spinner("Memotong clip..."):
                                extract_mini_clip(src, s["start"], s["end"], mini_p)
                        if os.path.exists(mini_p):
                            st.video(mini_p)
                        else:
                            st.warning("Gagal memuat clip.")
                else:
                    photo_paths = st.session_state.get("photo_paths", [])
                    if s["src_idx"] < len(photo_paths):
                        st.image(photo_paths[s["src_idx"]], use_container_width=True)
                    st.caption("**Slide {}** {}  \n**{:.1f}s**/slide 🎥".format(
                        s["seg_idx"] + 1, s["src_name"][:16], s["duration"]))
    st.divider()
    total_seg = sum(s["duration"] for s in segs)
    st.info(
        f"📊 **{len(segs)} segmen** · total **{total_seg:.1f}s** "
        f"(target: {durasi_target}s)"
    )
    ca, cb = st.columns(2)
    btn_ok    = ca.button("✅ OK — Lanjut Render", use_container_width=True, type="primary")
    btn_retry = cb.button("🔄 Acak Ulang Urutan",  use_container_width=True)
    if btn_retry:
        random.shuffle(st.session_state.trim_segments)
        st.rerun()
    if btn_ok:
        st.session_state.trim_approved = True
        st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3 — RENDER PASS 1
# ═══════════════════════════════════════════════════════════════════════════════
if st.session_state.trim_approved and not st.session_state.pass1_ready:
    segs = st.session_state.trim_segments
    mode = st.session_state.get("input_mode", "video")
    # [LINUX] Pass 1 disimpan di /tmp (sementara), output final di folder output/
    pass1_path = _tmp(f"tmp_{SID}_pass1.mp4")
    out_path   = f"output/out_{SID}.mp4"

    with st.status("⏳ Pass 1: Render...", expanded=True) as status:
        open_clips = []
        try:
            if   "360p"     in resolusi: OUT_W, OUT_H = 202, 360
            elif "720p"     in resolusi: OUT_W, OUT_H = 720, 1280
            elif "Original" in resolusi: OUT_W, OUT_H = 720, 1280
            else:                        OUT_W, OUT_H = 1080, 1920
            st.write(f"📐 Resolusi: **{OUT_W}×{OUT_H}**")

            if mode == "video":
                stored_vcs = st.session_state.get("trim_open_vcs", [])
                clips_916  = []
                for s in segs:
                    vc  = stored_vcs[s["src_idx"]]
                    seg = vc.subclipped(s["start"], s["end"])
                    f16 = fit_to_916(seg, OUT_W, OUT_H)
                    clips_916.append(f16)
                    st.write(f"  ✂️ {s['src_name']} [{s['start']:.1f}–{s['end']:.1f}s]")
            else:
                photo_paths = st.session_state.get("photo_paths", [])
                st.write("🖼️ Membangun photo slideshow dengan Ken Burns Effect...")
                base_slide = build_photo_slideshow(
                    photo_paths, durasi_target, OUT_W, OUT_H, fade_dur=0.5)
                clips_916  = [base_slide]

            # ── Logo ────────────────────────────────────────────────────────────
            logo_pil = None
            if logo_file:
                # [LINUX] Logo temp di /tmp
                logo_tmp = _tmp(f"tmp_{SID}_logo.png")
                with open(logo_tmp, "wb") as f: f.write(logo_file.read())
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
                    out = frame.copy().astype(np.float32)
                    patch = out[ly:ly+logo_h, lx:lx+logo_w]
                    alpha = logo_np[:,:,3:] / 255.0
                    out[ly:ly+logo_h, lx:lx+logo_w] = (
                        patch*(1-alpha) + logo_np[:,:,:3]*alpha
                    )
                    return out.astype(np.uint8)
                clips_916 = [c.image_transform(add_logo) for c in clips_916]
                st.write("🖼️ Logo OK.")

            # ── Gabungkan dengan transisi ──────────────────────────────────────
            st.write("🔗 Menggabungkan...")
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

            # ── Render Pass 1 ──────────────────────────────────────────────────
            status.update(label="⏳ Rendering Pass 1...")
            st.write(f"💾 Render → `{pass1_path}`...")
            base.write_videofile(
                pass1_path, codec="libx264", audio_codec="aac", fps=24,
                ffmpeg_params=["-pix_fmt", "yuv420p"], logger=None,
            )
            try: base.close()
            except: pass
            for vc in st.session_state.get("trim_open_vcs", []):
                try: vc.close()
                except: pass
            st.session_state.trim_open_vcs = []
            gc.collect()

            st.session_state.pass1_ready = True
            st.session_state.pass1_path  = pass1_path
            st.session_state.p1_out_w    = OUT_W
            st.session_state.p1_out_h    = OUT_H
            st.session_state.p1_logo_pil = logo_pil
            st.write("✅ **Pass 1 selesai.**")

            # ── Lanjut Pass 2 ──────────────────────────────────────────────────
            status.update(label="⏳ Pass 2: Overlay caption...")
            st.write("## ✍️ Pass 2: Overlay Caption")
            ok, captions, err = run_pass2(
                pass1_path=pass1_path, out_path=out_path,
                deskripsi=deskripsi, n_caption=n_caption,
                detail_colors=detail_colors,
                cta_nama=cta_nama, cta_wa=cta_wa,
                cta_dur=cta_dur, cta_label=cta_label,
                do_grade=do_grade, brightness=brightness,
                contrast=contrast, saturation=saturation,
                sharpness=sharpness, bgm_file=bgm_file,
                bgm_volume=bgm_volume, orig_vol=orig_vol,
                OUT_W=OUT_W, OUT_H=OUT_H, logo_pil=logo_pil,
                caption_align=caption_align,
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
            gc.collect()

# ── RE-RENDER PASS 2 SAJA ─────────────────────────────────────────────────────
if btn_pass2 and st.session_state.pass1_ready:
    pass1_path = st.session_state.pass1_path
    out_path   = f"output/out_{SID}.mp4"
    OUT_W      = st.session_state.p1_out_w
    OUT_H      = st.session_state.p1_out_h
    logo_pil   = st.session_state.p1_logo_pil
    if not os.path.exists(pass1_path):
        st.error(f"❌ File Pass 1 `{pass1_path}` tidak ditemukan.")
    else:
        st.session_state.pass2_done  = False
        st.session_state.video_bytes = None
        with st.status("⏳ Re-render Pass 2...", expanded=True) as status:
            ok, captions, err = run_pass2(
                pass1_path=pass1_path, out_path=out_path,
                deskripsi=deskripsi, n_caption=n_caption,
                detail_colors=detail_colors,
                cta_nama=cta_nama, cta_wa=cta_wa,
                cta_dur=cta_dur, cta_label=cta_label,
                do_grade=do_grade, brightness=brightness,
                contrast=contrast, saturation=saturation,
                sharpness=sharpness, bgm_file=bgm_file,
                bgm_volume=bgm_volume, orig_vol=orig_vol,
                OUT_W=OUT_W, OUT_H=OUT_H, logo_pil=logo_pil,
                caption_align=caption_align,
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

# ── PREVIEW & DOWNLOAD ────────────────────────────────────────────────────────
if st.session_state.pass2_done and st.session_state.video_bytes:
    st.divider()
    st.subheader("🎬 Preview & Download")
    out_path = st.session_state.out_path
    if os.path.exists(out_path):
        st.video(out_path)
    col_a, col_b = st.columns([3, 1])
    with col_a:
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
    with col_b:
        if st.button("🔄 Perbaiki Caption", use_container_width=True):
            st.info("💡 Edit **Deskripsi** di sidebar → klik **✍️ Re-render Pass 2**")
    st.caption(
        "💡 Caption salah? Edit deskripsi di sidebar → "
        "**✍️ Re-render Pass 2** (Pass 1 tidak diulang)"
    )