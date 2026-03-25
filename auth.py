"""
auth.py — Session-based authentication
"""
import secrets
from datetime import datetime, timedelta
from database import (
    get_user_by_username, create_session, get_session,
    delete_session, hash_pw, PACKAGES,
)

SESSION_DAYS = 7


def login(username: str, password: str) -> dict | None:
    """Validate credentials. Returns {token, user} or None."""
    user = get_user_by_username(username)
    if not user or not user["is_active"]:
        return None
    if user["password_hash"] != hash_pw(password):
        return None

    token      = secrets.token_urlsafe(32)
    expires_at = (datetime.now() + timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    create_session(user["id"], token, expires_at)
    return {"token": token, "user": build_user_info(user)}


def get_current_user(token: str) -> dict | None:
    """Return user dict from token, or None if invalid/expired."""
    if not token:
        return None
    row = get_session(token)
    return build_user_info(row) if row else None


def logout(token: str):
    delete_session(token)


def build_user_info(user: dict) -> dict:
    """Safe user info dict — no password hash."""
    package  = user.get("package", "trial")
    pkg      = PACKAGES.get(package, PACKAGES["trial"])
    utype = user.get("user_type", "subscriber")
    return {
        "id"             : user.get("id"),
        "username"       : user["username"],
        "email"          : user.get("email", ""),
        "user_type"      : utype,
        "package"        : package,
        "package_label"  : pkg["label"],
        "videos_limit"   : pkg["videos_limit"],
        "max_duration"   : pkg["max_duration"],
        "full_ai"        : pkg["full_ai"],
        "price"          : pkg["price"],
        "is_mansion_team": utype in ("mansion_team", "owner"),
        "is_owner"       : utype == "owner",
    }
