"""Deployment-key encryption for provider credentials."""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


KEY_ENVIRONMENT_VARIABLE = "M3UGUIDE_CREDENTIAL_KEY"


def _cipher() -> Fernet:
    value = os.getenv(KEY_ENVIRONMENT_VARIABLE, "").strip()
    if not value:
        raise RuntimeError(f"{KEY_ENVIRONMENT_VARIABLE} is required to store or use provider credentials")
    try:
        return Fernet(value.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as error:
        raise RuntimeError(f"{KEY_ENVIRONMENT_VARIABLE} is not a valid Fernet key") from error


def encrypt_password(password: str) -> str:
    """Encrypt a provider password with integrity protection."""
    return _cipher().encrypt(password.encode("utf-8")).decode("ascii")


def decrypt_password(details: dict) -> str | None:
    """Decrypt a password from playlist details; support plaintext only for migration."""
    encrypted = details.get("password_encrypted")
    if encrypted:
        try:
            return _cipher().decrypt(str(encrypted).encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError) as error:
            raise RuntimeError("Stored provider credential cannot be decrypted with the configured key") from error
    return details.get("password")


def store_password(details: dict, password: str) -> None:
    """Replace any plaintext password with encrypted storage."""
    details["password_encrypted"] = encrypt_password(password)
    details.pop("password", None)


def rotate_password(details: dict, old_key: str, new_key: str) -> None:
    """Re-encrypt one playlist credential during controlled key rotation."""
    encrypted = details.get("password_encrypted")
    if not encrypted:
        return
    plaintext = Fernet(old_key.encode("ascii")).decrypt(str(encrypted).encode("ascii"))
    details["password_encrypted"] = Fernet(new_key.encode("ascii")).encrypt(plaintext).decode("ascii")
