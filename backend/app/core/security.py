from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt as pyjwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.core.exceptions import ValidationError

# Patterns for common weak passwords (CVE-2019-1000007 list)
_COMMON_WEAK_PASSWORDS = {
    "password", "123456", "12345678", "qwerty", "abc123", "monkey", "master",
    "admin", "letmein", "welcome", "login", "password1", "password123",
    "admin123", "root", "toor", "pass", "test", "guest", "user", "qwerty123"
}

# Pattern for common weak patterns
_WEAK_PASSWORD_PATTERN = re.compile(
    r"^(?!.*[a-z])(?!.*[A-Z])(?!.*\d)(?!.*[^a-zA-Z0-9]).{1,12}$|^(\w)\1{2,}$|"
    r"^(\w)\2(\w)\3(\w)\4$|^1234567890$|^qwertyuiop$|^asdfghjkl$"
)


def _is_common_password(password: str) -> bool:
    """Check if password is in common weak passwords list."""
    return password.lower() in _COMMON_WEAK_PASSWORDS


def _has_weak_pattern(password: str) -> bool:
    """Check if password has weak pattern."""
    return bool(_WEAK_PASSWORD_PATTERN.match(password))


def hash_password(password: str) -> str:
    """Hash password with bcrypt, enforcing minimum security requirements."""
    if len(password) < 8:
        raise ValidationError("La contraseña debe tener al menos 8 caracteres.")
    if len(password) > 512:
        raise ValidationError("La contraseña es demasiado larga.")
    if _is_common_password(password):
        raise ValidationError("La contraseña es demasiado común. Elija una más segura.")
    if _has_weak_pattern(password):
        raise ValidationError("La contraseña tiene un patrón débil. Evite caracteres repetidos o secuencias.")
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str | None) -> bool:
    """Verify password against hash."""
    if not hashed:
        return False
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(subject: str, permissions: list[str] | None = None) -> str:
    """Emite un access JWT.

    `permissions` (opcional) incrusta la lista de permisos 'modulo.accion' del
    usuario en el payload. El frontend los decodifica para resolver la
    visibilidad de la navegación sin depender de una llamada extra a la API;
    el backend sigue autorizando por BD (require_perm), así que el claim del
    JWT es solo una caché de lectura para la UI, no fuente de autoridad.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict = {
        "sub": subject,
        "exp": expire,
        "iat": now,
        "jti": uuid.uuid4().hex,
        "type": "access",
    }
    if permissions is not None:
        payload["permissions"] = permissions
    return pyjwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return pyjwt.encode(
        {
            "sub": subject,
            "exp": expire,
            "iat": now,
            "jti": uuid.uuid4().hex,
            "type": "refresh",
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def decode_token(token: str) -> dict:
    """Decodifica y verifica un JWT.

    Lanza pyjwt.PyJWTError si el token es inválido/expirado/falsificado.
    Antes devolvía {} en error, lo que impedía a get_current_user distinguir
    "token inválido" de "sin sujeto". Ahora propaga la excepción para que el
    caller diferencie claramente ambos casos y responda 401.
    """
    settings = get_settings()
    return pyjwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


_FERNET_CACHE: dict[str, Fernet] = {}
_FERNET_LEGACY_CACHE: dict[str, Fernet] = {}


def _derive_fernet_key(source: str) -> bytes:
    """Derive a 32-byte Fernet key using PBKDF2-HMAC-SHA256 (480k iterations)."""
    salt = hashlib.sha256(b"chatbot-uso-fernet-salt:" + source.encode()).digest()
    raw = hashlib.pbkdf2_hmac("sha256", source.encode(), salt, iterations=480_000)
    return base64.urlsafe_b64encode(raw)


def _legacy_fernet_key(source: str) -> bytes:
    """Legacy key derivation (SHA256 only) for migrating existing data."""
    raw = hashlib.sha256(source.encode()).digest()
    return base64.urlsafe_b64encode(raw)


def _fernet() -> Fernet:
    """Derive a Fernet instance from ENCRYPTION_KEY (preferred) or SECRET_KEY.
    Cached so PBKDF2 (480k iterations) runs once per process lifetime.
    """
    settings = get_settings()
    source = settings.ENCRYPTION_KEY or settings.SECRET_KEY
    cached = _FERNET_CACHE.get(source)
    if cached is None:
        cached = Fernet(_derive_fernet_key(source))
        _FERNET_CACHE[source] = cached
    return cached


def _fernet_legacy() -> Fernet:
    """Legacy Fernet instance (SHA256 only, no PBKDF2) for migrating data.
    Cached per source to avoid recomputation.
    """
    settings = get_settings()
    source = settings.ENCRYPTION_KEY or settings.SECRET_KEY
    cached = _FERNET_LEGACY_CACHE.get(source)
    if cached is None:
        cached = Fernet(_legacy_fernet_key(source))
        _FERNET_LEGACY_CACHE[source] = cached
    return cached


def encrypt_secret(value: str) -> str:
    """Encrypt a plaintext string (e.g. API key) for storage in the DB.

    Síncrono — útil para seeds / scripts. En endpoints async, prefiere
    `await encrypt_secret_async(value)` para no bloquear el event loop.
    """
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(token: str) -> str:
    """Decrypt a Fernet-encrypted string. Falls back to legacy key for pre-PBKDF2 data.

    Síncrono — útil para seeds / scripts. En endpoints async, prefiere
    `await decrypt_secret_async(token)` para no bloquear el event loop.
    """
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return _fernet_legacy().decrypt(token.encode()).decode()


async def encrypt_secret_async(value: str) -> str:
    """Async version — ejecuta PBKDF2 en thread pool para no bloquear el event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, encrypt_secret, value)


async def decrypt_secret_async(token: str) -> str:
    """Async version — ejecuta PBKDF2 en thread pool para no bloquear el event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, decrypt_secret, token)
