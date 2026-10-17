"""Simple login: users with PBKDF2-hashed passwords + HMAC-signed session cookie.

Users live in users.json (only hashes, safe to commit). Manage them with manage_users.py.
SECRET_KEY signs the session cookie; if unset, a random one is generated at startup
(everyone gets logged out when the server restarts).
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional

USERS_FILE = Path(__file__).resolve().parent.parent / "users.json"
SECRET_KEY = (os.environ.get("SECRET_KEY") or secrets.token_hex(32)).encode()
COOKIE_NAME = "po_sim_session"
SESSION_SECONDS = 12 * 3600
PBKDF2_ITERATIONS = 200_000


# --------------------------------------------------------------------------
# Password hashing
# --------------------------------------------------------------------------
def hash_password(password: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def load_users() -> dict:
    if not USERS_FILE.exists():
        return {}
    return json.loads(USERS_FILE.read_text(encoding="utf-8"))


def authenticate(email: str, password: str) -> Optional[str]:
    """Returns the normalized email if the credentials are valid."""
    email = email.strip().lower()
    stored = load_users().get(email)
    # Hash anyway when the user doesn't exist, so timing doesn't reveal valid emails
    ok = verify_password(password, stored or hash_password("x"))
    return email if stored and ok else None


# --------------------------------------------------------------------------
# Session cookie: base64(email|expiry).signature
# --------------------------------------------------------------------------
def _sign(data: str) -> str:
    return hmac.new(SECRET_KEY, data.encode(), hashlib.sha256).hexdigest()


def make_session(email: str) -> str:
    data = base64.urlsafe_b64encode(f"{email}|{int(time.time()) + SESSION_SECONDS}".encode()).decode()
    return f"{data}.{_sign(data)}"


def read_session(token: Optional[str]) -> Optional[str]:
    """Returns the email in a valid, unexpired session cookie (and the user still exists)."""
    if not token or "." not in token:
        return None
    data, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(data)):
        return None
    try:
        email, expiry = base64.urlsafe_b64decode(data).decode().rsplit("|", 1)
    except (ValueError, UnicodeDecodeError):
        return None
    if int(expiry) < time.time() or email not in load_users():
        return None
    return email
