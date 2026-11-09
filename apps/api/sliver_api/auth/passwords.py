"""scrypt password hashes (standard library), stored as `scrypt$n$r$p$salt$hash`."""

import base64
import hashlib
import hmac
import secrets

N, R, P, DKLEN = 2**14, 8, 1, 32
MAX_PASSWORD_CHARS = 1024


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=DKLEN, maxmem=64 << 20)


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(16)
    digest = _derive(password, salt, N, R, P)
    encode = base64.urlsafe_b64encode
    return f"scrypt${N}${R}${P}${encode(salt).decode()}${encode(digest).decode()}"


# Verifying against this keeps unknown accounts as slow as wrong passwords.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded or not password or len(password) > MAX_PASSWORD_CHARS:
        _verify(password[:MAX_PASSWORD_CHARS] or "x", _DUMMY_HASH)
        return False
    return _verify(password, encoded)


def _verify(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = encoded.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.urlsafe_b64decode(digest)
        actual = _derive(password, base64.urlsafe_b64decode(salt), int(n), int(r), int(p))
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)
