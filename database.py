"""
database.py — SQLite user & session management
"""
import sqlite3, hashlib
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "vidgen_users.db"

# ── Package definitions (default/fallback) ────────────────────────────────────
DEFAULT_PACKAGES = {
    "unlimited": {"label": "Tim Mansion",  "videos_limit": -1, "max_duration": 60, "full_ai": True,  "price": 0},
    "trial":     {"label": "Trial",        "videos_limit": -1, "max_duration": 10, "full_ai": False, "price": 0},
    "basic":     {"label": "Basic",        "videos_limit":  5, "max_duration": 60, "full_ai": True,  "price": 25000},
    "lite":      {"label": "Lite",         "videos_limit": 15, "max_duration": 60, "full_ai": True,  "price": 50000},
    "pro":       {"label": "Pro",          "videos_limit": 25, "max_duration": 60, "full_ai": True,  "price": 75000},
}

# Backward-compat alias — always reflects DB state after init_db()
PACKAGES = dict(DEFAULT_PACKAGES)


def hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            email         TEXT    DEFAULT '',
            user_type     TEXT    DEFAULT 'subscriber',
            package       TEXT    DEFAULT 'trial',
            videos_used   INTEGER DEFAULT 0,
            billing_month TEXT    DEFAULT '',
            is_active     INTEGER DEFAULT 1,
            created_at    TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token      TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL,
            expires_at TEXT    NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS site_settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS packages (
            key          TEXT PRIMARY KEY,
            label        TEXT    NOT NULL,
            videos_limit INTEGER NOT NULL,
            max_duration INTEGER NOT NULL,
            full_ai      INTEGER NOT NULL DEFAULT 1,
            price        INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.commit()

    # Seed default site settings
    for k, v in [
        ("subscribe_terms",  "• Pembayaran dilakukan di awal masa berlangganan\n• Paket berlaku 1 bulan kalender\n• Tidak ada refund setelah akun diaktifkan"),
        ("subscribe_howto",  "1. Pilih paket yang sesuai\n2. Transfer ke rekening yang diberikan\n3. Kirim bukti transfer via WA\n4. Akun akan diaktifkan dalam 1x24 jam"),
        ("contact_wa",       "+62 081703133252"),
    ]:
        conn.execute("INSERT OR IGNORE INTO site_settings (key,value) VALUES (?,?)", (k, v))
    conn.commit()

    # Seed packages from defaults (INSERT OR IGNORE — keeps existing edits)
    for key, p in DEFAULT_PACKAGES.items():
        conn.execute(
            "INSERT OR IGNORE INTO packages (key,label,videos_limit,max_duration,full_ai,price) VALUES (?,?,?,?,?,?)",
            (key, p["label"], p["videos_limit"], p["max_duration"], int(p["full_ai"]), p["price"]),
        )
    conn.commit()

    # Seed default users (INSERT OR IGNORE — safe to call every startup)
    _seed(conn, "Admin",       "adnin098765", "owner",        "unlimited", "")
    _seed(conn, "Mansion tim", "mansion2026", "mansion_team", "unlimited", "tim@mansion.id")
    _seed(conn, "Trial",       "Trial",       "trial",        "trial",     "")
    conn.close()

    # Refresh module-level PACKAGES from DB
    _reload_packages()


def _seed(conn, username, password, user_type, package, email):
    conn.execute(
        "INSERT OR IGNORE INTO users (username,password_hash,email,user_type,package) VALUES (?,?,?,?,?)",
        (username, hash_pw(password), email, user_type, package),
    )
    conn.commit()


# ── Package queries ───────────────────────────────────────────────────────────
def get_packages() -> dict:
    """Read packages from DB. Returns same format as DEFAULT_PACKAGES."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM packages").fetchall()
    conn.close()
    if not rows:
        return dict(DEFAULT_PACKAGES)
    return {
        r["key"]: {
            "label"       : r["label"],
            "videos_limit": r["videos_limit"],
            "max_duration": r["max_duration"],
            "full_ai"     : bool(r["full_ai"]),
            "price"       : r["price"],
        }
        for r in rows
    }


def update_package(key: str, label: str, videos_limit: int, max_duration: int, price: int) -> tuple[bool, str]:
    """Update editable fields of a package. Returns (success, error_msg)."""
    conn = get_conn()
    cur = conn.execute("SELECT key FROM packages WHERE key=?", (key,)).fetchone()
    if not cur:
        conn.close()
        return False, "Package tidak ditemukan"
    conn.execute(
        "UPDATE packages SET label=?, videos_limit=?, max_duration=?, price=? WHERE key=?",
        (label, videos_limit, max_duration, price, key),
    )
    conn.commit()
    conn.close()
    _reload_packages()
    return True, ""


def get_setting(key: str, default: str = "") -> str:
    conn = get_conn()
    row  = conn.execute("SELECT value FROM site_settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO site_settings (key,value) VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()

def get_all_settings() -> dict:
    conn  = get_conn()
    rows  = conn.execute("SELECT key, value FROM site_settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


def _reload_packages():
    """Refresh module-level PACKAGES dict from DB."""
    global PACKAGES
    PACKAGES.clear()
    PACKAGES.update(get_packages())


# ── Dashboard ─────────────────────────────────────────────────────────────────
def get_dashboard_stats() -> dict:
    """Aggregate stats from existing tables — no extra schema needed."""
    current_month = datetime.now().strftime("%Y-%m")
    conn = get_conn()

    # Subscriber only (exclude system accounts)
    SYSTEM_TYPES = ("owner", "mansion_team")

    # Total active subscribers
    total_active = conn.execute(
        "SELECT COUNT(*) FROM users WHERE user_type NOT IN (?,?) AND is_active=1",
        SYSTEM_TYPES,
    ).fetchone()[0]

    total_inactive = conn.execute(
        "SELECT COUNT(*) FROM users WHERE user_type NOT IN (?,?) AND is_active=0",
        SYSTEM_TYPES,
    ).fetchone()[0]

    # New subscribers this month
    new_this_month = conn.execute(
        "SELECT COUNT(*) FROM users WHERE user_type NOT IN (?,?) AND strftime('%Y-%m', created_at)=?",
        (*SYSTEM_TYPES, current_month),
    ).fetchone()[0]

    # Total videos rendered this month (sum across all non-system users)
    total_videos = conn.execute(
        "SELECT COALESCE(SUM(videos_used),0) FROM users WHERE user_type NOT IN (?,?) AND billing_month=?",
        (*SYSTEM_TYPES, current_month),
    ).fetchone()[0]

    # Breakdown per package
    pkg_rows = conn.execute(
        """SELECT package,
                  COUNT(*) as total,
                  SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) as active,
                  COALESCE(SUM(CASE WHEN billing_month=? THEN videos_used ELSE 0 END),0) as videos
           FROM users WHERE user_type NOT IN (?,?)
           GROUP BY package ORDER BY package""",
        (current_month, *SYSTEM_TYPES),
    ).fetchall()

    # Top 10 users by videos this month
    top_users = conn.execute(
        """SELECT username, package, videos_used, billing_month
           FROM users WHERE user_type NOT IN (?,?) AND billing_month=? AND videos_used > 0
           ORDER BY videos_used DESC LIMIT 10""",
        (*SYSTEM_TYPES, current_month),
    ).fetchall()

    conn.close()

    pkgs = get_packages()
    return {
        "month"         : current_month,
        "total_active"  : total_active,
        "total_inactive": total_inactive,
        "new_this_month": new_this_month,
        "total_videos"  : int(total_videos),
        "by_package"    : [
            {
                "key"   : r["package"],
                "label" : pkgs.get(r["package"], {}).get("label", r["package"]),
                "total" : r["total"],
                "active": r["active"],
                "videos": r["videos"],
            }
            for r in pkg_rows
        ],
        "top_users": [
            {
                "username": r["username"],
                "package" : pkgs.get(r["package"], {}).get("label", r["package"]),
                "videos"  : r["videos_used"],
            }
            for r in top_users
        ],
    }


# ── User queries ──────────────────────────────────────────────────────────────
def get_user_by_username(username: str) -> dict | None:
    conn = get_conn()
    row  = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    conn = get_conn()
    row  = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_user(user_id: int, package: str = None, is_active: int = None, email: str = None) -> tuple[bool, str]:
    """Update subscriber fields. Pass only the fields to change."""
    conn = get_conn()
    row = conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        conn.close()
        return False, "User tidak ditemukan"
    fields, vals = [], []
    if package is not None:
        if package not in PACKAGES:
            conn.close()
            return False, "Package tidak valid"
        fields.append("package=?"); vals.append(package)
    if is_active is not None:
        fields.append("is_active=?"); vals.append(is_active)
    if email is not None:
        fields.append("email=?"); vals.append(email)
    if fields:
        vals.append(user_id)
        conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id=?", vals)
        conn.commit()
    conn.close()
    return True, ""


def reset_user_password(user_id: int, new_password: str) -> tuple[bool, str]:
    conn = get_conn()
    row = conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        conn.close()
        return False, "User tidak ditemukan"
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_pw(new_password), user_id))
    conn.commit()
    conn.close()
    return True, ""


def add_subscriber(username: str, password: str, email: str, package: str) -> tuple[bool, str]:
    """Add a new subscriber. Returns (success, error_msg)."""
    if package not in PACKAGES:
        return False, "Package tidak valid"
    try:
        conn = get_conn()
        conn.execute(
            "INSERT INTO users (username,password_hash,email,user_type,package) VALUES (?,?,?,?,?)",
            (username, hash_pw(password), email, "subscriber", package),
        )
        conn.commit()
        conn.close()
        return True, ""
    except sqlite3.IntegrityError:
        return False, "Username sudah dipakai"
    except Exception as e:
        return False, str(e)


def list_users() -> list[dict]:
    conn  = get_conn()
    rows  = conn.execute("SELECT id,username,email,user_type,package,videos_used,billing_month,is_active,created_at FROM users").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Session queries ───────────────────────────────────────────────────────────
def create_session(user_id: int, token: str, expires_at: str):
    conn = get_conn()
    # Hapus session lama user yang sama
    conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    conn.execute("INSERT INTO sessions VALUES (?,?,?)", (token, user_id, expires_at))
    conn.commit()
    conn.close()


def get_session(token: str) -> dict | None:
    conn = get_conn()
    row  = conn.execute(
        """SELECT s.token, u.*
           FROM sessions s JOIN users u ON s.user_id=u.id
           WHERE s.token=? AND s.expires_at > datetime('now')""",
        (token,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_session(token: str):
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    conn.commit()
    conn.close()


# ── Video quota ───────────────────────────────────────────────────────────────
def get_video_usage(user_id: int) -> tuple[int, int]:
    """Returns (videos_used_this_month, limit). -1 limit = unlimited."""
    current_month = datetime.now().strftime("%Y-%m")
    conn = get_conn()
    row  = conn.execute("SELECT videos_used, billing_month, package FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return 0, 0
    pkg   = PACKAGES.get(row["package"], PACKAGES["trial"])
    limit = pkg["videos_limit"]
    used  = row["videos_used"] if row["billing_month"] == current_month else 0
    return used, limit


def increment_video_usage(user_id: int):
    current_month = datetime.now().strftime("%Y-%m")
    conn = get_conn()
    row  = conn.execute("SELECT billing_month FROM users WHERE id=?", (user_id,)).fetchone()
    if row:
        if row["billing_month"] != current_month:
            conn.execute("UPDATE users SET videos_used=1, billing_month=? WHERE id=?", (current_month, user_id))
        else:
            conn.execute("UPDATE users SET videos_used=videos_used+1 WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
