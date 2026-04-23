"""Authentication helpers for Smart Notepad Pro."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Any

import db


PBKDF2_ITERATIONS = 390_000


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt_bytes = salt or os.urandom(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        PBKDF2_ITERATIONS,
    )
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.b64encode(salt_bytes).decode("ascii"),
        base64.b64encode(derived).decode("ascii"),
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, hash_b64 = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
        return hmac.compare_digest(candidate, expected)
    except Exception:
        return False


def create_user(username: str, email: str, password: str) -> tuple[bool, str, dict[str, Any] | None]:
    identifier = username.strip().lower()
    mail = email.strip().lower() if email else ""
    if not identifier:
        return False, "Username is required.", None
    if len(password) < 8:
        return False, "Password must be at least 8 characters long.", None
    existing = db.get_user_by_identifier(identifier) or (db.get_user_by_identifier(mail) if mail else None)
    if existing:
        return False, "That username or email already exists.", None
    password_hash = hash_password(password)
    user_id = db.create_user_record(identifier, mail, password_hash)
    db.ensure_default_settings(user_id)
    user = db.get_user_by_id(user_id)
    return True, "Account created successfully.", user


def authenticate(identifier: str, password: str) -> tuple[bool, str, dict[str, Any] | None]:
    user = db.get_user_by_identifier(identifier.strip().lower())
    if not user:
        return False, "Invalid username, email, or password.", None
    if not verify_password(password, user["password_hash"]):
        return False, "Invalid username, email, or password.", None
    db.update_last_login(user["id"])
    db.ensure_default_settings(user["id"])
    return True, "Login successful.", db.get_user_by_id(user["id"])

