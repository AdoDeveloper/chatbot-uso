"""Tests for app.core.security — password hashing, JWT, Fernet encryption."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("settings_env")


class TestPasswordHashing:
    def test_hash_and_verify(self):
        from app.core.security import hash_password, verify_password

        hashed = hash_password("MyP@ssw0rd!")
        assert hashed != "MyP@ssw0rd!"
        assert verify_password("MyP@ssw0rd!", hashed) is True

    def test_wrong_password(self):
        from app.core.security import hash_password, verify_password

        hashed = hash_password("correct-pw")
        assert verify_password("wrong-pw!!", hashed) is False

    def test_different_hashes(self):
        from app.core.security import hash_password

        h1 = hash_password("same-value")
        h2 = hash_password("same-value")
        assert h1 != h2  # bcrypt uses random salt


class TestJWT:
    def test_access_token_roundtrip(self):
        from app.core.security import create_access_token, decode_token

        token = create_access_token("user-123")
        payload = decode_token(token)
        assert payload["sub"] == "user-123"
        assert payload["type"] == "access"

    def test_refresh_token_roundtrip(self):
        from app.core.security import create_refresh_token, decode_token

        token = create_refresh_token("user-456")
        payload = decode_token(token)
        assert payload["sub"] == "user-456"
        assert payload["type"] == "refresh"

    def test_invalid_token(self):
        import jwt as pyjwt

        from app.core.security import decode_token

        with pytest.raises(pyjwt.PyJWTError):
            decode_token("invalid.token.here")

    def test_tampered_token(self):
        import jwt as pyjwt

        from app.core.security import create_access_token, decode_token

        token = create_access_token("user-789")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(pyjwt.PyJWTError):
            decode_token(tampered)


class TestFernetEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        from app.core.security import encrypt_secret, decrypt_secret

        secret = "sk-my-api-key-12345"
        encrypted = encrypt_secret(secret)
        assert encrypted != secret
        assert decrypt_secret(encrypted) == secret

    def test_different_encryptions(self):
        from app.core.security import encrypt_secret

        e1 = encrypt_secret("same-value")
        e2 = encrypt_secret("same-value")
        assert e1 != e2  # Fernet uses timestamp + random IV

    def test_legacy_fallback(self):
        """Data encrypted with old SHA256 derivation should still decrypt."""
        import base64
        import hashlib
        from cryptography.fernet import Fernet
        from app.core.config import get_settings
        from app.core.security import decrypt_secret

        settings = get_settings()
        source = settings.ENCRYPTION_KEY or settings.SECRET_KEY
        raw = hashlib.sha256(source.encode()).digest()
        legacy_fernet = Fernet(base64.urlsafe_b64encode(raw))
        legacy_encrypted = legacy_fernet.encrypt(b"old-api-key").decode()

        assert decrypt_secret(legacy_encrypted) == "old-api-key"
