"""
╔══════════════════════════════════════════════════════════════════════════════╗
║          Mansion Video Generator  —  Two-Pass Rendering                     ║
║          Versi Final · Linux / Streamlit Cloud Ready                        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Pass 1 : Clip mentah + Logo  →  /tmp/tmp_{SID}_pass1.mp4                  ║
║  Pass 2 : Pass1 + Caption + CTA + Progress Bar  →  output/out_{SID}.mp4    ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Struktur repo GitHub:                                                      ║
║    /fonts   — file .ttf (upload ke GitHub)                                  ║
║    /assets  — logo, backup font (opsional)                                  ║
║    /output  — video hasil render (dibuat otomatis)                          ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 1 — IMPORTS
# ═══════════════════════════════════════════════════════════════════════════════
import os, sys, gc, glob, time, uuid, random, shutil, subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

# ── NLTK: unduh data bahasa sebelum import lain ──────────────────────────────
import nltk
for _pkg in ["punkt", "punkt_tab", "averaged_perceptron_tagger", "stopwords"]:
    try:
        nltk.download(_pkg, quiet=True)
    except Exception:
        pass

# ── MoviePy ──────────────────────────────────────────────────────────────────
from moviepy import (
    VideoFileClip, AudioFileClip,
    VideoClip, concatenate_videoclips, CompositeAudioClip,
)
from moviepy.video.fx import Crop, FadeIn, FadeOut
from moviepy.audio.fx import AudioFadeOut, MultiplyVolume

# ── [Linux] ImageMagick untuk TextClip MoviePy ───────────────────────────────
try:
    from moviepy.config import change_settings
    change_settings({"IMAGEMAGICK_BINARY": "/usr/bin/convert"})
except Exception:
    pass

# ── Streamlit (HARUS setelah semua logic agar set_page_config tidak tabrakan) ─
import streamlit as st


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 2 — STORAGE MANAGEMENT  (HARUS DI ATAS sebelum dipanggil)
# ═══════════════════════════════════════════════════════════════════════════════
TMP_DIR          = "/tmp"
_MAX_AGE_SECONDS = 30 * 60   # 30 menit


def _tmp(filename: str) -> str:
    """Buat path absolut di /tmp."""
    return os.path.join(TMP_DIR, filename)


def _safe_remove(filepath: str) -> bool:
    """
    Hapus file dengan aman. Tidak pernah raise Exception.
    Return True jika berhasil, False jika terkunci / tidak ada.
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
    Pindai /tmp dan output/, hapus file sampah > max_age detik.
    File sesi AKTIF (< 30 mnt) dan file terkunci TIDAK tersentuh.
    """
    now     = time.time()
    scanned = deleted = skipped = 0
    freed_b = 0
    for pattern in [os.path.join(tmp_dir, "tmp_*"),
                    os.path.join(output_dir, "out_*.mp4")]:
        for fp in glob.glob(pattern):
            scanned += 1
            try:
                age = now - os.path.getmtime(fp)
                if age > max_age:
                    sz = 0
                    try: sz = os.path.getsize(fp)
                    except Exception: pass
                    if _safe_remove(fp):
                        deleted += 1; freed_b += sz
                    else:
                        skipped += 1
                else:
                    skipped += 1
            except FileNotFoundError:
                scanned -= 1
            except Exception:
                skipped += 1
    gc.collect()
    return {"scanned": scanned, "deleted": deleted,
            "skipped": skipped, "freed_mb": round(freed_b / 1048576, 2)}


def cleanup_session(sid: str, tmp_dir: str = TMP_DIR,
                    output_dir: str = "output") -> None:
    """Hapus semua file milik SID tertentu tanpa cek umur (untuk tombol Reset)."""
    for pattern in [os.path.join(tmp_dir,    f"tmp_{sid}_*"),
                    os.path.join(output_dir, f"out_{sid}*.mp4")]:
        for fp in glob.glob(pattern):
            _safe_remove(fp)
    gc.collect()


# ── Jalankan cleanup SEBELUM set_page_config ─────────────────────────────────
Path("assets").mkdir(exist_ok=True)
Path("fonts").mkdir(exist_ok=True)
Path("output").mkdir(exist_ok=True)
_CLEANUP = auto_cleanup()


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 3 — STREAMLIT PAGE CONFIG & CSS
# ═══════════════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="Mansion Video Generator", layout="centered")

st.markdown("""
<style>
[data-testid="stSidebar"] { min-width: 280px; }
@media (max-width: 640px) {
    div[data-testid="column"] { width:100% !important; flex:1 1 100% !important; }
    .stButton > button { width: 100%; }
    .main .block-container { padding-left:.8rem; padding-right:.8rem; }
}
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
        nltk.download("punkt", quiet=True)
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
# BAGIAN 5 — KONSTANTA
# ═══════════════════════════════════════════════════════════════════════════════
CAPTION_COLORS = [
    (255, 215,   0),   # Gold   — HOOK
    (255, 255, 255),   # White
    (192, 192, 192),   # Silver
    (255, 223, 128),   # Champagne
    (210, 180, 140),   # Rose Gold
]
HOOK_COLOR      = (255, 215, 0)
STROKE_COLOR    = (0, 0, 0)
STROKE_W        = 2
VERT_LINE_W     = 6
VERT_LINE_GAP   = 10
VERT_LINE_COLOR = (255, 215, 0)
CAPTION_Y       = 0.52
CTA_Y           = 0.66
SAFE_BOTTOM     = 0.78


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 6 — FONT HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
_FONT_LABELS = {
    "DejaVuSans-Bold.ttf"        : "DejaVu Sans Bold",
    "DejaVuSans.ttf"             : "DejaVu Sans",
    "LiberationSans-Bold.ttf"    : "Liberation Sans Bold",
    "LiberationSans.ttf"         : "Liberation Sans",
    "FreeSansBold.ttf"           : "Free Sans Bold",
    "FreeSans.ttf"               : "Free Sans",
    "NotoSans-Bold.ttf"          : "Noto Sans Bold",
    "NotoSans-Regular.ttf"       : "Noto Sans",
    "Roboto-Black.ttf"           : "Roboto Black",
    "RobotoCondensed-Bold.ttf"   : "Roboto Condensed Bold",
    "Ubuntu-Bold.ttf"            : "Ubuntu Bold",
    "Montserrat-Bold.ttf"        : "Montserrat Bold",
    "Oswald-Bold.ttf"            : "Oswald Bold",
    "PlayfairDisplay-Bold.ttf"   : "Playfair Display Bold",
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
    """Kembalikan list font yang tersedia: fonts/ > assets/ > sistem Linux."""
    found, seen = [], set()

    def add(path: str, label: str):
        p = os.path.normpath(path)
        if p not in seen and os.path.exists(p):
            seen.add(p)
            found.append({"label": label, "path": p})

    for folder, prefix in [("fonts", "📁 "), ("assets", "📁 ")]:
        for ext in ("*.ttf", "*.TTF", "*.otf", "*.OTF"):
            for fp in sorted(glob.glob(os.path.join(folder, ext))):
                fname = os.path.basename(fp)
                label = _FONT_LABELS.get(fname,
                    os.path.splitext(fname)[0].replace("_"," ").replace("-"," ").title())
                add(fp, f"{prefix}{label}")
    for fp in _SYSTEM_FONTS:
        fname = os.path.basename(fp)
        add(fp, _FONT_LABELS.get(fname, os.path.splitext(fname)[0]))
    return found


def get_font(size: int, path: str = "") -> ImageFont.FreeTypeFont:
    if path and os.path.exists(path):
        try:
            return ImageFont.truetype(path, max(8, size))
        except Exception:
            pass
    fonts = scan_fonts()
    if fonts:
        try:
            return ImageFont.truetype(fonts[0]["path"], max(8, size))
        except Exception:
            pass
    return ImageFont.load_default()


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 7 — NLP: PECAH DESKRIPSI → CAPTION
# ═══════════════════════════════════════════════════════════════════════════════
def split_captions(text: str, n: int) -> list[str]:
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

    MAX_W = 8
    return [
        (" ".join(c.split()[:MAX_W]) + "…" if len(c.split()) > MAX_W else c)
        for c in captions[:n]
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 8 — RENDER OVERLAY (Caption, CTA, Logo, Progress Bar)
# ═══════════════════════════════════════════════════════════════════════════════
def _compute_layout(out_w: int):
    return (
        max(18, int(out_w * 0.065)),   # font_size
        max(22, int(out_w * 0.080)),   # hook_size
        max(8,  int(out_w * 0.045)),   # pad_x
        max(4,  int(out_w * 0.018)),   # pad_y
    )


def _wrap(text: str, font, max_w: int, draw) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if (draw.textbbox((0, 0), test, font=font)[2]) <= max_w:
            cur = test
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines or [""]


def _fit_wrap(text: str, max_w: int, font_path: str,
              size: int, max_lines: int = 4):
    dummy = Image.new("RGBA", (1, 1))
    draw  = ImageDraw.Draw(dummy)
    s = max(8, size)
    while s >= 8:
        f = get_font(s, font_path)
        lines = _wrap(text, f, max_w, draw)
        if len(lines) <= max_lines:
            return f, lines
        s -= 1
    f = get_font(8, font_path)
    return f, _wrap(text, f, max_w, draw)


def _fit_single(text: str, max_w: int, font_path: str, size: int):
    dummy = Image.new("RGBA", (1, 1))
    draw  = ImageDraw.Draw(dummy)
    s = max(8, size)
    prev = None
    while s >= 8:
        f  = get_font(s, font_path)
        tw = draw.textbbox((0, 0), text, font=f)[2]
        if tw <= max_w:
            return f, s
        if prev is not None and tw >= prev:
            break
        prev = tw; s -= 2
    return get_font(8, font_path), 8


def _stroke_text(draw, x, y, text, font, rgb):
    for dx in range(-STROKE_W, STROKE_W + 1):
        for dy in range(-STROKE_W, STROKE_W + 1):
            if dx == 0 and dy == 0: continue
            draw.text((x+dx, y+dy), text, font=font, fill=(*STROKE_COLOR, 255))
    draw.text((x, y), text, font=font, fill=(*rgb, 255))


def _paste_logo(canvas, out_w, out_h, logo_pil):
    if logo_pil is None: return
    try:
        lw = max(20, int(out_w * 0.25))
        lh = max(1, int(logo_pil.height * lw / logo_pil.width))
        lr = logo_pil.resize((lw, lh), Image.LANCZOS).convert("RGBA")
        lx = (out_w - lw) // 2
        ly = min(max(4, int(out_h * 0.03)), out_h - lh - 4)
        canvas.paste(lr, (lx, ly), lr)
    except Exception:
        pass


def render_caption(text: str, out_w: int, out_h: int,
                   size: int, pad_x: int, pad_y: int,
                   color=(255,255,255), font_path="",
                   logo_pil=None, max_lines=4,
                   align="Center") -> np.ndarray:
    """
    Render caption overlay RGBA sebagai numpy float32.
    align: "Center" | "Left" | "Right"
      Left / Right menampilkan garis vertikal Gold.
    """
    canvas = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)

    if text.strip():
        lm    = (VERT_LINE_W + VERT_LINE_GAP) if align != "Center" else 0
        box_w = max(1, out_w - pad_x * 2)
        usable= max(1, box_w - lm - 8)
        font, lines = _fit_wrap(text, usable, font_path, size, max_lines)
        lh   = max(1, draw.textbbox((0, 0), "Ag", font=font)[3])
        lgap = max(2, int(lh * 0.10))
        th   = lh * len(lines) + lgap * (len(lines) - 1)

        safe_px = int(out_h * SAFE_BOTTOM)
        ty      = int(out_h * CAPTION_Y)
        if ty + th > safe_px:
            ty = max(0, safe_px - th - pad_y)

        text_x_anchor = text_x_end = None
        if align == "Left":
            gx0 = pad_x
            gx1 = pad_x + VERT_LINE_W
            draw.rectangle([gx0, ty, gx1, ty + th], fill=(*VERT_LINE_COLOR, 255))
            text_x_anchor = gx1 + VERT_LINE_GAP
        elif align == "Right":
            gx1 = out_w - pad_x
            gx0 = gx1 - VERT_LINE_W
            draw.rectangle([gx0, ty, gx1, ty + th], fill=(*VERT_LINE_COLOR, 255))
            text_x_end = gx0 - VERT_LINE_GAP

        cy = ty
        for line in lines:
            if not line.strip():
                cy += lh + lgap; continue
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


def render_cta(nama: str, wa: str, out_w: int, out_h: int,
               size: int, pad_x: int, pad_y: int,
               font_path="", logo_pil=None,
               label="HUBUNGI :") -> np.ndarray:
    canvas = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)
    items  = []
    if label: items.append((label.upper(), (255,255,255)))
    if nama:  items.append((nama.upper(),  (255,215,0)))
    if wa:    items.append((f"WA: {wa}",   (255,255,255)))

    if items:
        box_w  = max(1, out_w - pad_x * 2)
        usable = max(1, box_w - pad_x)
        rendered = []
        for i, (txt, clr) in enumerate(items):
            sz = max(8, int(size * (0.60 if i != 1 else 0.80)))
            f, _ = _fit_single(txt, usable, font_path, sz)
            bb   = draw.textbbox((0, 0), txt, font=f)
            rendered.append((txt, clr, f, max(1,bb[2]-bb[0]), max(1,bb[3]-bb[1])))

        lgap     = max(4, pad_y)
        tot_th   = sum(r[4] for r in rendered) + lgap*(len(rendered)-1)
        gold_h   = max(2, int(out_h * 0.003))
        block    = tot_th + gold_h + pad_y * 3
        safe_px  = int(out_h * SAFE_BOTTOM)
        y_top    = int(out_h * CTA_Y)
        if y_top + block > safe_px:
            y_top = max(0, safe_px - block)

        draw.rectangle([pad_x, y_top, pad_x+box_w, y_top+gold_h],
                       fill=(255,215,0,255))
        cy = y_top + gold_h + pad_y
        for txt, clr, f, tw, th in rendered:
            tx = pad_x + (box_w - tw) // 2
            _stroke_text(draw, tx, cy, txt, f, clr)
            cy += th + lgap

    _paste_logo(canvas, out_w, out_h, logo_pil)
    return np.array(canvas).astype(np.float32)


def blend(frame: np.ndarray, overlay: np.ndarray) -> np.ndarray:
    if frame.shape[:2] != overlay.shape[:2]:
        return frame
    alpha = overlay[:, :, 3:] / 255.0
    return np.clip(
        frame.astype(np.float32) * (1 - alpha) + overlay[:, :, :3] * alpha,
        0, 255
    ).astype(np.uint8)


def grade_frame(f, br, co, sa, sh):
    img = Image.fromarray(f.astype(np.uint8))
    img = ImageEnhance.Brightness(img).enhance(br)
    img = ImageEnhance.Contrast(img).enhance(co)
    img = ImageEnhance.Color(img).enhance(sa)
    img = ImageEnhance.Sharpness(img).enhance(sh)
    return np.array(img)


def draw_progress_bar(frame, t, total, out_w, out_h, bar_h=4):
    """Gambar progress bar putih di bawah frame."""
    if total <= 0: return frame
    result = frame.copy()
    bar_w  = int(out_w * min(max(t / total, 0), 1))
    y0     = max(0, out_h - bar_h)
    result[y0:out_h, :, :]      = (result[y0:out_h,:,:] * 0.3).astype(np.uint8)
    if bar_w > 0:
        result[y0:out_h, :bar_w, :] = 255
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 9 — VIDEO PROCESSING HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def blur_clip(clip, radius=25):
    def _blur(f):
        return np.array(Image.fromarray(f).filter(ImageFilter.GaussianBlur(radius)))
    return clip.image_transform(_blur)


def fit_to_916(clip, out_w, out_h):
    """Resize clip ke portrait 9:16 dengan blur background jika landscape."""
    try:
        cw, ch = clip.size
        sr, dr = cw / ch, out_w / out_h
        if abs(sr - dr) < 0.05:
            return clip.resized((out_w, out_h))
        scale_h  = out_h / ch
        bg_w_raw = max(out_w, int(cw * scale_h))
        bg       = blur_clip(clip.resized((bg_w_raw, out_h)), radius=25)
        if bg_w_raw > out_w:
            x1 = (bg_w_raw - out_w) // 2
            bg = bg.with_effects([Crop(x1=x1, x2=x1+out_w, y1=0, y2=out_h)])
        fg_h  = max(1, int(out_w / sr))
        fg    = clip.resized((out_w, fg_h))
        fg_y0 = (out_h - fg_h) // 2
        fg_y1 = fg_y0 + fg_h

        def _compose(t):
            res = bg.get_frame(t).copy()
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
    """Gabungkan clips dengan crossfade halus."""
    if not clips:
        raise ValueError("crossfade_concat: daftar klip kosong")
    if len(clips) == 1:
        return clips[0]
    min_dur = min(c.duration for c in clips)
    fd      = min(fade_d, min_dur * 0.4)
    starts  = [0.0]
    for c in clips[:-1]:
        starts.append(starts[-1] + c.duration - fd)
    total_dur = starts[-1] + clips[-1].duration

    def _frame(t):
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
                result = result * (1 - alpha) + frame.astype(np.float32) * alpha
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
    Potong setiap video menjadi segmen 4–6 detik secara acak.
    Guard: video < 2 detik diabaikan (warning); video 2–4 detik diambil utuh.
    """
    pool = []
    for src_idx, vc in enumerate(video_clips):
        dur = vc.duration
        if dur < 2.0:
            st.warning(f"⚠️ Video #{src_idx+1} terlalu pendek ({dur:.1f}s) — dilewati.")
            continue
        if dur < min_seg:
            # Ambil utuh sebagai satu segmen
            pool.append({"src_idx": src_idx, "start": 0.0,
                         "end": round(dur, 2), "duration": round(dur, 2)})
            continue
        t = 0.0
        while t < dur - 1.0:
            end    = min(t + max_seg, dur)
            actual = round(end - t, 2)
            if actual < min_seg:
                break
            pool.append({"src_idx": src_idx, "start": round(t, 2),
                         "end": round(end, 2), "duration": actual})
            t += max_seg

    if not pool:
        raise ValueError(
            "Semua video terlalu pendek (< 2 detik). "
            "Upload video minimal 2 detik."
        )

    random.shuffle(pool)
    selected, total = [], 0.0
    for s in pool:
        if total >= target_dur: break
        selected.append(s)
        total += s["duration"]
    for i, s in enumerate(selected):
        s["seg_idx"] = i
    return selected


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 11 — KEN BURNS PHOTO SLIDESHOW
# ═══════════════════════════════════════════════════════════════════════════════
def _photo_to_frame(img_path: str, out_w: int, out_h: int) -> np.ndarray:
    """
    Render satu foto ke base frame berukuran out_w × out_h dengan
    logika fit-to-9:16 (foreground + blurred background).
    """
    img = Image.open(img_path).convert("RGB")
    iw, ih = img.size
    sr, dr = iw / ih, out_w / out_h

    if abs(sr - dr) < 0.05:
        return np.array(img.resize((out_w, out_h), Image.LANCZOS))

    scale_h  = out_h / ih
    bg_w_raw = max(out_w, int(iw * scale_h))
    bg       = img.resize((bg_w_raw, out_h), Image.LANCZOS)
    bg       = bg.filter(ImageFilter.GaussianBlur(radius=25))
    if bg_w_raw > out_w:
        x1 = (bg_w_raw - out_w) // 2
        bg = bg.crop((x1, 0, x1 + out_w, out_h))
    fg_h   = max(1, int(out_w / sr))
    fg_img = img.resize((out_w, fg_h), Image.LANCZOS)
    fg_y0  = (out_h - fg_h) // 2
    canvas = bg.copy()
    canvas.paste(fg_img, (0, fg_y0))
    return np.array(canvas).astype(np.uint8)


def photo_to_clip(img_path: str, duration: float,
                  out_w: int, out_h: int,
                  zoom_start: float = 1.00,
                  zoom_end:   float = 1.15) -> VideoClip:
    """
    Buat VideoClip dari foto dengan Ken Burns Effect (slow zoom-in).

    Mekanisme:
      1. Render base_frame pada ukuran zoom_end × (out_w × out_h)
         (frame terbesar yang dibutuhkan).
      2. Setiap frame(t): crop area makin kecil → objek terlihat membesar.
         progress 0→1: crop_w = base_w → out_w (zoom_start→zoom_end).
    """
    MAX_SCALE = zoom_end
    base_w = int(out_w * MAX_SCALE)
    base_h = int(out_h * MAX_SCALE)

    # Render base pada ukuran diperbesar
    img = Image.open(img_path).convert("RGB")
    iw, ih = img.size
    sr, dr = iw / ih, base_w / base_h

    if abs(sr - dr) < 0.05:
        base_frame = np.array(img.resize((base_w, base_h), Image.LANCZOS))
    else:
        scale_h  = base_h / ih
        bg_w_raw = max(base_w, int(iw * scale_h))
        bg       = img.resize((bg_w_raw, base_h), Image.LANCZOS)
        bg       = bg.filter(ImageFilter.GaussianBlur(radius=25))
        if bg_w_raw > base_w:
            x1 = (bg_w_raw - base_w) // 2
            bg = bg.crop((x1, 0, x1 + base_w, base_h))
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
        # Crop makin kecil seiring waktu → zoom-in
        # Di t=0: crop = base (zoom_start), di t=dur: crop = out (zoom_end)
        start_w = int(_bw / zoom_start * zoom_start)   # = base_w di t=0
        crop_w  = max(_ow, int(_bw - (_bw - _ow) * progress))
        crop_h  = max(_oh, int(_bh - (_bh - _oh) * progress))
        x1 = max(0, (_bw - crop_w) // 2)
        y1 = max(0, (_bh - crop_h) // 2)
        cropped = base_frame[y1:y1+crop_h, x1:x1+crop_w]
        return np.array(
            Image.fromarray(cropped).resize((_ow, _oh), Image.BILINEAR)
        ).astype(np.uint8)

    return VideoClip(make_frame, duration=duration).with_fps(24)


def build_photo_slideshow(photo_paths: list, target_dur: int,
                           out_w: int, out_h: int,
                           fade_dur: float = 0.5,
                           zoom_end: float = 1.15) -> VideoClip:
    """
    Bangun slideshow dari foto-foto dengan Ken Burns Effect.
    Guard: raise ValueError jika photo_paths kosong.
    """
    if not photo_paths:
        raise ValueError("build_photo_slideshow: daftar foto kosong")
    n      = len(photo_paths)
    per_ph = max(5.0, min(8.0, target_dur / n))
    clips  = [photo_to_clip(p, per_ph, out_w, out_h, zoom_end=zoom_end)
              for p in photo_paths]
    faded  = []
    for i, c in enumerate(clips):
        fx = []
        if i > 0:     fx.append(FadeIn(fade_dur))
        if i < n - 1: fx.append(FadeOut(fade_dur))
        faded.append(c.with_effects(fx) if fx else c)
    return concatenate_videoclips(faded, method="chain")


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 12 — PASS 2: OVERLAY CAPTION + CTA + GRADING + AUDIO
# ═══════════════════════════════════════════════════════════════════════════════
def run_pass2(pass1_path: str, out_path: str,
              deskripsi: str, n_caption: int,
              detail_colors: list,
              cta_nama: str, cta_wa: str,
              cta_dur: float, cta_label: str,
              do_grade: bool,
              brightness: float, contrast: float,
              saturation: float, sharpness: float,
              bgm_file, bgm_volume: float, orig_vol: float,
              OUT_W: int, OUT_H: int,
              logo_pil, font_path: str,
              caption_align: str = "Center") -> tuple[bool, list, str]:
    """
    Pass 2: overlay caption + CTA + progress bar → simpan ke out_path.
    Return (success, captions, error_message)
    Semua resource WAJIB ditutup di blok finally.
    """
    open_clips  = []
    bgm_tmp     = _tmp(f"tmp_{SID}_bgm.mp3")
    bgm_created = False

    try:
        # ── NLP status ──────────────────────────────────────────────────────────
        _nlp_icon = {"nltk":"🟢 NLTK","textblob":"🟡 TextBlob","builtin":"🔵 Regex"}
        st.write(f"🧠 NLP: **{_nlp_icon.get(NLP_ENGINE, NLP_ENGINE)}** "
                 f"| {n_caption} caption · align **{caption_align}**")

        captions = split_captions(deskripsi, n_caption)

        with st.expander("📋 Preview Caption", expanded=True):
            for i, cap in enumerate(captions):
                tag = "🪝 HOOK" if i == 0 else f"📌 Detail {i}"
                st.markdown(f"**Caption {i+1}** `[{tag}]`")
                st.info(cap if cap else "_(kosong)_")
            if cta_nama.strip() or cta_wa.strip():
                st.markdown("**CTA (detik terakhir)**")
                st.success(f"📞 {cta_nama}  |  WA: {cta_wa}")

        # ── Layout ──────────────────────────────────────────────────────────────
        font_size, hook_size, pad_x, pad_y = _compute_layout(OUT_W)
        bar_h    = max(3, int(OUT_H * 0.006))
        all_clr  = [HOOK_COLOR] + list(detail_colors)

        # ── Pre-render overlays ─────────────────────────────────────────────────
        overlays = []
        for idx, cap in enumerate(captions):
            clr = all_clr[idx % len(all_clr)]
            sz  = hook_size if idx == 0 else font_size
            overlays.append(render_caption(
                cap, OUT_W, OUT_H, sz, pad_x, pad_y,
                color=clr, font_path=font_path, logo_pil=logo_pil,
                align=caption_align,
            ))

        cta_ov = None
        if cta_nama.strip() or cta_wa.strip():
            cta_ov = render_cta(
                cta_nama.strip(), cta_wa.strip(),
                OUT_W, OUT_H, font_size, pad_x, pad_y,
                font_path=font_path, logo_pil=logo_pil,
                label=cta_label.strip(),
            )

        # ── Baca Pass 1 ─────────────────────────────────────────────────────────
        st.write("📂 Membaca Pass 1...")
        p1 = VideoFileClip(pass1_path)
        open_clips.append(p1)
        total_dur = p1.duration
        n_cap     = len(captions)
        interval  = total_dur / max(n_cap, 1)
        cta_start = max(0.0, total_dur - cta_dur)
        audio_src = p1.audio

        sched = " | ".join([f"{i+1}. {i*interval:.0f}s–{(i+1)*interval:.0f}s"
                            for i in range(n_cap)])
        st.write(f"🕐 {sched}")

        # ── BGM ─────────────────────────────────────────────────────────────────
        if bgm_file:
            try:
                bgm_file.seek(0)   # ← WAJIB: reset pointer file uploader
                with open(bgm_tmp, "wb") as f:
                    f.write(bgm_file.read())
                bgm_created = True
                bgm_raw = AudioFileClip(bgm_tmp)
                open_clips.append(bgm_raw)   # ← pastikan ditutup di finally
                if bgm_raw.duration > total_dur:
                    bgm_raw = bgm_raw.subclipped(0, total_dur)
                fo_dur    = min(3.0, bgm_raw.duration * 0.3)
                bgm_audio = bgm_raw.with_effects([
                    AudioFadeOut(fo_dur), MultiplyVolume(bgm_volume),
                ])
                # --- PERBAIKAN LOGIKA AUDIO ---
                if audio_src is not None:
                    audio_src = audio_src.with_effects([MultiplyVolume(orig_vol)])
                
                # Masukkan audio_src yang sudah di-volume ke dalam list mixing
                mixed_list = [a for a in [audio_src, bgm_audio] if a is not None]
                if mixed_list:
                    # Gabungkan SEMUA audio menjadi satu track
                    audio_final_track = CompositeAudioClip(mixed_list)
                    # Tempelkan track audio ini ke video p1 SEBELUM ditransform
                    p1 = p1.with_audio(audio_final_track)
                
                st.write(f"  ✅ Audio Mixed: BGM {bgm_raw.duration:.1f}s")
            except Exception as e:
                st.warning(f"⚠️ BGM gagal dimuat: {e}")

        # ── Closure variables untuk frame processor ─────────────────────────────
        _do   = bool(do_grade)
        _br   = float(brightness) if _do else 1.0
        _co   = float(contrast)   if _do else 1.0
        _sa   = float(saturation) if _do else 1.0
        _sh   = float(sharpness)  if _do else 1.0
        _ovs  = list(overlays)
        _cta  = cta_ov
        _cs   = float(cta_start)
        _iv   = float(interval)
        _nc   = int(n_cap)
        _td   = float(total_dur)
        _bh   = int(bar_h)
        _ow   = int(OUT_W)
        _oh   = int(OUT_H)

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

        # ── Render & tulis ───────────────────────────────────────────────────────
        st.write("🎬 Render Pass 2...")
        # Gunakan .transform untuk menerapkan pass2_proc ke setiap frame
        final = p1.transform(pass2_proc)
        
        # Eksekusi penulisan file
        final.write_videofile(
            out_path, 
            codec="libx264", 
            audio_codec="aac", 
            fps=24,
            ffmpeg_params=["-pix_fmt", "yuv420p"], 
            logger=None,
            threads=4
        )
        
        return True, captions, ""

    except Exception as e:
        import traceback
        return False, [], f"{str(e)}\n{traceback.format_exc()}"

    finally:
        # ── WAJIB: tutup semua resource agar Streamlit Cloud tidak Segfault ──
        for oc in open_clips:
            try: oc.close()
            except Exception: pass
        if bgm_created and os.path.exists(bgm_tmp):
            _safe_remove(bgm_tmp)
        gc.collect()

# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 13 — UI: HEADER & SESSION
# ═══════════════════════════════════════════════════════════════════════════════
st.title("🎬 Mansion Video Generator")
st.caption("Aplikasi membuat video Konten Sosial Media dalam Format Portrait")

if _CLEANUP["deleted"] > 0:
    st.toast(
        f"🧹 Auto-cleanup: {_CLEANUP['deleted']} file lama dihapus "
        f"· {_CLEANUP['freed_mb']} MB dibebaskan", icon="✅"
    )

if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex[:8]
SID = st.session_state.session_id
st.caption(f"🔑 Session: `{SID}`")


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 14 — SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════
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
    n_caption = st.slider("Jumlah Caption", 1, 5, 3,
                          help="Deskripsi dipecah menjadi N caption otomatis")

    st.header("📞 CTA (Caption Akhir)")
    cta_label = st.text_input("Teks Label", "Hubungi :")
    cta_nama  = st.text_input("Nama Agen", "Nama Agen")
    cta_wa    = st.text_input("Nomor WhatsApp", "0812-xxxx-xxxx")
    cta_dur   = st.slider("Durasi CTA (detik terakhir)", 2, 8, 4)

    st.header("🎨 Warna Caption 2–5")
    _color_names = ["Gold", "White", "Silver", "Champagne", "Rose Gold"]
    detail_colors = []
    for i in range(1, 5):
        c = st.selectbox(f"Caption {i+1}", options=_color_names,
                         index=i % len(_color_names), key=f"clr_{i}")
        detail_colors.append(CAPTION_COLORS[_color_names.index(c)])

    st.header("✨ Color Grading")
    do_grade   = st.toggle("Aktifkan", value=False)
    brightness = st.slider("Brightness",  0.7, 1.5, 1.05, 0.05)
    contrast   = st.slider("Contrast",    0.7, 1.5, 1.10, 0.05)
    saturation = st.slider("Saturation",  0.7, 1.5, 1.05, 0.05)
    sharpness  = st.slider("Sharpness",   0.7, 2.0, 1.10, 0.05)

    st.header("🔤 Font & Alignment")
    _avail = scan_fonts()
    if _avail:
        _labels = [f["label"] for f in _avail]
        _paths  = [f["path"]  for f in _avail]
        _choice = st.selectbox(
            "Font", options=range(len(_labels)),
            format_func=lambda i: _labels[i], index=0,
        )
        selected_font_path = _paths[_choice]
        st.caption(f"`{os.path.basename(selected_font_path)}`")
    else:
        selected_font_path = ""
        st.warning("Tidak ada font. Upload file `.ttf` ke folder `fonts/` di GitHub.")

    caption_align = st.selectbox(
        "Caption Align", ["Center", "Left", "Right"], index=0,
        help="Left/Right menampilkan garis vertikal Gold di sisi teks."
    )
    st.caption("💡 Upload `.ttf` ke folder `fonts/` di GitHub untuk font custom.")

    st.header("🖼️ Logo")
    logo_file = st.file_uploader("Upload Logo (PNG)", type=["png"])

    st.header("🎵 Background Music")
    bgm_file   = st.file_uploader("Upload MP3/WAV", type=["mp3","wav"])
    bgm_volume = st.slider("Volume BGM",           0.1, 1.0, 0.50, 0.05)
    orig_vol   = st.slider("Volume Video (+ BGM)", 0.0, 1.0, 0.80, 0.05)

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

    # ── Storage widget ─────────────────────────────────────────────────────────
    st.divider()
    st.caption("🗄️ **Storage Server**")
    _sc = _CLEANUP
    if _sc["deleted"] > 0:
        st.caption(f"✅ {_sc['deleted']} file dihapus · {_sc['freed_mb']} MB dibebaskan")
    else:
        st.caption(f"✨ Bersih · {_sc['scanned']} file diperiksa")
    if st.button("🔍 Bersihkan Sekarang", use_container_width=True):
        _r = auto_cleanup()
        if _r["deleted"] > 0:
            st.success(f"✅ {_r['deleted']} file dihapus · {_r['freed_mb']} MB dibebaskan")
        else:
            st.info(f"✨ Bersih · {_r['scanned']} file diperiksa")
        gc.collect()


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 15 — TAB INPUT (VIDEO / PHOTO)
# ═══════════════════════════════════════════════════════════════════════════════
tab_video, tab_photo = st.tabs(["🎬  A · Buat Video", "🖼️  B · Photo Slide"])

with tab_video:
    st.caption("Upload beberapa file video. Setiap file dipotong otomatis 4–6 detik.")
    video_files = st.file_uploader(
        "Upload Video (bisa lebih dari 1)",
        type=["mp4","mov","avi"], accept_multiple_files=True,
        key="up_video",
    )

with tab_photo:
    st.caption("Upload foto (maks 6). **Ken Burns Effect** zoom 100%→115% otomatis.")
    photo_files = st.file_uploader(
        "Upload Foto (maks 6)",
        type=["jpg","jpeg","png","webp"], accept_multiple_files=True,
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
_SS = {
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
    "trim_vcs"     : [],
    "input_mode"   : "video",
    "photo_paths"  : [],
}
for k, v in _SS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 17 — MAIN UI: TOMBOL KONTROL
# ═══════════════════════════════════════════════════════════════════════════════
st.divider()

if st.session_state.pass1_ready:
    p1 = st.session_state.pass1_path
    if os.path.exists(p1):
        sz = os.path.getsize(p1) / 1048576
        st.success(
            f"✅ **Pass 1 tersimpan** — `{p1}` ({sz:.1f} MB) · "
            f"{st.session_state.p1_out_w}×{st.session_state.p1_out_h}"
        )
    else:
        st.warning("⚠️ File Pass 1 tidak ditemukan. Jalankan ulang.")
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

if btn_reset:
    for vc in st.session_state.get("trim_vcs", []):
        try: vc.close()
        except Exception: pass
    cleanup_session(SID)
    gc.collect()
    for k in list(_SS.keys()):
        if k in st.session_state:
            del st.session_state[k]
    st.success("🗑️ Session direset.")
    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 18 — STEP 1: PREVIEW TRIM / FOTO
# ═══════════════════════════════════════════════════════════════════════════════
if btn_full and has_input:
    for vc in st.session_state.get("trim_vcs", []):
        try: vc.close()
        except Exception: pass
    for k in ["trim_segs","trim_approved","trim_vcs","pass1_ready",
              "pass2_done","video_bytes","input_mode"]:
        st.session_state[k] = _SS.get(k, False if "ready" in k or "approved" in k or "done" in k else [])
    st.session_state.input_mode = input_mode

    if input_mode == "video":
        with st.status("🔍 Menganalisis video...", expanded=True) as status:
            open_vcs = []
            try:
                raw_clips = []
                for i, vf in enumerate(video_files):
                    raw = _tmp(f"tmp_{SID}_raw_{i}.mp4")
                    fin = _tmp(f"tmp_{SID}_v_{i}.mp4")
                    vf.seek(0)   # ← WAJIB
                    with open(raw, "wb") as f: f.write(vf.read())
                    size_mb = os.path.getsize(raw) / 1048576
                    if size_mb > 400:
                        st.write(f"  ⚠️ Video {i+1}: {size_mb:.0f} MB → kompres...")
                        r = subprocess.run([
                            "ffmpeg","-y","-i",raw,
                            "-vf","scale=720:-2","-vcodec","libx264",
                            "-crf","28","-preset","ultrafast",
                            "-acodec","aac","-b:a","128k", fin,
                        ], capture_output=True, text=True)
                        if r.returncode != 0:
                            shutil.copy(raw, fin)
                        else:
                            st.write(f"  ✅ {size_mb:.0f}MB → {os.path.getsize(fin)/1048576:.0f}MB")
                    else:
                        shutil.copy(raw, fin)
                    _safe_remove(raw)
                    vc = VideoFileClip(fin)
                    open_vcs.append(vc)
                    raw_clips.append(vc)
                    st.write(f"  📹 Video {i+1}: `{vf.name}` — {vc.duration:.1f}s")

                segments = smart_cut_clips(raw_clips, durasi_target)
                fin_paths = [_tmp(f"tmp_{SID}_v_{i}.mp4") for i in range(len(video_files))]
                st.session_state.trim_segs = [
                    {**s,
                     "src_name": video_files[s["src_idx"]].name,
                     "src_path": fin_paths[s["src_idx"]]}
                    for s in segments
                ]
                st.session_state.trim_vcs = open_vcs
                status.update(label=f"✅ {len(segments)} segmen siap", state="complete")

            except Exception as e:
                status.update(label=f"❌ {e}", state="error")
                st.exception(e)
                for vc in open_vcs:
                    try: vc.close()
                    except Exception: pass

    else:  # photo mode
        with st.status("🖼️ Menyiapkan foto...", expanded=True) as status:
            try:
                photo_paths = []
                for i, pf in enumerate(photo_files[:6]):
                    ext = os.path.splitext(pf.name)[1]
                    p   = _tmp(f"tmp_{SID}_photo_{i}{ext}")
                    pf.seek(0)   # ← WAJIB
                    with open(p, "wb") as f: f.write(pf.read())
                    photo_paths.append(p)
                    st.write(f"  🖼️ Foto {i+1}: `{pf.name}`")
                n     = len(photo_paths)
                per_s = max(5.0, min(8.0, durasi_target / n))
                segs  = [{"src_name": photo_files[i].name, "seg_idx": i,
                           "start": 0, "end": per_s, "duration": per_s,
                           "src_idx": i}
                         for i in range(n)]
                st.session_state.trim_segs    = segs
                st.session_state.photo_paths  = photo_paths
                status.update(
                    label=f"✅ {n} foto · {per_s:.1f}s/slide · Ken Burns 🎥",
                    state="complete"
                )
            except Exception as e:
                status.update(label=f"❌ {e}", state="error")
    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 19 — STEP 2: PREVIEW GRID SEGMEN
# ═══════════════════════════════════════════════════════════════════════════════
def _extract_thumb(src: str, t: float, out: str) -> bool:
    try:
        r = subprocess.run([
            "ffmpeg","-y","-ss",str(round(t,2)),"-i",src,
            "-vframes","1","-vf","scale=240:-1","-q:v","4", out,
        ], capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and os.path.exists(out)
    except Exception:
        return False


def _extract_mini(src: str, start: float, end: float, out: str) -> bool:
    try:
        r = subprocess.run([
            "ffmpeg","-y","-ss",str(round(start,2)),"-i",src,
            "-t",str(round(end-start,2)),"-vf","scale=360:-2",
            "-c:v","libx264","-crf","28","-preset","ultrafast",
            "-an","-movflags","+faststart", out,
        ], capture_output=True, text=True, timeout=30)
        return r.returncode == 0 and os.path.exists(out)
    except Exception:
        return False


if st.session_state.trim_segs and not st.session_state.pass1_ready:
    segs = st.session_state.trim_segs
    mode = st.session_state.input_mode
    st.subheader("📋 Preview Segmen" if mode == "video" else "🖼️ Preview Urutan Foto")
    if mode == "photo":
        st.info("✨ Ken Burns Effect (zoom 100% → 115%) diterapkan saat render.")

    N_COLS = 3
    for row in [segs[i:i+N_COLS] for i in range(0, len(segs), N_COLS)]:
        cols = st.columns(N_COLS)
        for col, s in zip(cols, row):
            with col:
                if mode == "video":
                    idx     = s["seg_idx"]
                    src     = s.get("src_path", "")
                    thumb_p = _tmp(f"tmp_{SID}_th_{idx}.jpg")
                    mini_p  = _tmp(f"tmp_{SID}_mn_{idx}.mp4")
                    if not os.path.exists(thumb_p):
                        _extract_thumb(src, s["start"] + s["duration"]/2, thumb_p)
                    if os.path.exists(thumb_p):
                        st.image(thumb_p, use_container_width=True)
                    else:
                        st.markdown("🎬")
                    st.caption(f"**#{idx+1}** {s['src_name'][:14]}\n"
                               f"{s['start']:.1f}s–{s['end']:.1f}s · **{s['duration']:.1f}s**")
                    with st.expander("▶ Play"):
                        if not os.path.exists(mini_p):
                            with st.spinner("Memotong..."):
                                _extract_mini(src, s["start"], s["end"], mini_p)
                        if os.path.exists(mini_p):
                            st.video(mini_p)
                        else:
                            st.warning("Gagal.")
                else:
                    pph = st.session_state.get("photo_paths", [])
                    if s["src_idx"] < len(pph):
                        st.image(pph[s["src_idx"]], use_container_width=True)
                    st.caption(f"**Slide {s['seg_idx']+1}** {s['src_name'][:14]}\n"
                               f"**{s['duration']:.1f}s**/slide 🎥")

    st.divider()
    total_seg = sum(s["duration"] for s in segs)
    st.info(f"📊 **{len(segs)} segmen** · total **{total_seg:.1f}s** (target: {durasi_target}s)")

    ca, cb = st.columns(2)
    if cb.button("🔄 Acak Ulang Urutan", use_container_width=True):
        random.shuffle(st.session_state.trim_segs)
        st.rerun()
    if ca.button("✅ OK — Lanjut Render", use_container_width=True, type="primary"):
        st.session_state.trim_approved = True
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 20 — STEP 3: RENDER PASS 1 + PASS 2
# ═══════════════════════════════════════════════════════════════════════════════
if st.session_state.trim_approved and not st.session_state.pass1_ready:
    segs       = st.session_state.trim_segs
    mode       = st.session_state.input_mode
    pass1_path = _tmp(f"tmp_{SID}_pass1.mp4")
    out_path   = f"output/out_{SID}.mp4"

    # ── Resolusi ──────────────────────────────────────────────────────────────
    if   "360p"  in resolusi: OUT_W, OUT_H = 202, 360
    elif "720p"  in resolusi: OUT_W, OUT_H = 720, 1280
    elif "1080p" in resolusi: OUT_W, OUT_H = 1080, 1920
    else:                      OUT_W, OUT_H = 720, 1280   # Original fallback

    # ── Logo ──────────────────────────────────────────────────────────────────
    logo_pil = None
    if logo_file:
        logo_tmp = _tmp(f"tmp_{SID}_logo.png")
        try:
            logo_file.seek(0)   # ← WAJIB
            with open(logo_tmp, "wb") as f: f.write(logo_file.read())
            logo_pil = Image.open(logo_tmp).convert("RGBA")
        except Exception as e:
            st.warning(f"⚠️ Logo gagal dimuat: {e}")

    with st.status("⏳ Pass 1: Render...", expanded=True) as status:
        open_clips = []
        try:
            st.write(f"📐 Resolusi: **{OUT_W}×{OUT_H}**")

            # ── Bangun clips_916 ───────────────────────────────────────────────
            if mode == "video":
                stored_vcs = st.session_state.get("trim_vcs", [])
                clips_916  = []
                for s in segs:
                    vc  = stored_vcs[s["src_idx"]]
                    seg = vc.subclipped(s["start"], s["end"])
                    f16 = fit_to_916(seg, OUT_W, OUT_H)
                    clips_916.append(f16)
                    st.write(f"  ✂️ {s['src_name']} [{s['start']:.1f}–{s['end']:.1f}s]")
            else:
                photo_paths = st.session_state.get("photo_paths", [])
                st.write("🖼️ Membangun slideshow Ken Burns (100%→115%)...")
                base_slide = build_photo_slideshow(
                    photo_paths, durasi_target, OUT_W, OUT_H,
                    fade_dur=0.5, zoom_end=1.15)
                clips_916 = [base_slide]
                gc.collect()

            # ── Overlay logo di setiap clip ───────────────────────────────────
            if logo_pil is not None:
                lw = max(20, int(OUT_W * 0.20))
                lh = max(1, int(logo_pil.height * lw / logo_pil.width))
                lr = logo_pil.resize((lw, lh), Image.LANCZOS).convert("RGBA")
                ln = np.array(lr).astype(np.float32)
                lx = (OUT_W - lw) // 2
                ly = min(max(4, int(OUT_H * 0.03)), OUT_H - lh - 4)

                def _add_logo(frame, _ln=ln, _lx=lx, _ly=ly, _lw=lw, _lh=lh):
                    if frame.shape[0] < _ly+_lh or frame.shape[1] < _lx+_lw:
                        return frame
                    out   = frame.copy().astype(np.float32)
                    patch = out[_ly:_ly+_lh, _lx:_lx+_lw]
                    alpha = _ln[:,:,3:] / 255.0
                    out[_ly:_ly+_lh, _lx:_lx+_lw] = patch*(1-alpha) + _ln[:,:,:3]*alpha
                    return out.astype(np.uint8)

                clips_916 = [c.image_transform(_add_logo) for c in clips_916]
                st.write("🖼️ Logo diterapkan.")

            # ── Gabungkan dengan transisi ─────────────────────────────────────
            st.write("🔗 Menggabungkan klip...")
            if not clips_916:
                raise ValueError("Tidak ada klip yang berhasil diproses.")
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

            # ── Render Pass 1 ────────────────────────────────────────────────
            status.update(label="⏳ Rendering Pass 1...")
            st.write(f"💾 Render → `{pass1_path}`...")
            base.write_videofile(
                pass1_path, codec="libx264", audio_codec="aac", fps=24,
                ffmpeg_params=["-pix_fmt","yuv420p"], logger=None,
            )
            try: base.close()
            except Exception: pass
            for vc in st.session_state.get("trim_vcs", []):
                try: vc.close()
                except Exception: pass
            st.session_state.trim_vcs = []
            gc.collect()

            st.session_state.pass1_ready  = True
            st.session_state.pass1_path   = pass1_path
            st.session_state.p1_out_w     = OUT_W
            st.session_state.p1_out_h     = OUT_H
            st.session_state.p1_logo_pil  = logo_pil
            st.session_state.p1_font_path = selected_font_path
            st.write("✅ **Pass 1 selesai.**")

            # ── Pass 2 ───────────────────────────────────────────────────────
            status.update(label="⏳ Pass 2: Overlay caption...")
            st.write("## ✍️ Pass 2: Overlay Caption + CTA")
            ok, captions, err = run_pass2(
                pass1_path=pass1_path, out_path=out_path,
                deskripsi=deskripsi, n_caption=n_caption,
                detail_colors=detail_colors,
                cta_nama=cta_nama, cta_wa=cta_wa,
                cta_dur=cta_dur, cta_label=cta_label,
                do_grade=do_grade,
                brightness=brightness, contrast=contrast,
                saturation=saturation, sharpness=sharpness,
                bgm_file=bgm_file, bgm_volume=bgm_volume, orig_vol=orig_vol,
                OUT_W=OUT_W, OUT_H=OUT_H,
                logo_pil=logo_pil, font_path=selected_font_path,
                caption_align=caption_align,
            )
            if not ok:
                status.update(label=f"❌ Pass 2 error: {err}", state="error")
                st.error(err)
            else:
                with open(out_path, "rb") as f:
                    st.session_state.video_bytes = f.read()
                gc.collect()
                st.session_state.pass2_done = True
                st.session_state.out_path   = out_path
                status.update(label="✅ Selesai!", state="complete")

        except Exception as e:
            status.update(label=f"❌ Error: {e}", state="error")
            st.exception(e)
        finally:
            # ── WAJIB: tutup semua resource ───────────────────────────────────
            for oc in open_clips:
                try: oc.close()
                except Exception: pass
            gc.collect()


# ═══════════════════════════════════════════════════════════════════════════════
# BAGIAN 21 — RE-RENDER PASS 2 SAJA
# ═══════════════════════════════════════════════════════════════════════════════
if btn_pass2 and st.session_state.pass1_ready:
    p1    = st.session_state.pass1_path
    op    = f"output/out_{SID}.mp4"
    OUT_W = st.session_state.p1_out_w
    OUT_H = st.session_state.p1_out_h
    lpil  = st.session_state.p1_logo_pil
    fpth  = st.session_state.p1_font_path

    if not os.path.exists(p1):
        st.error(f"❌ File Pass 1 `{p1}` tidak ditemukan. Jalankan ulang Pass 1.")
    else:
        st.session_state.pass2_done  = False
        st.session_state.video_bytes = None
        with st.status("⏳ Re-render Pass 2...", expanded=True) as status:
            ok, captions, err = run_pass2(
                pass1_path=p1, out_path=op,
                deskripsi=deskripsi, n_caption=n_caption,
                detail_colors=detail_colors,
                cta_nama=cta_nama, cta_wa=cta_wa,
                cta_dur=cta_dur, cta_label=cta_label,
                do_grade=do_grade,
                brightness=brightness, contrast=contrast,
                saturation=saturation, sharpness=sharpness,
                bgm_file=bgm_file, bgm_volume=bgm_volume, orig_vol=orig_vol,
                OUT_W=OUT_W, OUT_H=OUT_H,
                logo_pil=lpil, font_path=fpth,
                caption_align=caption_align,
            )
            if not ok:
                status.update(label=f"❌ Error: {err}", state="error")
                st.error(err)
            else:
                with open(op, "rb") as f:
                    st.session_state.video_bytes = f.read()
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
    if os.path.exists(st.session_state.out_path):
        st.video(st.session_state.out_path)
    ca, cb = st.columns([3, 1])
    with ca:
        st.download_button(
            "⬇️ Download Video Final",
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
        "**✍️ Re-render Pass 2** (Pass 1 tidak diulang)"
    )