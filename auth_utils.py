"""Password hashing helpers."""
import base64
import hashlib
import hmac
import os

PBKDF2_ITERATIONS = 310_000
PBKDF2_PREFIX = "pbkdf2_sha256"


def _b64encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64decode(raw: str) -> bytes:
    return base64.b64decode(raw.encode("ascii"))


def hash_password(password: str) -> str:
    """Create a salted PBKDF2 password hash."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return f"{PBKDF2_PREFIX}${PBKDF2_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against PBKDF2 or legacy unsalted SHA-256 hashes."""
    if not stored_hash:
        return False

    if stored_hash.startswith(f"{PBKDF2_PREFIX}$"):
        try:
            _, iterations_raw, salt_raw, digest_raw = stored_hash.split("$", 3)
            digest = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                _b64decode(salt_raw),
                int(iterations_raw),
            )
            return hmac.compare_digest(digest, _b64decode(digest_raw))
        except Exception:
            return False

    legacy_digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy_digest, stored_hash)


def password_needs_rehash(stored_hash: str) -> bool:
    """Return True for legacy hashes or hashes using older parameters."""
    if not stored_hash.startswith(f"{PBKDF2_PREFIX}$"):
        return True
    try:
        _, iterations_raw, _, _ = stored_hash.split("$", 3)
        return int(iterations_raw) < PBKDF2_ITERATIONS
    except Exception:
        return True
