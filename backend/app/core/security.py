from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt as pyjwt
from cryptography.fernet import Fernet

from app.core.config import get_settings
from app.core.exceptions import ValidationError

# Contraseñas débiles comunes (lista CVE-2019-1000007)
_COMMON_WEAK_PASSWORDS = {
    "password", "123456", "12345678", "qwerty", "abc123", "monkey", "master",
    "admin", "letmein", "welcome", "login", "password1", "password123",
    "admin123", "root", "toor", "pass", "test", "guest", "user", "qwerty123"
}

# Patrones débiles comunes (sin variedad de caracteres, repeticiones, secuencias)
_WEAK_PASSWORD_PATTERN = re.compile(
    r"^(?!.*[a-z])(?!.*[A-Z])(?!.*\d)(?!.*[^a-zA-Z0-9]).{1,12}$|^(\w)\1{2,}$|"
    r"^(\w)\2(\w)\3(\w)\4$|^1234567890$|^qwertyuiop$|^asdfghjkl$"
)


def _is_common_password(password: str) -> bool:
    """Verifica si la contraseña está en la lista de contraseñas débiles comunes."""
    return password.lower() in _COMMON_WEAK_PASSWORDS


def _has_weak_pattern(password: str) -> bool:
    """Verifica si la contraseña tiene un patrón débil."""
    return bool(_WEAK_PASSWORD_PATTERN.match(password))


def hash_password(password: str) -> str:
    """Genera el hash de la contraseña con bcrypt, validando requisitos mínimos de seguridad."""
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

    Lanza pyjwt.PyJWTError si el token es inválido/expirado/falsificado, para que el caller distinga ese caso de "sin sujeto" y responda 401.
    """
    settings = get_settings()
    return pyjwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


_FERNET_CACHE: dict[str, Fernet] = {}


def _derive_fernet_key(source: str) -> bytes:
    """Deriva una clave Fernet de 32 bytes usando PBKDF2-HMAC-SHA256 (480k iteraciones)."""
    salt = hashlib.sha256(b"chatbot-uso-fernet-salt:" + source.encode()).digest()
    raw = hashlib.pbkdf2_hmac("sha256", source.encode(), salt, iterations=480_000)
    return base64.urlsafe_b64encode(raw)


def _fernet() -> Fernet:
    """Deriva una instancia de Fernet a partir de ENCRYPTION_KEY (preferida) o SECRET_KEY.
    Se cachea para que PBKDF2 (480k iteraciones) corra una sola vez por proceso.
    """
    settings = get_settings()
    source = settings.ENCRYPTION_KEY or settings.SECRET_KEY
    cached = _FERNET_CACHE.get(source)
    if cached is None:
        cached = Fernet(_derive_fernet_key(source))
        _FERNET_CACHE[source] = cached
    return cached


def encrypt_secret(value: str) -> str:
    """Cifra una cadena en texto plano (p. ej. una API key) para guardarla en BD.

    Síncrono - útil para seeds / scripts. En endpoints async, prefiere
    `await encrypt_secret_async(value)` para no bloquear el event loop.
    """
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(token: str) -> str:
    """Descifra una cadena cifrada con Fernet.

    Síncrono - útil para seeds / scripts. En endpoints async, prefiere
    `await decrypt_secret_async(token)` para no bloquear el event loop.
    """
    return _fernet().decrypt(token.encode()).decode()


async def encrypt_secret_async(value: str) -> str:
    """Versión async - ejecuta PBKDF2 en thread pool para no bloquear el event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, encrypt_secret, value)


async def decrypt_secret_async(token: str) -> str:
    """Versión async - ejecuta PBKDF2 en thread pool para no bloquear el event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, decrypt_secret, token)
