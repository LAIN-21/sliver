"""Password and opaque session primitives. Never put identity claims in cookies."""

import hashlib
import hmac
import secrets


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16_384,
                            r=8, p=1, maxmem=64 * 1024 * 1024).hex()
    return f"scrypt${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16_384,
                                r=8, p=1, maxmem=64 * 1024 * 1024).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False
