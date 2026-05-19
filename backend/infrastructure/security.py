from __future__ import annotations

import hashlib
import hmac
import os
import secrets


def hash_password(password: str, *, salt: str | None = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    )
    return f"{salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        salt, stored = encoded.split("$", 1)
    except ValueError:
        return False
    candidate = hash_password(password, salt=salt)
    return hmac.compare_digest(candidate, f"{salt}${stored}")


def new_session_token() -> str:
    return secrets.token_urlsafe(48)


def safe_filename(name: str) -> str:
    text = (name or "").strip()
    if not text:
        return "upload.bin"
    text = text.replace("\\", "_").replace("/", "_")
    text = "".join(ch if ch.isalnum() or ch in {"-", "_", ".", " "} else "_" for ch in text)
    text = text.strip(" .")
    return text or "upload.bin"


def make_job_id() -> str:
    return os.urandom(16).hex()

