"""
Stateless session manager for Google Cloud Run / serverless deployment.
Uses Fernet symmetric encryption and HMAC-SHA256 signatures to store OAuth
tokens in secure, encrypted, HttpOnly cookies without needing Redis or a SQL database.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional, Tuple
from cryptography.fernet import Fernet, InvalidToken


SESSION_COOKIE_NAME = "nbf_session"
CSRF_COOKIE_NAME = "nbf_csrf"

# Load secret key from environment or generate a stable local development key
_ENV_SECRET = os.getenv("SESSION_SECRET_KEY", "").strip()
if _ENV_SECRET:
    # Ensure key is valid 32-byte urlsafe base64 for Fernet
    _key_bytes = hashlib.sha256(_ENV_SECRET.encode("utf-8")).digest()
    FERNET_KEY = base64.urlsafe_b64encode(_key_bytes)
else:
    # Fallback key for local dev only (in production, SESSION_SECRET_KEY should be set)
    _default_bytes = hashlib.sha256(b"notebookflow-dev-secret-key-change-in-production").digest()
    FERNET_KEY = base64.urlsafe_b64encode(_default_bytes)

fernet = Fernet(FERNET_KEY)
SIGNING_KEY = hashlib.sha256(FERNET_KEY).digest()


def create_csrf_state() -> str:
    """Generate a signed, timestamped CSRF state token for OAuth 2.0."""
    timestamp = str(int(time.time()))
    nonce = os.urandom(16).hex()
    payload = f"{nonce}:{timestamp}"
    signature = hmac.new(SIGNING_KEY, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}:{signature}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def verify_csrf_state(state: str, max_age_seconds: int = 600) -> bool:
    """Verify state token signature and expiration (default 10 minutes)."""
    try:
        raw = base64.urlsafe_b64decode(state.encode("utf-8")).decode("utf-8")
        parts = raw.split(":")
        if len(parts) != 3:
            return False
        nonce, timestamp_str, sig = parts
        timestamp = int(timestamp_str)
        if time.time() - timestamp > max_age_seconds or time.time() < timestamp - 60:
            return False
        payload = f"{nonce}:{timestamp_str}"
        expected_sig = hmac.new(SIGNING_KEY, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected_sig)
    except Exception:
        return False


def encrypt_session_data(data: Dict[str, Any]) -> str:
    """Encrypt session dictionary into a tamper-proof ciphertext string."""
    json_bytes = json.dumps(data).encode("utf-8")
    return fernet.encrypt(json_bytes).decode("utf-8")


def decrypt_session_data(cookie_val: str, max_age_seconds: int = 86400 * 7) -> Optional[Dict[str, Any]]:
    """Decrypt and validate session cookie value. Returns None if invalid or expired."""
    if not cookie_val:
        return None
    try:
        decrypted = fernet.decrypt(cookie_val.encode("utf-8"), ttl=max_age_seconds)
        return json.loads(decrypted.decode("utf-8"))
    except (InvalidToken, Exception):
        return None
