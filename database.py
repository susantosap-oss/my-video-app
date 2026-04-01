"""
database.py — Firestore user & session management
"""
import hashlib
from datetime import datetime, timezone

from google.cloud import firestore
from google.cloud.firestore_v1 import FieldFilter

# ── Firestore client (lazy init) ──────────────────────────────────────────────
_db: firestore.Client | None = None

def _get_db() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client()
    return _db

# ── Collections ───────────────────────────────────────────────────────────────
COL_USERS    = "users"
COL_SESSIONS = "sessions"
COL_PACKAGES = "packages"
COL_SETTINGS = "site_settings"

# ── Package definitions ───────────────────────────────────────────────────────
DEFAULT_PACKAGES = {
    "unlimited": {"label": "Tim Mansion",  "videos_limit": -1, "max_duration": 60, "full_ai": True,  "price": 0},
    "trial":     {"label": "Trial",        "videos_limit": -1, "max_duration": 10, "full_ai": False, "price": 0},
    "basic":     {"label": "Basic",        "videos_limit":  5, "max_duration": 60, "full_ai": True,  "price": 25000},
    "lite":      {"label": "Lite",         "videos_limit": 15, "max_duration": 60, "full_ai": True,  "price": 50000},
    "pro":       {"label": "Pro",          "videos_limit": 25, "max_duration": 60, "full_ai": True,  "price": 75000},
}

# Module-level cache (refreshed from Firestore after init)
PACKAGES: dict = dict(DEFAULT_PACKAGES)


def hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# ── Init / Seed ───────────────────────────────────────────────────────────────
def init_db():
    db = _get_db()

    # Seed packages (INSERT OR IGNORE equivalent)
    for key, p in DEFAULT_PACKAGES.items():
        ref = db.collection(COL_PACKAGES).document(key)
        if not ref.get().exists:
            ref.set({**p, "full_ai": bool(p["full_ai"])})

    # Seed site settings
    for k, v in [
        ("subscribe_terms",  "• Pembayaran dilakukan di awal masa berlangganan\n• Paket berlaku 1 bulan kalender\n• Tidak ada refund setelah akun diaktifkan"),
        ("subscribe_howto",  "1. Pilih paket yang sesuai\n2. Transfer ke rekening yang diberikan\n3. Kirim bukti transfer via WA\n4. Akun akan diaktifkan dalam 1x24 jam"),
        ("contact_wa",       "+62 081703133252"),
    ]:
        ref = db.collection(COL_SETTINGS).document(k)
        if not ref.get().exists:
            ref.set({"value": v})

    # Seed users
    _seed("Admin",       "adnin098765", "owner",        "unlimited", "")
    _seed("Mansion tim", "mansion2026", "mansion_team", "unlimited", "tim@mansion.id")
    _seed("Trial",       "Trial",       "trial",        "trial",     "")

    _reload_packages()


def _seed(username: str, password: str, user_type: str, package: str, email: str):
    db  = _get_db()
    ref = db.collection(COL_USERS).document(username)
    if not ref.get().exists:
        ref.set({
            "id"           : username,
            "username"     : username,
            "password_hash": hash_pw(password),
            "email"        : email,
            "user_type"    : user_type,
            "package"      : package,
            "videos_used"  : 0,
            "billing_month": "",
            "is_active"    : True,
            "created_at"   : datetime.now(timezone.utc).isoformat(),
        })


# ── Package queries ───────────────────────────────────────────────────────────
def get_packages() -> dict:
    db   = _get_db()
    docs = db.collection(COL_PACKAGES).stream()
    pkgs = {d.id: d.to_dict() for d in docs}
    return pkgs if pkgs else dict(DEFAULT_PACKAGES)


def update_package(key: str, label: str, videos_limit: int, max_duration: int, price: int) -> tuple[bool, str]:
    db  = _get_db()
    ref = db.collection(COL_PACKAGES).document(key)
    if not ref.get().exists:
        return False, "Package tidak ditemukan"
    ref.update({"label": label, "videos_limit": videos_limit,
                 "max_duration": max_duration, "price": price})
    _reload_packages()
    return True, ""


def _reload_packages():
    global PACKAGES
    PACKAGES.clear()
    PACKAGES.update(get_packages())


# ── Site settings ─────────────────────────────────────────────────────────────
def get_setting(key: str, default: str = "") -> str:
    doc = _get_db().collection(COL_SETTINGS).document(key).get()
    return doc.to_dict().get("value", default) if doc.exists else default


def set_setting(key: str, value: str):
    _get_db().collection(COL_SETTINGS).document(key).set({"value": value})


def get_all_settings() -> dict:
    docs = _get_db().collection(COL_SETTINGS).stream()
    return {d.id: d.to_dict().get("value", "") for d in docs}


# ── User queries ──────────────────────────────────────────────────────────────
def get_user_by_username(username: str) -> dict | None:
    doc = _get_db().collection(COL_USERS).document(username).get()
    return doc.to_dict() if doc.exists else None


def get_user_by_id(user_id: str) -> dict | None:
    # user_id == username (doc ID)
    return get_user_by_username(user_id)


def update_user(user_id: str, package: str = None, is_active: int = None, email: str = None) -> tuple[bool, str]:
    db  = _get_db()
    ref = db.collection(COL_USERS).document(user_id)
    if not ref.get().exists:
        return False, "User tidak ditemukan"
    updates = {}
    if package is not None:
        if package not in PACKAGES:
            return False, "Package tidak valid"
        updates["package"] = package
    if is_active is not None:
        updates["is_active"] = bool(is_active)
    if email is not None:
        updates["email"] = email
    if updates:
        ref.update(updates)
    return True, ""


def reset_user_password(user_id: str, new_password: str) -> tuple[bool, str]:
    db  = _get_db()
    ref = db.collection(COL_USERS).document(user_id)
    if not ref.get().exists:
        return False, "User tidak ditemukan"
    ref.update({"password_hash": hash_pw(new_password)})
    return True, ""


def add_subscriber(username: str, password: str, email: str, package: str) -> tuple[bool, str]:
    if package not in PACKAGES:
        return False, "Package tidak valid"
    db  = _get_db()
    ref = db.collection(COL_USERS).document(username)
    if ref.get().exists:
        return False, "Username sudah dipakai"
    ref.set({
        "id"           : username,
        "username"     : username,
        "password_hash": hash_pw(password),
        "email"        : email,
        "user_type"    : "subscriber",
        "package"      : package,
        "videos_used"  : 0,
        "billing_month": "",
        "is_active"    : True,
        "created_at"   : datetime.now(timezone.utc).isoformat(),
    })
    return True, ""


def list_users() -> list[dict]:
    docs = _get_db().collection(COL_USERS).stream()
    return [d.to_dict() for d in docs]


# ── Session queries ───────────────────────────────────────────────────────────
def create_session(user_id: str, token: str, expires_at: str):
    db = _get_db()
    # Hapus session lama user yang sama
    old = db.collection(COL_SESSIONS).where(
        filter=FieldFilter("user_id", "==", user_id)
    ).stream()
    for doc in old:
        doc.reference.delete()
    db.collection(COL_SESSIONS).document(token).set({
        "user_id"   : user_id,
        "expires_at": expires_at,
    })


def get_session(token: str) -> dict | None:
    db  = _get_db()
    doc = db.collection(COL_SESSIONS).document(token).get()
    if not doc.exists:
        return None
    data  = doc.to_dict()
    # Check expiry (stored as "YYYY-MM-DD HH:MM:SS" local time)
    try:
        exp = datetime.strptime(data["expires_at"], "%Y-%m-%d %H:%M:%S")
        if exp < datetime.now():
            doc.reference.delete()
            return None
    except Exception:
        pass
    return get_user_by_username(data["user_id"])


def delete_session(token: str):
    _get_db().collection(COL_SESSIONS).document(token).delete()


# ── Video quota ───────────────────────────────────────────────────────────────
def get_video_usage(user_id: str) -> tuple[int, int]:
    current_month = datetime.now().strftime("%Y-%m")
    user = get_user_by_id(user_id)
    if not user:
        return 0, 0
    pkg   = PACKAGES.get(user["package"], PACKAGES["trial"])
    limit = pkg["videos_limit"]
    used  = user["videos_used"] if user.get("billing_month") == current_month else 0
    return used, limit


def increment_video_usage(user_id: str):
    current_month = datetime.now().strftime("%Y-%m")
    db  = _get_db()
    ref = db.collection(COL_USERS).document(user_id)
    user = ref.get().to_dict()
    if not user:
        return
    if user.get("billing_month") != current_month:
        ref.update({"videos_used": 1, "billing_month": current_month})
    else:
        ref.update({"videos_used": firestore.Increment(1)})


# ── Dashboard ─────────────────────────────────────────────────────────────────
def get_dashboard_stats() -> dict:
    current_month = datetime.now().strftime("%Y-%m")
    SYSTEM_TYPES  = {"owner", "mansion_team"}
    users = [u for u in list_users() if u.get("user_type") not in SYSTEM_TYPES]

    total_active   = sum(1 for u in users if u.get("is_active"))
    total_inactive = sum(1 for u in users if not u.get("is_active"))
    new_this_month = sum(1 for u in users if (u.get("created_at", "") or "").startswith(current_month[:7]))
    total_videos   = sum(
        u.get("videos_used", 0) for u in users
        if u.get("billing_month") == current_month
    )

    # Breakdown per package
    pkg_map: dict[str, dict] = {}
    for u in users:
        key = u.get("package", "trial")
        if key not in pkg_map:
            pkg_map[key] = {"total": 0, "active": 0, "videos": 0}
        pkg_map[key]["total"] += 1
        if u.get("is_active"):
            pkg_map[key]["active"] += 1
        if u.get("billing_month") == current_month:
            pkg_map[key]["videos"] += u.get("videos_used", 0)

    pkgs = get_packages()
    by_package = [
        {
            "key"   : key,
            "label" : pkgs.get(key, {}).get("label", key),
            "total" : v["total"],
            "active": v["active"],
            "videos": v["videos"],
        }
        for key, v in sorted(pkg_map.items())
    ]

    # Top 10 users by videos this month
    active_users = [u for u in users if u.get("billing_month") == current_month and u.get("videos_used", 0) > 0]
    top_users = sorted(active_users, key=lambda u: u.get("videos_used", 0), reverse=True)[:10]

    return {
        "month"         : current_month,
        "total_active"  : total_active,
        "total_inactive": total_inactive,
        "new_this_month": new_this_month,
        "total_videos"  : int(total_videos),
        "by_package"    : by_package,
        "top_users"     : [
            {
                "username": u["username"],
                "package" : pkgs.get(u["package"], {}).get("label", u["package"]),
                "videos"  : u.get("videos_used", 0),
            }
            for u in top_users
        ],
    }
