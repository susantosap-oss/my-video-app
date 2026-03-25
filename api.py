"""
api.py — FastAPI Backend for Mansion Video Generator
=====================================================
Auth:
  POST /api/login              → login, return token
  POST /api/logout             → invalidate token
  GET  /api/me                 → current user info + quota

Endpoints:
  GET  /                       → serve index.html (requires auth)
  GET  /login                  → serve login.html
  POST /api/session            → create render session
  POST /api/upload/{sid}       → upload clips / photos / logo / bgm
  GET  /api/fonts              → list available fonts
  POST /api/ai-spec            → Full AI RenderSpec (requires full_ai tier)
  POST /api/render/{sid}       → trigger background render
  GET  /api/status/{sid}       → poll render status
  GET  /api/download/{sid}     → download result video
  DELETE /api/session/{sid}    → cleanup session files

Admin:
  GET  /api/admin/users        → list users (mansion_team only)
  POST /api/admin/users        → add subscriber
"""
import os, gc, uuid, json, shutil, logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import render_engine as RE
from ai_spec import call_full_ai_spec, validate_and_fill, QuotaExceededError, InvalidKeyError
import database as DB
import auth as Auth

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ── Init DB on startup ────────────────────────────────────────────────────────
DB.init_db()

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
UPLOAD_DIR  = BASE_DIR / "uploads"
OUTPUT_DIR  = BASE_DIR / "output"
STATIC_DIR  = BASE_DIR / "static"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# ── In-memory render session store ───────────────────────────────────────────
SESSIONS: dict[str, dict] = {}

app = FastAPI(title="Mansion Video Generator API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Auth helpers ──────────────────────────────────────────────────────────────
def _get_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return ""

def _require_user(request: Request) -> dict:
    user = Auth.get_current_user(_get_token(request))
    if not user:
        raise HTTPException(status_code=401, detail="Login diperlukan.")
    return user

def _require_mansion(request: Request) -> dict:
    user = _require_user(request)
    if user["user_type"] not in ("mansion_team", "owner"):
        raise HTTPException(status_code=403, detail="Hanya untuk Tim Mansion.")
    return user

def _require_owner(request: Request) -> dict:
    user = _require_user(request)
    if user["user_type"] != "owner":
        raise HTTPException(status_code=403, detail="Hanya untuk Admin.")
    return user


# ─────────────────────────────────────────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/login")
async def login(req: LoginRequest):
    result = Auth.login(req.username.strip(), req.password)
    if not result:
        raise HTTPException(status_code=401, detail="Username atau password salah.")
    return result   # {token, user}

@app.post("/api/logout")
async def logout(request: Request):
    token = _get_token(request)
    if token:
        Auth.logout(token)
    return {"ok": True}

@app.get("/api/me")
async def me(request: Request):
    user = _require_user(request)
    used, limit = DB.get_video_usage(user["id"])
    return {**user, "videos_used": used}

@app.get("/api/subscribe-info")
async def subscribe_info():
    """Public endpoint — returns package list + subscription terms for Trial users."""
    pkgs = DB.get_packages()
    settings = DB.get_all_settings()
    return {
        "packages": [{"key": k, **v} for k, v in pkgs.items() if k not in ("unlimited",)],
        "terms"   : settings.get("subscribe_terms", ""),
        "howto"   : settings.get("subscribe_howto", ""),
        "contact" : settings.get("contact_wa", ""),
    }


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

@app.put("/api/user/password")
async def change_own_password(req: ChangePasswordRequest, request: Request):
    user = _require_user(request)
    # Verify old password
    db_user = DB.get_user_by_id(user["id"])
    if not db_user or db_user["password_hash"] != DB.hash_pw(req.old_password):
        raise HTTPException(status_code=400, detail="Password lama tidak cocok.")
    if len(req.new_password) < 4:
        raise HTTPException(status_code=400, detail="Password baru minimal 4 karakter.")
    ok, err = DB.reset_user_password(user["id"], req.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True}

# ── Admin ─────────────────────────────────────────────────────────────────────
class AddUserRequest(BaseModel):
    username : str
    password : str
    email    : str = ""
    package  : str  # basic | lite | pro

@app.get("/api/admin/users")
async def admin_list_users(request: Request):
    _require_mansion(request)
    users = DB.list_users()
    # attach package labels
    for u in users:
        pkg = DB.PACKAGES.get(u["package"], {})
        u["package_label"] = pkg.get("label", u["package"])
    return {"users": users}

@app.post("/api/admin/users")
async def admin_add_user(req: AddUserRequest, request: Request):
    _require_mansion(request)
    ok, err = DB.add_subscriber(req.username.strip(), req.password, req.email.strip(), req.package)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True, "username": req.username}


class UpdateUserRequest(BaseModel):
    package   : Optional[str] = None
    is_active : Optional[int] = None
    email     : Optional[str] = None

@app.put("/api/admin/users/{user_id}")
async def admin_update_user(user_id: int, req: UpdateUserRequest, request: Request):
    _require_mansion(request)
    ok, err = DB.update_user(user_id, req.package, req.is_active, req.email)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True}


class ResetPasswordRequest(BaseModel):
    new_password: str

@app.put("/api/admin/users/{user_id}/reset-password")
async def admin_reset_password(user_id: int, req: ResetPasswordRequest, request: Request):
    _require_mansion(request)
    if len(req.new_password) < 4:
        raise HTTPException(status_code=400, detail="Password minimal 4 karakter.")
    ok, err = DB.reset_user_password(user_id, req.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True}


class SiteSettingsRequest(BaseModel):
    subscribe_terms: str = ""
    subscribe_howto: str = ""
    contact_wa     : str = ""

@app.get("/api/admin/settings")
async def admin_get_settings(request: Request):
    _require_owner(request)
    return DB.get_all_settings()

@app.put("/api/admin/settings")
async def admin_update_settings(req: SiteSettingsRequest, request: Request):
    _require_owner(request)
    DB.set_setting("subscribe_terms", req.subscribe_terms)
    DB.set_setting("subscribe_howto", req.subscribe_howto)
    DB.set_setting("contact_wa",      req.contact_wa)
    return {"ok": True}


@app.get("/api/admin/dashboard")
async def admin_dashboard(request: Request):
    _require_mansion(request)
    return DB.get_dashboard_stats()


@app.get("/api/admin/packages")
async def admin_get_packages(request: Request):
    _require_owner(request)
    pkgs = DB.get_packages()
    return {"packages": [
        {"key": k, **v} for k, v in pkgs.items()
    ]}


class UpdatePackageRequest(BaseModel):
    label        : str
    videos_limit : int
    max_duration : int
    price        : int

@app.put("/api/admin/packages/{key}")
async def admin_update_package(key: str, req: UpdatePackageRequest, request: Request):
    _require_owner(request)
    ok, err = DB.update_package(key, req.label.strip(), req.videos_limit, req.max_duration, req.price)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True, "key": key}


# ─────────────────────────────────────────────────────────────────────────────
# PAGE ROUTES
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return (STATIC_DIR / "login.html").read_text(encoding="utf-8")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # Serve app — client-side JS handles redirect if not logged in
    html_path = STATIC_DIR / "index.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return html_path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# RENDER SESSION
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/session")
async def create_render_session(request: Request):
    _require_user(request)
    sid = uuid.uuid4().hex[:8]
    session_dir = UPLOAD_DIR / sid
    session_dir.mkdir(parents=True, exist_ok=True)
    SESSIONS[sid] = {"status": "idle", "progress": 0, "message": "Session created", "output": ""}
    return {"sid": sid}


@app.post("/api/upload/{sid}")
async def upload_file(
    sid: str,
    request: Request,
    file: UploadFile = File(...),
    file_type: str = Form(...),  # "clip" | "photo" | "logo" | "bgm"
):
    _require_user(request)
    if sid not in SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found")
    session_dir = UPLOAD_DIR / sid
    safe_name   = file.filename.replace("..", "").replace("/", "_").replace("\\", "_")
    dest        = session_dir / f"{file_type}_{safe_name}"
    content     = await file.read()
    dest.write_bytes(content)
    return {"file_type": file_type, "path": str(dest), "name": safe_name, "size": len(content)}


@app.get("/api/fonts")
async def list_fonts():
    fonts = RE.scan_available_fonts()
    return {"fonts": [{"label": f["label"], "path": f["path"]} for f in fonts]}


# ── AI Spec ───────────────────────────────────────────────────────────────────
class AISpecRequest(BaseModel):
    sid               : str
    description       : str
    style_prompt      : str = ""
    n_captions        : int = 3
    clips             : list[dict]   # [{index, name, duration, score?}]
    user_api_key      : str = ""     # opsional — key milik user sebagai fallback
    user_key_provider : str = ""     # "gemini" | "anthropic"


@app.post("/api/ai-spec")
async def get_ai_spec(req: AISpecRequest, request: Request):
    user = _require_user(request)
    if not user["full_ai"]:
        raise HTTPException(status_code=403,
            detail=f"Paket {user['package_label']} tidak mendukung Full AI. Upgrade paket untuk menggunakan fitur ini.")
    if req.sid not in SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found")
    has_server_key = bool(os.getenv("GEMINI_API_KEY"))
    has_user_key   = bool(req.user_api_key.strip())
    if not has_server_key and not has_user_key:
        raise HTTPException(status_code=503,
            detail="Tidak ada API key tersedia. Set GEMINI_API_KEY di server atau masukkan key Anda sendiri.")
    try:
        fonts          = RE.scan_available_fonts()
        font_labels    = [f["label"].replace("📁 ", "") for f in fonts]
        raw_spec       = call_full_ai_spec(
            clips=req.clips,
            description=req.description,
            style_prompt=req.style_prompt,
            available_fonts=font_labels,
            n_captions=req.n_captions,
            user_api_key=req.user_api_key,
            user_key_provider=req.user_key_provider,
        )
        validated_spec = validate_and_fill(raw_spec, req.clips, req.n_captions)
        return {"spec": validated_spec}
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"AI menghasilkan format tidak valid. Coba lagi.")
    except QuotaExceededError as e:
        provider = str(e).capitalize()
        raise HTTPException(status_code=429, detail=(
            f"⚠️ Kuota server {provider} habis hari ini (reset jam 07:00 WIB). "
            f"Silakan masukkan API Key sendiri di kolom di bawah untuk melanjutkan."
        ))
    except InvalidKeyError as e:
        provider = str(e).capitalize()
        raise HTTPException(status_code=401, detail=(
            f"API Key {provider} tidak valid atau tidak memiliki akses. "
            f"Periksa kembali key Anda di {('aistudio.google.com' if 'gemini' in str(e).lower() else 'console.anthropic.com')}."
        ))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Render ────────────────────────────────────────────────────────────────────
class RenderRequest(BaseModel):
    # Session
    sid            : str

    # Files (paths relative to upload/sid/)
    clip_paths     : list[str] = []
    photo_paths    : list[str] = []
    logo_path      : str = ""
    bgm_path       : str = ""

    # Manual-only params (outside AI scope)
    bgm_volume     : float = 0.5
    orig_vol       : float = 0.8
    duration_target: int   = 30
    resolution     : str   = "720p  (720×1280) Best"

    # CTA
    cta_label      : str   = "Hubungi :"
    cta_nama       : str   = ""
    cta_wa         : str   = ""
    cta_dur        : int   = 4

    # Full AI spec (if used)
    ai_spec        : Optional[dict] = None

    # Manual fallback (used when ai_spec is None)
    description    : str   = ""
    n_captions     : int   = 3
    caption_align  : str   = "Center"
    detail_colors  : list  = []        # ["White","Silver",...]
    font_path      : str   = ""
    transition     : str   = "Crossfade"
    fade_dur       : float = 0.4
    do_grade       : bool  = False
    brightness     : float = 1.05
    contrast       : float = 1.10
    saturation     : float = 1.05
    sharpness      : float = 1.10


def _resolve_path(sid: str, p: str) -> str:
    """Return absolute path for an upload. p may already be absolute."""
    if os.path.isabs(p) and os.path.exists(p):
        return p
    candidate = str(UPLOAD_DIR / sid / p)
    return candidate if os.path.exists(candidate) else p


RESOLUTION_MAP = {
    "360p"  : (202, 360),
    "720p"  : (720, 1280),
    "1080p" : (1080, 1920),
}


def _parse_resolution(res_str: str):
    for key, wh in RESOLUTION_MAP.items():
        if res_str.startswith(key):
            return wh
    return (720, 1280)


def _do_render(sid: str, req: RenderRequest):
    """Background render task."""
    from moviepy import VideoFileClip, concatenate_videoclips
    from moviepy.video.fx import FadeIn, FadeOut
    import shutil as _shutil

    session = SESSIONS[sid]

    def update(msg: str, progress: int):
        session["message"] = msg
        session["progress"] = progress
        logger.info(f"[{sid}] {msg}")

    try:
        session["status"] = "rendering"
        update("Memulai render...", 5)

        out_w, out_h = _parse_resolution(req.resolution)

        # ── Logo ──────────────────────────────────────────────────────────────
        logo_pil = None
        if req.logo_path:
            lp = _resolve_path(sid, req.logo_path)
            if os.path.exists(lp):
                from PIL import Image
                logo_pil = Image.open(lp).convert("RGBA")

        # ── AI spec or manual params ──────────────────────────────────────────
        spec      = req.ai_spec or {}
        use_ai    = bool(spec)
        ai_caps   = spec.get("captions") if use_ai else None
        do_grade  = spec["color_grade"]["enabled"]  if use_ai and "color_grade" in spec else req.do_grade
        brightness = spec["color_grade"]["brightness"] if use_ai and "color_grade" in spec else req.brightness
        contrast   = spec["color_grade"]["contrast"]   if use_ai and "color_grade" in spec else req.contrast
        saturation = spec["color_grade"]["saturation"] if use_ai and "color_grade" in spec else req.saturation
        sharpness  = spec["color_grade"]["sharpness"]  if use_ai and "color_grade" in spec else req.sharpness
        t_type    = spec.get("transition", {}).get("type",     req.transition) if use_ai else req.transition
        t_dur     = spec.get("transition", {}).get("duration", req.fade_dur)   if use_ai else req.fade_dur
        font_path = spec.get("font", req.font_path) if use_ai else req.font_path
        if font_path:
            font_path = RE.get_font_path(font_path) or font_path

        # ── Detail colors (manual mode) ───────────────────────────────────────
        color_names  = req.detail_colors or ["White", "Silver", "Champagne"]
        detail_colors = [RE.COLOR_NAME_TO_RGB.get(c, (255,255,255)) for c in color_names]

        # ── Collect clips ─────────────────────────────────────────────────────
        open_clips, segments = [], []

        if req.clip_paths:
            update("Loading video clips...", 10)
            # Apply AI trim if available
            trim_map = spec.get("trim", {}) if use_ai else {}
            order    = spec.get("segment_order", list(range(len(req.clip_paths)))) if use_ai else list(range(len(req.clip_paths)))

            loaded_clips = {}
            for idx, cp in enumerate(req.clip_paths):
                abs_cp = _resolve_path(sid, cp)
                if not os.path.exists(abs_cp):
                    continue
                vc = VideoFileClip(abs_cp)
                open_clips.append(vc)
                loaded_clips[idx] = vc

            if use_ai and trim_map:
                # Use AI-specified order and trim
                for rank, idx in enumerate(order):
                    vc = loaded_clips.get(idx)
                    if vc is None: continue
                    key = str(idx)
                    t   = trim_map.get(key, {})
                    s   = float(t.get("start", 0.5))
                    e   = float(t.get("end",   min(s+5.0, vc.duration-0.3)))
                    s   = max(0.0, min(s, vc.duration-1.0))
                    e   = max(s+1.0, min(e, vc.duration))
                    segments.append(vc.subclipped(s, e))
            else:
                # Smart cut
                raw_segs = RE.smart_cut_clips(
                    [loaded_clips[i] for i in sorted(loaded_clips.keys())],
                    req.duration_target,
                )
                for seg in raw_segs:
                    vc = loaded_clips.get(seg["src_idx"])
                    if vc: segments.append(vc.subclipped(seg["start"], seg["end"]))

        elif req.photo_paths:
            update("Building photo slideshow...", 10)
            abs_photos = [_resolve_path(sid, p) for p in req.photo_paths if os.path.exists(_resolve_path(sid, p))]
            if abs_photos:
                slide = RE.build_photo_slideshow(abs_photos, req.duration_target, out_w, out_h)
                segments = [slide]

        if not segments:
            raise ValueError("No valid clips or photos to render.")

        update("Fitting clips to 9:16...", 20)
        fitted = [RE.fit_to_916(c, out_w, out_h) for c in segments]

        # ── Pass 1: concat + logo ─────────────────────────────────────────────
        update("Pass 1: assembling clips...", 30)
        if t_type == "Crossfade":
            combined = RE.crossfade_concat(fitted, t_dur)
        elif t_type == "Fade to Black":
            faded = []
            for i, c in enumerate(fitted):
                fx = []
                if i > 0:           fx.append(FadeIn(t_dur))
                if i < len(fitted)-1: fx.append(FadeOut(t_dur))
                faded.append(c.with_effects(fx) if fx else c)
            combined = concatenate_videoclips(faded, method="chain")
        else:
            combined = concatenate_videoclips(fitted, method="chain")

        pass1_path = str(OUTPUT_DIR / f"pass1_{sid}.mp4")
        combined.write_videofile(
            pass1_path, codec="libx264", audio_codec="aac", fps=24,
            ffmpeg_params=["-pix_fmt", "yuv420p"], logger=None,
        )

        for oc in open_clips:
            try: oc.close()
            except Exception: pass
        gc.collect()

        # ── Pass 2: captions + CTA + grading ─────────────────────────────────
        update("Pass 2: adding captions and effects...", 60)
        out_path = str(OUTPUT_DIR / f"out_{sid}.mp4")
        bgm_abs  = _resolve_path(sid, req.bgm_path) if req.bgm_path else ""

        is_trial    = session.get("package") == "trial"
        watermark   = "VieCut" if is_trial else ""

        ok, captions, err = RE.run_pass2(
            pass1_path=pass1_path,
            out_path=out_path,
            deskripsi=req.description,
            n_caption=req.n_captions,
            detail_colors=detail_colors,
            cta_nama=req.cta_nama,
            cta_wa=req.cta_wa,
            cta_dur=req.cta_dur,
            cta_label=req.cta_label,
            do_grade=do_grade,
            brightness=brightness,
            contrast=contrast,
            saturation=saturation,
            sharpness=sharpness,
            bgm_path=bgm_abs,
            bgm_volume=req.bgm_volume,
            orig_vol=req.orig_vol,
            OUT_W=out_w,
            OUT_H=out_h,
            logo_pil=logo_pil,
            caption_align=req.caption_align,
            font_path=font_path,
            session_id=sid,
            status_cb=lambda m: update(m, session["progress"]),
            ai_captions=ai_caps,
            watermark_text=watermark,
        )

        if not ok:
            raise RuntimeError(err)

        # cleanup pass1
        try: os.remove(pass1_path)
        except Exception: pass

        session["status"]   = "done"
        session["output"]   = out_path
        session["progress"] = 100
        session["message"]  = "Render selesai!"
        update("✅ Render selesai!", 100)

    except Exception as e:
        session["status"]  = "error"
        session["message"] = str(e)
        logger.error(f"[{sid}] Render error: {e}")
        gc.collect()


@app.post("/api/render/{sid}")
async def start_render(sid: str, req: RenderRequest, background_tasks: BackgroundTasks,
                       request: Request):
    user = _require_user(request)
    if sid not in SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found")
    if SESSIONS[sid].get("status") == "rendering":
        raise HTTPException(status_code=409, detail="Render already in progress")

    # ── Quota check (non-mansion team) ────────────────────────────────────────
    if user["user_type"] not in ("mansion_team", "owner"):
        used, limit = DB.get_video_usage(user["id"])
        if limit != -1 and used >= limit:
            pkg = DB.PACKAGES.get(user["package"], {})
            raise HTTPException(
                status_code=403,
                detail=f"⚠️ Paket {pkg.get('label','Anda')} sudah habis ({used}/{limit} video bulan ini). "
                       f"Upgrade paket untuk melanjutkan.",
            )

    # ── Trial duration cap ────────────────────────────────────────────────────
    max_dur = user.get("max_duration", 60)
    req.duration_target = min(req.duration_target, max_dur)

    req.sid = sid
    # Simpan user_id di session untuk increment saat download
    SESSIONS[sid].update({
        "status": "rendering", "progress": 0,
        "message": "Queued...", "output": "",
        "user_id": user["id"],
        "user_type": user["user_type"],
        "package": user["package"],
    })
    background_tasks.add_task(_do_render, sid, req)
    return {"sid": sid, "status": "rendering"}


@app.get("/api/status/{sid}")
async def get_status(sid: str, request: Request):
    _require_user(request)
    if sid not in SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found")
    s = SESSIONS[sid]
    return {
        "status"    : s.get("status",   "idle"),
        "progress"  : s.get("progress",  0),
        "message"   : s.get("message",  ""),
        "has_output": bool(s.get("output") and os.path.exists(s["output"])),
    }


@app.get("/api/download/{sid}")
async def download_video(sid: str, request: Request):
    user = _require_user(request)
    if sid not in SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found")
    out = SESSIONS[sid].get("output", "")
    if not out or not os.path.exists(out):
        raise HTTPException(status_code=404, detail="Output not ready")

    # ── Increment video count on download (non-mansion) ───────────────────────
    sess_user_id = SESSIONS[sid].get("user_id")
    if sess_user_id and user["user_type"] not in ("mansion_team", "owner"):
        if not SESSIONS[sid].get("counted"):
            DB.increment_video_usage(sess_user_id)
            SESSIONS[sid]["counted"] = True   # jangan hitung dua kali

    return FileResponse(out, media_type="video/mp4", filename=f"mansion_video_{sid}.mp4")


@app.delete("/api/session/{sid}")
async def delete_session(sid: str, request: Request):
    _require_user(request)
    if sid not in SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found")
    # Cleanup files
    session_dir = UPLOAD_DIR / sid
    if session_dir.exists():
        shutil.rmtree(str(session_dir), ignore_errors=True)
    out = SESSIONS[sid].get("output", "")
    if out and os.path.exists(out):
        try: os.remove(out)
        except Exception: pass
    del SESSIONS[sid]
    return {"deleted": sid}
