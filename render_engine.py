"""
render_engine.py — Core Video Render Functions (no Streamlit dependency)
=========================================================================
All functions extracted from VidGen.py.
Streamlit calls replaced with status_cb(msg) callbacks and logging.
"""
import os, glob, gc, random, subprocess, logging
from pathlib import Path

from moviepy import VideoFileClip, concatenate_videoclips, VideoClip, AudioFileClip
from moviepy import CompositeAudioClip
from moviepy.video.fx import Crop, FadeIn, FadeOut
from moviepy.audio.fx import AudioFadeOut, MultiplyVolume
from PIL import Image, ImageFilter, ImageDraw, ImageFont, ImageEnhance
import numpy as np

logger = logging.getLogger(__name__)

# ── NLP Engine detection ──────────────────────────────────────────────────────
import sys
_project_dir = os.path.dirname(os.path.abspath(__file__))
for _sub in ["lib", "Lib", "site-packages",
             os.path.join("lib", "python3", "site-packages")]:
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
        sent_tokenize("test.")
        NLP_ENGINE = "nltk"
    except LookupError:
        nltk.download("punkt",     download_dir=_nltk_local, quiet=True)
        nltk.download("punkt_tab", download_dir=_nltk_local, quiet=True)
        nltk.data.path.insert(0, _nltk_local)
        sent_tokenize("test.")
        NLP_ENGINE = "nltk"
except Exception:
    try:
        from textblob import TextBlob
        TextBlob("test").sentences
        NLP_ENGINE = "textblob"
    except Exception:
        NLP_ENGINE = "builtin"

Path("assets").mkdir(exist_ok=True)
Path("output").mkdir(exist_ok=True)

# ── Constants ─────────────────────────────────────────────────────────────────
CAPTION_COLORS = [
    (255, 215,   0),
    (255, 255, 255),
    (192, 192, 192),
    (255, 223, 128),
    (210, 180, 140),
]
CAPTION_COLOR_NAMES = ["Gold", "White", "Silver", "Champagne", "Rose Gold"]
HOOK_COLOR   = (255, 215, 0)
STROKE_COLOR = (0, 0, 0)
STROKE_W     = 2
VERT_LINE_W     = 6
VERT_LINE_GAP   = 10
VERT_LINE_COLOR = (255, 215, 0)
CAPTION_Y   = 0.52
CTA_Y       = 0.66
SAFE_BOTTOM = 0.78

COLOR_NAME_TO_RGB = {
    "Gold"      : (255, 215,   0),
    "White"     : (255, 255, 255),
    "Silver"    : (192, 192, 192),
    "Champagne" : (255, 223, 128),
    "Rose Gold" : (210, 180, 140),
}

# ── Font helpers ──────────────────────────────────────────────────────────────
_WIN_FONT_LABELS = {
    "ariblk.ttf"   : "Arial Black",   "ARIBLK.TTF"   : "Arial Black",
    "impact.ttf"   : "Impact",        "Impact.ttf"   : "Impact",
    "arialbd.ttf"  : "Arial Bold",    "ariali.ttf"   : "Arial Italic",
    "arial.ttf"    : "Arial",         "verdanab.ttf" : "Verdana Bold",
    "calibrib.ttf" : "Calibri Bold",  "trebucbd.ttf" : "Trebuchet Bold",
    "segoeuib.ttf" : "Segoe UI Bold", "timesbd.ttf"  : "Times New Roman Bold",
    "consolab.ttf" : "Consolas Bold", "georgiabd.ttf": "Georgia Bold",
    "Roboto-Black.ttf"        : "Roboto Black",
    "RobotoCondensed-Bold.ttf": "Roboto Condensed Bold",
    "DejaVuSans-Bold.ttf"     : "DejaVu Sans Bold",
    "LiberationSans-Bold.ttf" : "Liberation Sans Bold",
    "FreeSansBold.ttf"        : "Free Sans Bold",
}
_SYSTEM_FONT_PATHS = [
    "C:/Windows/Fonts/ariblk.ttf", "C:/Windows/Fonts/impact.ttf",
    "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/verdanab.ttf",
    "/usr/share/fonts/truetype/roboto/Roboto-Black.ttf",
    "/usr/share/fonts/truetype/roboto/RobotoCondensed-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def scan_available_fonts() -> list[dict]:
    found, seen = [], set()
    def add(path, label):
        p = os.path.normpath(path)
        if p not in seen and os.path.exists(p):
            seen.add(p); found.append({"label": label, "path": p})
    for ext in ("*.ttf", "*.TTF", "*.otf", "*.OTF"):
        for fp in glob.glob(os.path.join("assets", ext)):
            fname = os.path.basename(fp)
            label = "📁 " + os.path.splitext(fname)[0].replace("_"," ").replace("-"," ").title()
            add(fp, label)
    for fp in _SYSTEM_FONT_PATHS:
        fname = os.path.basename(fp)
        add(fp, _WIN_FONT_LABELS.get(fname, os.path.splitext(fname)[0]))
    return found


def get_font_path(selected_path: str = "") -> str:
    if selected_path and os.path.exists(selected_path):
        return selected_path
    fonts = scan_available_fonts()
    return fonts[0]["path"] if fonts else ""


def get_font(size: int, font_path: str = "") -> ImageFont.FreeTypeFont:
    p = font_path or get_font_path()
    if p:
        try:
            return ImageFont.truetype(p, max(8, size))
        except Exception:
            pass
    return ImageFont.load_default()


# ── NLP / Caption helpers ─────────────────────────────────────────────────────
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
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+(?=[A-Z])', text) if s.strip()]
    if not sentences:
        sentences = [text]
    sentences = [_strip_trailing_punct(s) for s in sentences]
    hook = sentences[0].upper()
    rest = sentences[1:]
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
            s = int(i * bucket); e = max(int((i+1)*bucket), s+1)
            captions.append(" ".join(rest[s:e]).upper())
    MAX_WORDS = 8
    result = []
    for cap in captions[:n]:
        words = cap.split()
        result.append(" ".join(words[:MAX_WORDS]) + ("…" if len(words) > MAX_WORDS else ""))
    return result


# ── Layout helpers ────────────────────────────────────────────────────────────
def compute_layout(out_w: int):
    return (
        max(18, int(out_w * 0.065)),
        max(22, int(out_w * 0.080)),
        max(8,  int(out_w * 0.045)),
        max(4,  int(out_w * 0.018)),
    )


def fit_text_font(text, max_w, font_path, start_size):
    dummy = Image.new("RGBA", (1, 1))
    draw  = ImageDraw.Draw(dummy)
    size, prev_w = max(8, start_size), None
    while size >= 8:
        f  = get_font(size, font_path)
        bb = draw.textbbox((0, 0), text, font=f)
        tw = bb[2] - bb[0]
        if tw <= max_w:
            return f, size
        if prev_w is not None and tw >= prev_w:
            break
        prev_w = tw; size -= 2
    return get_font(8, font_path), 8


def wrap_text_complete(text, font, max_w, draw):
    words = text.split()
    if not words:
        return [""]
    lines, cur = [], ""
    for word in words:
        test = (cur + " " + word).strip()
        bb   = draw.textbbox((0, 0), test, font=font)
        if (bb[2] - bb[0]) <= max_w:
            cur = test
        else:
            if cur: lines.append(cur)
            cur = word
    if cur: lines.append(cur)
    return lines or [""]


def fit_and_wrap(text, max_w, font_path, start_size, max_lines=4):
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


# ── Render overlay helpers ────────────────────────────────────────────────────
def _draw_text_with_stroke(draw, tx, ty, text, font, color_rgb):
    for dx in range(-STROKE_W, STROKE_W + 1):
        for dy in range(-STROKE_W, STROKE_W + 1):
            if dx == 0 and dy == 0: continue
            draw.text((tx+dx, ty+dy), text, font=font, fill=(*STROKE_COLOR, 255))
    r, g, b = color_rgb
    draw.text((tx, ty), text, font=font, fill=(r, g, b, 255))


def _paste_logo(canvas, out_w, out_h, logo_pil):
    if logo_pil is None: return
    try:
        logo_w = max(20, int(out_w * 0.25))
        logo_h = max(1, int(logo_pil.height * logo_w / logo_pil.width))
        logo_r = logo_pil.resize((logo_w, logo_h), Image.LANCZOS).convert("RGBA")
        lx = (out_w - logo_w) // 2
        ly = min(max(4, int(out_h * 0.03)), out_h - logo_h - 4)
        canvas.paste(logo_r, (lx, ly), logo_r)
    except Exception:
        pass


def render_caption_overlay(text, out_w, out_h, start_size, pad_x, pad_y,
                            color_rgb=(255,255,255), font_path="",
                            logo_pil=None, max_lines=4, align="Center"):
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
            gx0 = pad_x; gx1 = pad_x + VERT_LINE_W
            draw.rectangle([gx0, ty_block, gx1, ty_block + total_h], fill=(*VERT_LINE_COLOR, 255))
            text_x_anchor = gx1 + VERT_LINE_GAP
        elif align == "Right":
            gx1 = out_w - pad_x; gx0 = gx1 - VERT_LINE_W
            draw.rectangle([gx0, ty_block, gx1, ty_block + total_h], fill=(*VERT_LINE_COLOR, 255))
            text_x_end = gx0 - VERT_LINE_GAP
        cur_y = ty_block
        for line in lines:
            if not line.strip():
                cur_y += line_h + line_gap; continue
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


def render_watermark_overlay(text: str, out_w: int, out_h: int, font_path: str = "") -> np.ndarray:
    """Render a semi-transparent watermark text overlay (bottom-right corner)."""
    canvas = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)
    wm_size = max(18, int(out_w * 0.055))
    try:
        font = ImageFont.truetype(font_path, wm_size) if font_path and os.path.exists(font_path) else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()
    bb  = draw.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    pad = int(out_w * 0.04)
    tx  = out_w - tw - pad
    ty  = int(out_h * 0.88) - th
    # dark stroke
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            if dx == 0 and dy == 0: continue
            draw.text((tx + dx, ty + dy), text, font=font, fill=(0, 0, 0, 160))
    draw.text((tx, ty), text, font=font, fill=(255, 255, 255, 140))
    return np.array(canvas).astype(np.float32)


def render_cta_overlay(nama, wa, out_w, out_h, start_size, pad_x, pad_y,
                       font_path="", logo_pil=None, label="HUBUNGI :"):
    canvas = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)
    lines_def = []
    if label: lines_def.append((label.upper(), (255, 255, 255)))
    if nama:  lines_def.append((nama.upper(),  (255, 215,   0)))
    if wa:    lines_def.append((f"WA: {wa}",   (255, 255, 255)))
    if lines_def:
        box_w  = max(1, out_w - pad_x * 2)
        usable = max(1, box_w - pad_x)
        rendered = []
        for idx_l, (text, color) in enumerate(lines_def):
            if idx_l == 0 and label: sz = max(8, int(start_size * 0.60))
            elif (idx_l == 1 and label) or (idx_l == 0 and not label): sz = max(8, int(start_size * 0.80))
            else: sz = max(8, int(start_size * 0.60))
            font, _ = fit_text_font(text, usable, font_path, sz)
            bb = draw.textbbox((0, 0), text, font=font)
            rendered.append((text, color, font, max(1, bb[2]-bb[0]), max(1, bb[3]-bb[1])))
        line_gap    = max(4, pad_y)
        total_txt_h = sum(r[4] for r in rendered) + line_gap * (len(rendered)-1)
        safe_bottom_px = int(out_h * SAFE_BOTTOM)
        x_left      = pad_x
        gold_line_h = max(2, int(out_h * 0.003))
        block_total = total_txt_h + gold_line_h + pad_y * 3
        y_top = int(out_h * CTA_Y)
        if y_top + block_total > safe_bottom_px:
            y_top = max(0, safe_bottom_px - block_total)
        draw.rectangle([x_left, y_top, x_left + box_w, y_top + gold_line_h], fill=(255, 215, 0, 255))
        y_top += gold_line_h + pad_y
        cur_y = y_top
        for text, color, font, tw, th in rendered:
            tx = x_left + (box_w - tw) // 2
            for dx in range(-STROKE_W, STROKE_W+1):
                for dy in range(-STROKE_W, STROKE_W+1):
                    if dx == 0 and dy == 0: continue
                    draw.text((tx+dx, cur_y+dy), text, font=font, fill=(0,0,0,255))
            r, g, b = color
            draw.text((tx, cur_y), text, font=font, fill=(r, g, b, 255))
            cur_y += th + line_gap
    _paste_logo(canvas, out_w, out_h, logo_pil)
    return np.array(canvas).astype(np.float32)


# ── Frame processing ──────────────────────────────────────────────────────────
def blend(frame: np.ndarray, overlay: np.ndarray) -> np.ndarray:
    if frame.shape[:2] != overlay.shape[:2]:
        return frame
    rgb   = overlay[:, :, :3]
    alpha = overlay[:, :, 3:] / 255.0
    return np.clip(frame.astype(np.float32)*(1-alpha) + rgb*alpha, 0, 255).astype(np.uint8)


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
    result[bar_y0:out_h, :, :]       = (result[bar_y0:out_h, :, :] * 0.3).astype(np.uint8)
    if bar_w > 0:
        result[bar_y0:out_h, :bar_w, :] = 255
    return result


# ── Video processing ──────────────────────────────────────────────────────────
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
            res = bg.get_frame(t).copy()
            res[fg_y0:fg_y1] = fg.get_frame(t)
            return res
        out = VideoClip(compose, duration=clip.duration).with_fps(clip.fps or 24)
        if clip.audio is not None:
            out = out.with_audio(clip.audio)
        return out
    except Exception as e:
        logger.warning(f"fit_to_916 fallback: {e}")
        return clip.resized((out_w, out_h))


def crossfade_concat(clips, fade_d):
    if len(clips) == 1: return clips[0]
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
    audio = [c.audio.with_start(starts[i]) for i, c in enumerate(clips) if c.audio is not None]
    if audio:
        out = out.with_audio(CompositeAudioClip(audio))
    return out.with_fps(clips[0].fps or 24)


# ── Scene scoring ─────────────────────────────────────────────────────────────
def _laplacian_var(arr: np.ndarray) -> float:
    lap = (
        -4.0*arr[1:-1,1:-1]
        + arr[:-2,1:-1] + arr[2:,1:-1]
        + arr[1:-1,:-2] + arr[1:-1,2:]
    )
    return float(np.var(lap))


def score_segment(src_path: str, start: float, end: float,
                  sid: str, seg_idx: int) -> dict:
    dur = max(1.0, end - start)
    raw = []
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
                arr = np.array(Image.open(tp).convert("L"), dtype=np.float32)
                raw.append({"blur": _laplacian_var(arr), "br": float(np.mean(arr))})
                try: os.remove(tp)
                except Exception: pass
        except Exception:
            pass
    if not raw:
        return {"blur": 0.0, "brightness": 128.0, "composite": 0.5}
    avg_blur = float(np.mean([s["blur"] for s in raw]))
    avg_br   = float(np.mean([s["br"]   for s in raw]))
    blur_n   = min(1.0, avg_blur / 600.0)
    br_n     = 1.0 - abs(avg_br - 135.0) / 135.0
    composite = blur_n * 0.65 + max(0.0, br_n) * 0.35
    return {
        "blur"      : round(avg_blur, 1),
        "brightness": round(avg_br, 1),
        "composite" : round(min(1.0, max(0.0, composite)), 3),
    }


# ── Smart clip cutter ─────────────────────────────────────────────────────────
def smart_cut_clips(video_clips: list, target_dur: int,
                    min_seg=4.0, max_seg=6.0) -> list:
    pool = []
    for src_idx, vc in enumerate(video_clips):
        dur = vc.duration; t = 0.0
        while t < dur - 1.0:
            end    = min(t + max_seg, dur)
            actual = round(end - t, 2)
            if actual < min_seg: break
            pool.append({"src_idx": src_idx, "start": round(t,2), "end": round(end,2), "duration": actual})
            t += max_seg
    random.shuffle(pool)
    selected, total = [], 0.0
    for s in pool:
        if total >= target_dur: break
        selected.append(s); total += s["duration"]
    for i, s in enumerate(selected):
        s["seg_idx"] = i
    return selected


# ── Photo slideshow ───────────────────────────────────────────────────────────
def photo_to_clip(img_path: str, duration: float, out_w: int, out_h: int) -> VideoClip:
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
        bg_img   = img.resize((bg_w_raw, base_h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(25))
        if bg_w_raw > base_w:
            x1     = (bg_w_raw - base_w) // 2
            bg_img = bg_img.crop((x1, 0, x1 + base_w, base_h))
        fg_h   = max(1, int(base_w / src_ratio))
        fg_img = img.resize((base_w, fg_h), Image.LANCZOS)
        fg_y0  = (base_h - fg_h) // 2
        canvas = bg_img.copy(); canvas.paste(fg_img, (0, fg_y0))
        base_frame = np.array(canvas)
    base_frame = base_frame.astype(np.uint8)
    _bw, _bh, _ow, _oh = base_w, base_h, out_w, out_h
    def make_frame(t):
        progress = min(t / max(duration, 1e-6), 1.0)
        crop_w = max(_ow, int(_bw - (_bw - _ow) * progress))
        crop_h = max(_oh, int(_bh - (_bh - _oh) * progress))
        x1 = max(0, (_bw - crop_w) // 2)
        y1 = max(0, (_bh - crop_h) // 2)
        cropped = base_frame[y1:y1+crop_h, x1:x1+crop_w]
        return np.array(Image.fromarray(cropped).resize((_ow, _oh), Image.BILINEAR)).astype(np.uint8)
    return VideoClip(make_frame, duration=duration).with_fps(24)


def build_photo_slideshow(photo_paths, target_dur, out_w, out_h, fade_dur=0.5):
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


# ── Cleanup ───────────────────────────────────────────────────────────────────
def cleanup_session(sid: str):
    patterns = [f"tmp_{sid}_*", f"output/out_{sid}_*.mp4", f"output/pass1_{sid}.mp4"]
    for pat in patterns:
        for f in glob.glob(pat):
            try: os.remove(f)
            except Exception: pass


# ── Pass 2 ────────────────────────────────────────────────────────────────────
def run_pass2(
    pass1_path, out_path, deskripsi, n_caption, detail_colors,
    cta_nama, cta_wa, cta_dur, cta_label,
    do_grade, brightness, contrast, saturation, sharpness,
    bgm_path, bgm_volume, orig_vol,
    OUT_W, OUT_H, logo_pil,
    caption_align="Center", font_path="",
    session_id="tmp", status_cb=None,
    ai_captions=None,
    watermark_text="",
):
    """
    Pass 2: overlay caption + CTA + color grade → write to out_path.
    Returns: (success: bool, captions: list, error: str)

    bgm_path  : str path to BGM audio file (or "" for no BGM)
    ai_captions: optional list of {text, color, align} dicts from Full AI spec
    """
    def _log(msg):
        if status_cb: status_cb(msg)
        else: logger.info(msg)

    open_clips, bgm_tmp = [], f"tmp_{session_id}_bgm.mp3"
    bgm_created = False
    try:
        # ── Captions ──────────────────────────────────────────────────────────
        if ai_captions:
            captions = [c["text"] for c in ai_captions]
            all_colors = [
                COLOR_NAME_TO_RGB.get(c.get("color", "White"), (255,255,255))
                for c in ai_captions
            ]
            all_aligns = [c.get("align", "Center") for c in ai_captions]
        else:
            captions   = split_description_to_captions(deskripsi, n_caption)
            all_colors = [HOOK_COLOR] + list(detail_colors)
            all_aligns = [caption_align] * len(captions)

        _log(f"NLP:{NLP_ENGINE} | {len(captions)} caption | align:{caption_align}")

        font_size, hook_size, pad_x, pad_y = compute_layout(OUT_W)
        active_font = get_font_path(font_path)
        bar_h = max(3, int(OUT_H * 0.006))

        # ── Pre-render overlays ────────────────────────────────────────────────
        overlays = []
        for idx, cap in enumerate(captions):
            color = all_colors[idx % len(all_colors)]
            align = all_aligns[idx] if idx < len(all_aligns) else caption_align
            sz    = hook_size if idx == 0 else font_size
            ov    = render_caption_overlay(
                cap, OUT_W, OUT_H, sz, pad_x, pad_y,
                color_rgb=color, font_path=active_font,
                logo_pil=logo_pil, align=align,
            )
            overlays.append(ov)

        cta_overlay = None
        if cta_nama.strip() or cta_wa.strip():
            cta_overlay = render_cta_overlay(
                cta_nama.strip(), cta_wa.strip(),
                OUT_W, OUT_H, font_size, pad_x, pad_y,
                font_path=active_font, logo_pil=logo_pil,
                label=cta_label.strip() if cta_label.strip() else "",
            )

        _log("Membaca Pass 1...")
        p1_clip   = VideoFileClip(pass1_path)
        open_clips.append(p1_clip)
        total_dur = p1_clip.duration
        n_cap     = len(captions)
        interval  = total_dur / max(n_cap, 1)
        cta_start = max(0.0, total_dur - cta_dur)
        audio_src = p1_clip.audio

        # ── BGM ────────────────────────────────────────────────────────────────
        if bgm_path and os.path.exists(bgm_path):
            try:
                import shutil
                shutil.copy(bgm_path, bgm_tmp)
                bgm_created = True
                bgm_raw     = AudioFileClip(bgm_tmp)
                if bgm_raw.duration > total_dur:
                    bgm_raw = bgm_raw.subclipped(0, total_dur)
                fo_dur    = min(3.0, bgm_raw.duration * 0.3)
                bgm_audio = bgm_raw.with_effects([AudioFadeOut(fo_dur), MultiplyVolume(bgm_volume)])
                if audio_src is not None:
                    audio_src = audio_src.with_effects([MultiplyVolume(orig_vol)])
                mixed = [a for a in [audio_src, bgm_audio] if a is not None]
                if mixed:
                    audio_src = CompositeAudioClip(mixed)
                _log(f"BGM loaded: {bgm_raw.duration:.1f}s")
            except Exception as e:
                _log(f"BGM warning: {e}")

        _do = bool(do_grade)
        _br = float(brightness) if _do else 1.0
        _co = float(contrast)   if _do else 1.0
        _sa = float(saturation) if _do else 1.0
        _sh = float(sharpness)  if _do else 1.0
        _ovs, _cta, _cs, _iv = list(overlays), cta_overlay, float(cta_start), float(interval)
        _nc, _td, _bh = int(n_cap), float(total_dur), int(bar_h)
        _ow, _oh       = int(OUT_W), int(OUT_H)

        _wm = render_watermark_overlay(watermark_text, _ow, _oh, active_font) if watermark_text else None

        def pass2_proc(get_frame, t):
            frame = get_frame(t)
            if _do: frame = grade_frame(frame, _br, _co, _sa, _sh)
            if _cta is not None and t >= _cs:
                frame = blend(frame, _cta)
            else:
                idx   = min(int(t / _iv), _nc - 1)
                frame = blend(frame, _ovs[idx])
            if _wm is not None:
                frame = blend(frame, _wm)
            return draw_progress_bar(frame, t, _td, _ow, _oh, _bh)

        _log("Render Pass 2...")
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
