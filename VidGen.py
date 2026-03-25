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

_project_dir = os.path.dirname(os.path.abspath(__file__))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

for _sub in ["lib", "Lib", "site-packages",
             os.path.join("lib", "python3", "site-packages"),
             os.path.join("Lib", "site-packages")]:
    _p = os.path.join(_project_dir, _sub)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

NLP_ENGINE = "builtin"

try:
    import nltk
    _nltk_local = os.path.join(_project_dir, "nltk_data")
    if os.path.isdir(_nltk_local) and _nltk_local not in nltk.data.path:
        nltk.data.path.insert(0, _nltk_local)
    from nltk.tokenize import sent_tokenize
    try:
        sent_tokenize("test sentence.")
        NLP_ENGINE = "nltk"
    except LookupError:
        nltk.download("punkt",     download_dir=_nltk_local, quiet=True)
        nltk.download("punkt_tab", download_dir=_nltk_local, quiet=True)
        nltk.data.path.insert(0, _nltk_local)
        sent_tokenize("test sentence.")
        NLP_ENGINE = "nltk"
except (ImportError, Exception):
    try:
        from textblob import TextBlob
        TextBlob("test").sentences
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
HOOK_COLOR   = (255, 215, 0)
STROKE_COLOR = (0, 0, 0)
STROKE_W     = 2

# ── Garis vertikal Gold untuk align Left / Right ──────────────────────────────
VERT_LINE_W     = 6              # lebar garis (px), antara 5–8
VERT_LINE_GAP   = 10             # jarak garis ke teks (px)
VERT_LINE_COLOR = (255, 215, 0)  # Gold

# ── Safe zone TikTok / Reels (9:16) ──────────────────────────────────────────
CAPTION_Y    = 0.52
CTA_Y        = 0.66
SAFE_BOTTOM  = 0.78

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Mansion Video Generator", layout="centered")
st.title("🎬 Mansion Video Generator")
st.caption("Aplikasi membuat video Konten Sosial Media dalam Format Portrait")

# ─── SESSION ID ───────────────────────────────────────────────────────────────
if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex[:8]
SID = st.session_state.session_id
st.caption(f"🔑 Session: `{SID}`")

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS — Font
# ─────────────────────────────────────────────────────────────────────────────
_WIN_FONT_LABELS = {
    "ariblk.ttf"   : "Arial Black",
    "ARIBLK.TTF"   : "Arial Black",
    "impact.ttf"   : "Impact",
    "Impact.ttf"   : "Impact",
    "arialbd.ttf"  : "Arial Bold",
    "ariali.ttf"   : "Arial Italic",
    "arial.ttf"    : "Arial",
    "verdanab.ttf" : "Verdana Bold",
    "verdana.ttf"  : "Verdana",
    "calibrib.ttf" : "Calibri Bold",
    "calibri.ttf"  : "Calibri",
    "trebucbd.ttf" : "Trebuchet Bold",
    "trebuc.ttf"   : "Trebuchet",
    "segoeuib.ttf" : "Segoe UI Bold",
    "segoeui.ttf"  : "Segoe UI",
    "timesbd.ttf"  : "Times New Roman Bold",
    "times.ttf"    : "Times New Roman",
    "consolab.ttf" : "Consolas Bold",
    "consola.ttf"  : "Consolas",
    "georgiabd.ttf": "Georgia Bold",
    "georgia.ttf"  : "Georgia",
    "Roboto-Black.ttf"        : "Roboto Black",
    "RobotoCondensed-Bold.ttf": "Roboto Condensed Bold",
    "DejaVuSans-Bold.ttf"     : "DejaVu Sans Bold",
    "LiberationSans-Bold.ttf" : "Liberation Sans Bold",
    "FreeSansBold.ttf"        : "Free Sans Bold",
}

_SYSTEM_FONT_PATHS = [
    "C:/Windows/Fonts/ariblk.ttf",
    "C:/Windows/Fonts/ARIBLK.TTF",
    "C:/Windows/Fonts/impact.ttf",
    "C:/Windows/Fonts/Impact.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/verdanab.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
    "C:/Windows/Fonts/trebucbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/timesbd.ttf",
    "C:/Windows/Fonts/consolab.ttf",
    "C:/Windows/Fonts/georgiabd.ttf",
    "/usr/share/fonts/truetype/roboto/Roboto-Black.ttf",
    "/usr/share/fonts/truetype/roboto/RobotoCondensed-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def scan_available_fonts() -> list[dict]:
    found = []
    seen_paths = set()

    def add(path: str, label: str):
        p = os.path.normpath(path)
        if p not in seen_paths and os.path.exists(p):
            seen_paths.add(p)
            found.append({"label": label, "path": p})

    for ext in ("*.ttf", "*.TTF", "*.otf", "*.OTF"):
        for fp in glob.glob(os.path.join("assets", ext)):
            fname = os.path.basename(fp)
            label = os.path.splitext(fname)[0].replace("_", " ").replace("-", " ").title()
            label = f"📁 {label}"
            add(fp, label)

    for fp in _SYSTEM_FONT_PATHS:
        fname = os.path.basename(fp)
        label = _WIN_FONT_LABELS.get(fname, os.path.splitext(fname)[0])
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
        st.sidebar.warning("Tidak ada font TTF. Taruh file .ttf di folder assets/ untuk font custom.")
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
        st.warning("Tidak ada font. Taruh file .ttf di folder assets/ lalu refresh.")

    # ── Caption Alignment ─────────────────────────────────────────────────────
    caption_align = st.selectbox(
        "Caption Align",
        options=["Center", "Left", "Right"],
        index=0,
        help=(
            "Center : teks di tengah (gaya lama, tanpa garis).\n"
            "Left   : teks rata kiri + garis vertikal Gold di sisi kiri.\n"
            "Right  : teks rata kanan + garis vertikal Gold di sisi kanan."
        ),
    )

    st.caption(
        "💡 Tambah font: copy file `.ttf` ke folder `assets/` "
        "→ otomatis muncul di daftar ini."
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

    st.divider()
    st.header("🤖 Director AI")
    director_prompt = st.text_area(
        "Instruksi gaya video",
        placeholder=(
            "Contoh: Buat video properti modern elegan, hook kuat dari "
            "eksterior terbaik, interior di tengah, tutup dengan view lokasi. "
            "Tone hangat dan premium, target TikTok & Instagram."
        ),
        height=110,
        help="AI mengatur urutan klip, durasi, transisi, dan color grade otomatis.",
    )
    anthropic_key = st.text_input(
        "Anthropic API Key",
        type="password",
        placeholder="sk-ant-...",
        help="Diperlukan untuk mengaktifkan AI Director.",
    )
    use_ai_director = bool(director_prompt.strip() and anthropic_key.strip())
    if use_ai_director:
        st.caption("✅ AI Director aktif")
    elif director_prompt.strip():
        st.warning("⚠️ Isi API Key untuk aktifkan AI")


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
    st.caption("Upload foto (maks 6). **Ken Burns Effect** (slow zoom-in) diterapkan otomatis pada setiap foto.")
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
    """Hapus tanda baca penutup kalimat (. ! ?) di akhir teks."""
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
    hook      = sentences[0].upper()
    rest      = sentences[1:]

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
            end   = int((i + 1) * bucket)
            end   = max(end, start + 1)
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
    """
    Render caption overlay RGBA.

    align = "Center"  → teks di tengah, tanpa garis vertikal (perilaku lama)
    align = "Left"    → teks rata kiri  + garis vertikal Gold di sisi KIRI teks
    align = "Right"   → teks rata kanan + garis vertikal Gold di sisi KANAN teks

    Garis vertikal:
      - Lebar  : VERT_LINE_W px (6 px default)
      - Tinggi : mengikuti total tinggi blok teks
      - Warna  : Gold (255, 215, 0)
    """
    canvas = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)

    if text.strip():
        # Ruang untuk garis vertikal hanya berlaku di Left / Right
        line_margin = (VERT_LINE_W + VERT_LINE_GAP) if align != "Center" else 0
        box_w  = max(1, out_w - pad_x * 2)
        usable = max(1, box_w - line_margin - 8)

        font, lines = fit_and_wrap(text, usable, font_path, start_size, max_lines)

        line_h   = max(1, draw.textbbox((0, 0), "Ag", font=font)[3])
        line_gap = max(2, int(line_h * 0.10))
        total_h  = line_h * len(lines) + line_gap * (len(lines) - 1)

        # ── Posisi vertikal blok ──────────────────────────────────────────────
        safe_bottom_px = int(out_h * SAFE_BOTTOM)
        ty_block = int(out_h * CAPTION_Y)
        if ty_block + total_h > safe_bottom_px:
            ty_block = max(0, safe_bottom_px - total_h - pad_y)

        # ── Gambar garis vertikal Gold (Left / Right) ─────────────────────────
        if align == "Left":
            # Garis di sisi kiri, teks mulai setelah garis + gap
            gx0 = pad_x
            gx1 = pad_x + VERT_LINE_W
            draw.rectangle(
                [gx0, ty_block, gx1, ty_block + total_h],
                fill=(*VERT_LINE_COLOR, 255),
            )
            text_x_anchor = gx1 + VERT_LINE_GAP   # x awal teks

        elif align == "Right":
            # Garis di sisi kanan, teks berakhir sebelum garis
            gx1 = out_w - pad_x
            gx0 = gx1 - VERT_LINE_W
            draw.rectangle(
                [gx0, ty_block, gx1, ty_block + total_h],
                fill=(*VERT_LINE_COLOR, 255),
            )
            text_x_end = gx0 - VERT_LINE_GAP       # x akhir teks (kanan)

        # ── Gambar baris teks ─────────────────────────────────────────────────
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
                tx = text_x_end - lw
                tx = max(pad_x, tx)

            else:  # Center
                tx = pad_x + (box_w - lw) // 2
                tx = max(pad_x, tx)

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

        line_gap    = max(4, pad_y)
        total_txt_h = sum(r[4] for r in rendered) + line_gap * (len(rendered)-1)

        safe_bottom_px = int(out_h * SAFE_BOTTOM)
        x_left      = pad_x
        gold_line_h = max(2, int(out_h * 0.003))
        block_total = total_txt_h + gold_line_h + pad_y * 3
        y_top = int(out_h * CTA_Y)
        if y_top + block_total > safe_bottom_px:
            y_top = max(0, safe_bottom_px - block_total)

        draw.rectangle([x_left, y_top,
                        x_left + box_w, y_top + gold_line_h],
                       fill=(255, 215, 0, 255))
        y_top = y_top + gold_line_h + pad_y

        cur_y = y_top
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
    result = frame.copy()
    bar_w  = int(out_w * min(max(t/total_dur, 0), 1))
    bar_y0 = max(0, out_h - bar_h)
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
# HELPER — Pass 2
# ─────────────────────────────────────────────────────────────────────────────
def run_pass2(pass1_path, out_path, deskripsi, n_caption, detail_colors,
              cta_nama, cta_wa, cta_dur, cta_label, do_grade, brightness, contrast,
              saturation, sharpness, bgm_file, bgm_volume, orig_vol,
              OUT_W, OUT_H, logo_pil,
              caption_align="Center"):
    """
    Pass 2: overlay caption + CTA + grading → simpan ke out_path.
    Return: (success: bool, captions: list, error: str)
    """
    open_clips  = []
    bgm_tmp     = f"tmp_{SID}_bgm.mp3"
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

        with st.expander("📋 Preview Caption (klik untuk lihat/sembunyikan)", expanded=True):
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

        # ── Pre-render caption overlays ────────────────────────────────────────
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

        schedule = " | ".join([
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
    """
    Buat VideoClip dari satu foto dengan Ken Burns Effect (Slow Zoom-In).

    Mekanisme:
      1. Foto di-render ke base_frame berukuran (out_w * MAX_SCALE) × (out_h * MAX_SCALE)
         menggunakan logika fit-to-9:16 yang sama seperti sebelumnya.
      2. Tiap frame (t):
           progress = t / duration  (0 → 1)
           crop_w   = base_w → out_w   (semakin kecil = zoom makin besar)
           crop_h   = base_h → out_h
         Crop area tengah, lalu resize ke (out_w × out_h).
      3. Hasilnya: foto bergerak perlahan dari skala 100% → 110% selama durasi.
    """
    MAX_SCALE = 1.10   # zoom akhir 110%

    img = Image.open(img_path).convert("RGB")
    iw, ih    = img.size
    src_ratio = iw / ih
    dst_ratio = out_w / out_h

    # ── Render base frame pada ukuran MAX_SCALE ────────────────────────────────
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
    _bw, _bh   = base_w, base_h   # capture untuk closure
    _ow, _oh   = out_w, out_h

    def make_frame(t: float) -> np.ndarray:
        progress = min(t / max(duration, 1e-6), 1.0)
        # Crop mengecil seiring waktu → objek tampak membesar (zoom-in)
        crop_w = max(_ow, int(_bw - (_bw - _ow) * progress))
        crop_h = max(_oh, int(_bh - (_bh - _oh) * progress))
        x1 = max(0, (_bw - crop_w) // 2)
        y1 = max(0, (_bh - crop_h) // 2)
        cropped = base_frame[y1:y1+crop_h, x1:x1+crop_w]
        # BILINEAR lebih cepat dari LANCZOS; cukup untuk video zoom halus
        return np.array(
            Image.fromarray(cropped).resize((_ow, _oh), Image.BILINEAR)
        ).astype(np.uint8)

    return VideoClip(make_frame, duration=duration).with_fps(24)


def build_photo_slideshow(photo_paths: list, target_dur: int,
                           out_w: int, out_h: int,
                           fade_dur: float = 0.5) -> VideoClip:
    n      = len(photo_paths)
    per_ph = max(5.0, min(8.0, target_dur / n))

    clips = [photo_to_clip(p, per_ph, out_w, out_h) for p in photo_paths]

    faded = []
    for i, c in enumerate(clips):
        fx = []
        if i > 0:     fx.append(FadeIn(fade_dur))
        if i < n - 1: fx.append(FadeOut(fade_dur))
        faded.append(c.with_effects(fx) if fx else c)

    return concatenate_videoclips(faded, method="chain")


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS — Scene Scoring (ffmpeg + numpy, zero new deps)
# ─────────────────────────────────────────────────────────────────────────────
def _laplacian_var(arr: np.ndarray) -> float:
    """Variance of Laplacian approximation — higher = sharper."""
    lap = (
        -4.0 * arr[1:-1, 1:-1]
        + arr[:-2, 1:-1] + arr[2:,  1:-1]
        + arr[1:-1, :-2] + arr[1:-1, 2:]
    )
    return float(np.var(lap))


def score_segment(src_path: str, start: float, end: float,
                  sid: str, seg_idx: int) -> dict:
    """
    Score a video segment by sampling 2 frames via ffmpeg.
    Returns: {blur, brightness, composite (0–1)}
    Higher composite = better quality clip.
    """
    dur  = max(1.0, end - start)
    raw_scores = []
    for qi, frac in enumerate([0.25, 0.75]):
        qt = start + dur * frac
        tp = f"tmp_{sid}_qs_{seg_idx}_{qi}.jpg"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{qt:.2f}", "-i", src_path,
                 "-vframes", "1", "-vf", "scale=160:-1", "-q:v", "5", tp],
                capture_output=True, timeout=8,
            )
            if os.path.exists(tp):
                arr  = np.array(Image.open(tp).convert("L"), dtype=np.float32)
                raw_scores.append({
                    "blur": _laplacian_var(arr),
                    "br"  : float(np.mean(arr)),
                })
                try: os.remove(tp)
                except Exception: pass
        except Exception:
            pass

    if not raw_scores:
        return {"blur": 0.0, "brightness": 128.0, "composite": 0.5}

    avg_blur = float(np.mean([s["blur"] for s in raw_scores]))
    avg_br   = float(np.mean([s["br"]   for s in raw_scores]))
    blur_n   = min(1.0, avg_blur / 600.0)
    br_n     = 1.0 - abs(avg_br - 135.0) / 135.0
    composite = blur_n * 0.65 + max(0.0, br_n) * 0.35
    return {
        "blur"      : round(avg_blur, 1),
        "brightness": round(avg_br, 1),
        "composite" : round(min(1.0, max(0.0, composite)), 3),
    }


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS — AI Director (Claude API)
# ─────────────────────────────────────────────────────────────────────────────
def parse_prompt_to_render_plan(
    prompt: str,
    segments: list,
    captions: list,
    api_key: str,
    durasi_target: int = 30,
) -> dict:
    """
    Call Claude API to produce a render plan from a director prompt.
    Returns dict: segment_order, hook_duration, detail_duration,
                  transition, color_grade, reasoning.
    """
    try:
        import anthropic, json

        client   = anthropic.Anthropic(api_key=api_key)
        segs_txt = "\n".join([
            f"  [{i}] {s['src_name']} "
            f"[{s['start']:.1f}s–{s['end']:.1f}s · {s['duration']:.1f}s] "
            f"skor={s.get('score', {}).get('composite', 0.5):.2f}"
            for i, s in enumerate(segments)
        ])
        caps_txt = "\n".join([
            f"  Caption {i+1}: {c}" for i, c in enumerate(captions)
        ])

        msg = f"""Kamu adalah direktur video properti profesional untuk konten TikTok & Instagram.

Instruksi user:
{prompt}

Segmen video tersedia ({len(segments)} segmen, skor 0–1 = kualitas visual):
{segs_txt}

Caption yang akan dipakai (dari input user, jangan diubah):
{caps_txt}

Target durasi: {durasi_target} detik (maksimum 60 detik).

Aturan:
- Segmen skor tinggi (≥0.6) → prioritas depan / posisi kunci
- Segmen skor rendah (<0.3) → taruh di tengah atau skip jika terlalu banyak
- hook_duration: 5–8 detik (klip pertama, kesan pertama paling penting)
- detail_duration: 3–6 detik
- Sesuaikan color grade dengan tone instruksi
- Total durasi: sum(hook + detail × (n-1)) ≤ {durasi_target} detik

Balas HANYA JSON valid ini, tanpa teks lain:
{{
  "segment_order": [indeks 0-based sesuai urutan render],
  "hook_duration": 6.0,
  "detail_duration": 4.0,
  "transition": "Crossfade",
  "color_grade": {{
    "aktif": true,
    "brightness": 1.05,
    "contrast": 1.15,
    "saturation": 1.10,
    "sharpness": 1.20
  }},
  "reasoning": "penjelasan singkat max 1 kalimat"
}}"""

        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": msg}],
        )
        text = resp.content[0].text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.split("```")[0].strip()

        plan  = json.loads(text)
        n     = len(segments)
        order = [i for i in plan.get("segment_order", []) if isinstance(i, int) and 0 <= i < n]
        for i in range(n):
            if i not in order:
                order.append(i)
        plan["segment_order"] = order
        return plan

    except Exception as e:
        return {"error": str(e)}


def apply_render_plan_to_segments(segments: list, plan: dict,
                                   max_dur: int = 60) -> list:
    """
    Reorder segments + adjust clip durations based on render plan.
    Trims total duration to max_dur seconds.
    """
    order      = plan.get("segment_order", list(range(len(segments))))
    hook_dur   = float(plan.get("hook_duration",   6.0))
    detail_dur = float(plan.get("detail_duration", 4.0))

    reordered = []
    for rank, idx in enumerate(order):
        if idx >= len(segments):
            continue
        s    = dict(segments[idx])
        want = hook_dur if rank == 0 else detail_dur
        avail = s["end"] - s["start"]
        actual = min(want, avail)
        s["end"]      = round(s["start"] + actual, 2)
        s["duration"] = round(actual, 2)
        s["seg_idx"]  = rank
        reordered.append(s)

    total, trimmed = 0.0, []
    for s in reordered:
        if total >= max_dur:
            break
        remaining = max_dur - total
        if s["duration"] > remaining:
            s = dict(s)
            s["end"]      = round(s["start"] + remaining, 2)
            s["duration"] = round(remaining, 2)
        trimmed.append(s)
        total += s["duration"]
    return trimmed


# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────────────────
if "pass1_ready"   not in st.session_state: st.session_state.pass1_ready   = False
if "pass1_path"    not in st.session_state: st.session_state.pass1_path    = ""
if "pass2_done"    not in st.session_state: st.session_state.pass2_done    = False
if "out_path"      not in st.session_state: st.session_state.out_path      = ""
if "video_bytes"   not in st.session_state: st.session_state.video_bytes   = None
if "p1_out_w"      not in st.session_state: st.session_state.p1_out_w      = 720
if "p1_out_h"      not in st.session_state: st.session_state.p1_out_h      = 1280
if "p1_logo_pil"   not in st.session_state: st.session_state.p1_logo_pil   = None
if "trim_segments" not in st.session_state: st.session_state.trim_segments = []
if "trim_approved" not in st.session_state: st.session_state.trim_approved = False
if "trim_open_vcs" not in st.session_state: st.session_state.trim_open_vcs = []
if "input_mode"    not in st.session_state: st.session_state.input_mode    = "video"
if "photo_paths"   not in st.session_state: st.session_state.photo_paths   = []
if "trim_temp_raw" not in st.session_state: st.session_state.trim_temp_raw = []
if "render_plan"   not in st.session_state: st.session_state.render_plan   = {}


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
        help="Analisis clip / foto, tampilkan preview sebelum render",
    )
with col2:
    btn_pass2 = st.button(
        "✍️ Re-render Pass 2 (caption saja)",
        disabled=not st.session_state.pass1_ready,
        use_container_width=True,
        help="Pakai video Pass 1 yang sudah ada, hanya render ulang caption/teks",
    )
with col3:
    btn_reset = st.button(
        "🗑️ Reset",
        use_container_width=True,
        help="Hapus semua file session ini dan mulai dari nol",
    )

if btn_reset:
    for vc in st.session_state.get("trim_open_vcs", []):
        try: vc.close()
        except: pass
    cleanup_session(SID)
    for key in ["pass1_ready", "pass1_path", "pass2_done", "out_path",
                "video_bytes", "p1_out_w", "p1_out_h", "p1_logo_pil",
                "trim_segments", "trim_approved", "trim_open_vcs", "input_mode"]:
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
    st.session_state.render_plan   = {}

    if input_mode == "video":
        with st.status("🔍 Menganalisis video...", expanded=True) as status:
            open_vcs = []
            temp_raw = []
            try:
                SIZE_LIMIT_MB = 500
                raw_clips = []
                for i, vf in enumerate(video_files):
                    raw = f"tmp_{SID}_raw_{i}.mp4"
                    fin = f"tmp_{SID}_v_{i}.mp4"
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
                fin_paths = [f"tmp_{SID}_v_{i}.mp4" for i in range(len(video_files))]
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

                # ── Score kualitas visual tiap segmen ─────────────────────────
                st.write("🔍 Scoring kualitas visual segmen...")
                scored_segs = []
                for seg in st.session_state.trim_segments:
                    sc  = score_segment(
                        seg["src_path"], seg["start"], seg["end"],
                        SID, seg["seg_idx"],
                    )
                    seg = dict(seg)
                    seg["score"] = sc
                    scored_segs.append(seg)
                st.session_state.trim_segments = scored_segs

                # ── AI Director (jika prompt + API key diisi) ─────────────────
                if use_ai_director:
                    st.write("🤖 AI Director menganalisis...")
                    preview_caps = split_description_to_captions(deskripsi, n_caption)
                    plan = parse_prompt_to_render_plan(
                        director_prompt, scored_segs, preview_caps,
                        anthropic_key, durasi_target,
                    )
                    if "error" in plan:
                        st.warning(f"⚠️ AI Director gagal: {plan['error']}. Pakai urutan default.")
                        st.session_state.render_plan = {}
                    else:
                        st.session_state.render_plan   = plan
                        st.session_state.trim_segments = apply_render_plan_to_segments(
                            scored_segs, plan, durasi_target,
                        )
                        st.write(f"✅ AI: _{plan.get('reasoning', 'Render plan diterapkan.')}_")
                else:
                    st.session_state.render_plan = {}

                status.update(label=f"✅ {len(st.session_state.trim_segments)} segmen siap di-preview", state="complete")
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
                    p = f"tmp_{SID}_photo_{i}{os.path.splitext(pf.name)[1]}"
                    with open(p, "wb") as f: f.write(pf.read())
                    photo_paths.append(p)
                    st.write(f"  🖼️ Foto {i+1}: `{pf.name}`")

                n     = len(photo_paths)
                per_s = max(5.0, min(8.0, durasi_target / n))
                segs  = [{"src_name": photo_files[i].name,
                          "seg_idx": i, "start": 0, "end": per_s,
                          "duration": per_s, "src_idx": i}
                         for i in range(n)]
                st.session_state.trim_segments   = segs
                st.session_state["photo_paths"]  = photo_paths
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

    # ── Tampilkan render plan AI jika ada ─────────────────────────────────────
    _rp = st.session_state.get("render_plan", {})
    if _rp and not _rp.get("error"):
        st.info(
            f"🤖 **AI Director** · Transisi: `{_rp.get('transition','—')}` · "
            f"Hook: `{_rp.get('hook_duration','—')}s` · "
            f"Detail: `{_rp.get('detail_duration','—')}s`  \n"
            f"_{_rp.get('reasoning','')}_"
        )

    N_COLS = 3
    indexed = list(enumerate(segs))
    rows    = [indexed[i:i+N_COLS] for i in range(0, len(indexed), N_COLS)]

    for row in rows:
        cols = st.columns(N_COLS)
        for col, (pos, s) in zip(cols, row):
            with col:
                if mode == "video":
                    src     = s.get("src_path", "")
                    idx     = s["seg_idx"]
                    thumb_p = f"tmp_{SID}_thumb_{idx}.jpg"
                    mini_p  = f"tmp_{SID}_mini_{idx}.mp4"

                    if not os.path.exists(thumb_p):
                        extract_thumb(src, s["start"] + s["duration"] / 2, thumb_p)
                    if os.path.exists(thumb_p):
                        st.image(thumb_p, use_container_width=True)
                    else:
                        st.markdown("🎬")

                    # Score badge
                    sc = s.get("score", {})
                    if sc:
                        cv = sc.get("composite", 0.5)
                        em = "🟢" if cv >= 0.6 else "🟡" if cv >= 0.35 else "🔴"
                        st.caption(f"{em} Skor: **{cv:.2f}**")

                    st.caption("**#{}** {}  \n{:.1f}s – {:.1f}s · **{:.1f}s**".format(
                        pos + 1, s["src_name"][:16],
                        s["start"], s["end"], s["duration"]))

                    # Reorder buttons
                    rb1, rb2 = st.columns(2)
                    if rb1.button("▲", key=f"up_{pos}",
                                  use_container_width=True, disabled=(pos == 0)):
                        sl = list(st.session_state.trim_segments)
                        sl[pos], sl[pos - 1] = sl[pos - 1], sl[pos]
                        st.session_state.trim_segments = sl
                        st.rerun()
                    if rb2.button("▼", key=f"dn_{pos}",
                                  use_container_width=True,
                                  disabled=(pos == len(segs) - 1)):
                        sl = list(st.session_state.trim_segments)
                        sl[pos], sl[pos + 1] = sl[pos + 1], sl[pos]
                        st.session_state.trim_segments = sl
                        st.rerun()

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
    segs       = st.session_state.trim_segments
    mode       = st.session_state.get("input_mode", "video")
    pass1_path = f"tmp_{SID}_pass1.mp4"
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

            # ── Logo ──────────────────────────────────────────────────────────
            logo_pil = None
            if logo_file:
                logo_tmp = f"tmp_{SID}_logo.png"
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
                    out[ly:ly+logo_h, lx:lx+logo_w] = (patch*(1-alpha)+logo_np[:,:,:3]*alpha)
                    return out.astype(np.uint8)

                clips_916 = [c.image_transform(add_logo) for c in clips_916]
                st.write("🖼️ Logo OK.")

            # ── Gabungkan dengan transisi ──────────────────────────────────────
            st.write("🔗 Menggabungkan...")
            _rp_trans = st.session_state.get("render_plan", {}).get("transition", "")
            effective_transition = _rp_trans if _rp_trans else jenis_transisi
            if _rp_trans:
                st.write(f"  🤖 Transisi dari AI: **{effective_transition}**")
            if len(clips_916) == 1:
                base = clips_916[0]
            elif effective_transition == "Crossfade":
                base = crossfade_concat(clips_916, fade_d=fade_dur)
            elif effective_transition == "Fade to Black":
                faded = []
                for i, c in enumerate(clips_916):
                    fx = ([] if i == 0 else [FadeIn(fade_dur)]) + [FadeOut(fade_dur)]
                    faded.append(c.with_effects(fx))
                base = concatenate_videoclips(faded, method="chain")
            else:
                base = concatenate_videoclips(clips_916, method="chain")

            # ── Render Pass 1 ─────────────────────────────────────────────────
            status.update(label="⏳ Rendering Pass 1...")
            st.write(f"💾 Render → `{pass1_path}`...")
            base.write_videofile(
                pass1_path,
                codec="libx264", audio_codec="aac", fps=24,
                ffmpeg_params=["-pix_fmt", "yuv420p"],
                logger=None,
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

            # ── Lanjut Pass 2 ─────────────────────────────────────────────────
            status.update(label="⏳ Pass 2: Overlay caption...")
            st.write("## ✍️ Pass 2: Overlay Caption")
            # ── Terapkan color grade dari render plan (jika ada) ──────────────
            _rp_cg = st.session_state.get("render_plan", {}).get("color_grade", {})
            eff_do_grade   = bool(_rp_cg.get("aktif",     do_grade))    if _rp_cg else do_grade
            eff_brightness = float(_rp_cg.get("brightness", brightness)) if _rp_cg else brightness
            eff_contrast   = float(_rp_cg.get("contrast",   contrast))   if _rp_cg else contrast
            eff_saturation = float(_rp_cg.get("saturation", saturation)) if _rp_cg else saturation
            eff_sharpness  = float(_rp_cg.get("sharpness",  sharpness))  if _rp_cg else sharpness
            if _rp_cg:
                st.write(
                    f"  🤖 Color grade dari AI: "
                    f"br={eff_brightness:.2f} co={eff_contrast:.2f} "
                    f"sa={eff_saturation:.2f} sh={eff_sharpness:.2f}"
                )

            ok, captions, err = run_pass2(
                pass1_path=pass1_path, out_path=out_path,
                deskripsi=deskripsi, n_caption=n_caption,
                detail_colors=detail_colors,
                cta_nama=cta_nama, cta_wa=cta_wa,
                cta_dur=cta_dur, cta_label=cta_label,
                do_grade=eff_do_grade, brightness=eff_brightness,
                contrast=eff_contrast, saturation=eff_saturation,
                sharpness=eff_sharpness, bgm_file=bgm_file,
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
            file_name=f"mansion_{SID}_{st.session_state.p1_out_w}x{st.session_state.p1_out_h}.mp4",
            mime="video/mp4",
            use_container_width=True,
        )
    with col_b:
        if st.button("🔄 Perbaiki Caption", use_container_width=True):
            st.info("💡 Edit **Deskripsi** di sidebar → klik **✍️ Re-render Pass 2**")
    st.caption(
        f"💡 Caption salah? Edit deskripsi di sidebar → **✍️ Re-render Pass 2** "
        f"(Pass 1 tidak diulang)"
    )