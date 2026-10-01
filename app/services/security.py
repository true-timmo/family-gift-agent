"""Zufällige Tokens und Codes. Gespeichert werden nur Hashes – ein Datenbank-Leck verrät keine Logins."""
import hashlib
import hmac
import secrets


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def hash_code(name: str, code: str) -> str:
    return hashlib.sha256(f"{name.lower()}:{code}".encode()).hexdigest()


def same_secret(a: str, b: str) -> bool:
    """Vergleich in konstanter Zeit (verrät nicht, ab welcher Stelle es abweicht)."""
    return hmac.compare_digest(a.encode(), b.encode())
