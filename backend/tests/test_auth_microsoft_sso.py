"""Tests de caracterización para microsoft_callback en app/api/v1/auth/router.py.

Este endpoint no tenía NINGÚN test antes de esto (verificado por grep en
todo tests/) a pesar de ser el flujo con mayor blast radius del sistema
(login SSO: intercambio de código, verificación JWKS, provisión de
usuario). Se fija exhaustivamente aquí antes de considerar cualquier
extracción a servicio.

El intercambio de código por tokens con Microsoft (httpx) se sustituye
por un stub. La verificación del id_token NO mockea jwt.decode: firma un
id_token real con una clave RSA de test y solo reemplaza PyJWKClient
para que devuelva la clave pública correspondiente — así jwt.decode()
real (el mismo módulo que usa core/security.py para los JWT propios del
sistema) sigue haciendo la verificación de firma de verdad, sin arriesgar
que un mock global rompa la emisión de tokens tras un login exitoso.

Todas las ramas de error devuelven el mismo 401 genérico ("Credenciales
incorrectas") por diseño anti-enumeración; se distinguen por el `reason`
que queda en el audit log (no verificado aquí, solo el status code).
"""
from __future__ import annotations

import pytest

from app.models.enums import UserRole
from app.models.global_setting import GlobalSetting


SSO_SETTINGS = {
    "MICROSOFT_CLIENT_ID": "test-client-id",
    "MICROSOFT_CLIENT_SECRET": "test-client-secret",
    "MICROSOFT_TENANT_ID": "test-tenant-id",
    "MICROSOFT_REDIRECT_URI": "http://testserver/auth/callback",
}


@pytest.fixture(autouse=True)
def sso_env(monkeypatch):
    from app.core.config import get_settings
    for k, v in SSO_SETTINGS.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def reset_local_rate_limit_fallback():
    """Red de seguridad para el fallback en memoria de app.core.rate_limit
    (_LOCAL_LIMITS, dict a nivel de módulo que persistiría entre tests si
    Redis no estuviera disponible). El camino normal ya no depende de esto:
    rate_limit.py usa `redis_mod.get_redis()` (import del módulo, no del
    símbolo), por lo que el `monkeypatch.setattr(redis_mod, "get_redis", ...)`
    de conftest.py sí lo intercepta, y cada test recibe un FakeRedis nuevo
    vía el fixture `client` — el rate limit se resetea solo entre tests."""
    from app.core.rate_limit import _LOCAL_LIMITS
    _LOCAL_LIMITS.clear()
    yield
    _LOCAL_LIMITS.clear()


@pytest.fixture
async def sso_active(db_session):
    """Activa oauth_active=True en GlobalSetting (leído por el endpoint)."""
    db_session.add(GlobalSetting(key="oauth_active", value=True))
    await db_session.commit()


def _new_rsa_key():
    from cryptography.hazmat.primitives.asymmetric import rsa
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def rsa_keypair():
    """Clave RSA de test usada para firmar id_tokens "legítimos" en los
    tests. Ver docstring del módulo: no se mockea jwt.decode global."""
    return _new_rsa_key()


@pytest.fixture(scope="module")
def other_rsa_keypair():
    """Segunda clave, distinta de rsa_keypair — usada para simular un
    id_token con firma inválida (PyJWKClient devuelve la pública de
    rsa_keypair, pero el token viene firmado con esta otra)."""
    return _new_rsa_key()


def _sign_id_token(claims: dict, private_key, audience="test-client-id") -> str:
    import jwt as jwt_module
    from cryptography.hazmat.primitives import serialization
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    payload = {**claims, "aud": audience}
    return jwt_module.encode(payload, private_pem, algorithm="RS256")


@pytest.fixture
def patch_jwks_verify(monkeypatch, rsa_keypair):
    """PyJWKClient.get_signing_key_from_jwt siempre devuelve la clave
    pública de rsa_keypair — jwt.decode() real verifica la firma de verdad
    contra esa clave. Ningún golpe de red al JWKS real de Microsoft."""
    import jwt as jwt_module

    class _FakeSigningKey:
        def __init__(self, public_key):
            self.key = public_key

    class _FakeJWKClient:
        def __init__(self, url, cache_keys=True):
            pass
        def get_signing_key_from_jwt(self, token):
            return _FakeSigningKey(rsa_keypair.public_key())

    # El código hace `from jwt import PyJWKClient` dentro de la función —
    # el nombre se resuelve en el módulo jwt en el momento de la llamada.
    monkeypatch.setattr(jwt_module, "PyJWKClient", _FakeJWKClient)


@pytest.fixture
def patch_ms_token_exchange(monkeypatch, rsa_keypair):
    """Mockea el httpx.AsyncClient usado DENTRO de microsoft_callback para
    simular el intercambio de código por tokens con Microsoft, devolviendo
    un id_token real firmado con rsa_keypair.

    Importante: NO se puede monkeypatchear httpx.AsyncClient.post a nivel
    de clase — el propio test client (fixture `client` en conftest.py)
    también es un httpx.AsyncClient (con ASGITransport), así que un patch
    de clase intercepta la petición del test contra el servidor de
    pruebas, no solo la llamada real a Microsoft. En su lugar se reemplaza
    el atributo `AsyncClient` visto desde `app.services.auth.sso.httpx`
    (el módulo httpx importado ahí), dejando intacto el httpx usado por
    conftest.py para construir el test client.
    """
    import app.services.auth.sso as sso_service

    default_claims = {"email": "usuario@empresa.com", "preferred_username": "usuario@empresa.com"}
    state = {
        "status_code": 200,
        "claims": dict(default_claims),
        "id_token_override": None,  # si se setea, se usa tal cual (p.ej. para simular firma inválida)
        "json_override": None,      # si se setea, reemplaza el body completo del intercambio
    }

    class _FakeResponse:
        def __init__(self, status_code, json_body):
            self.status_code = status_code
            self._json = json_body
        def json(self):
            return self._json

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return False
        async def post(self, url, data=None, **kwargs):
            if state["json_override"] is not None:
                return _FakeResponse(state["status_code"], state["json_override"])
            id_token = state["id_token_override"] or _sign_id_token(state["claims"], rsa_keypair)
            return _FakeResponse(state["status_code"], {"id_token": id_token})

    monkeypatch.setattr(sso_service.httpx, "AsyncClient", _FakeAsyncClient)
    return state


async def _post_callback(client, code="valid-code", redirect_uri="http://testserver/auth/callback"):
    return await client.post(
        "/api/v1/auth/microsoft/callback",
        json={"code": code, "redirect_uri": redirect_uri},
    )


class TestSsoNotConfigured:
    async def test_sso_inactive_returns_401(self, client, patch_ms_token_exchange, patch_jwks_verify):
        # sso_active fixture NOT used -> oauth_active defaults to False/missing
        r = await _post_callback(client)
        assert r.status_code == 401

    async def test_sso_active_but_missing_client_secret_returns_401(
        self, client, sso_active, monkeypatch, patch_ms_token_exchange, patch_jwks_verify
    ):
        from app.core.config import get_settings
        monkeypatch.delenv("MICROSOFT_CLIENT_SECRET", raising=False)
        get_settings.cache_clear()
        r = await _post_callback(client)
        assert r.status_code == 401


class TestRedirectUriValidation:
    async def test_mismatched_redirect_uri_returns_401(
        self, client, sso_active, patch_ms_token_exchange, patch_jwks_verify
    ):
        r = await _post_callback(client, redirect_uri="http://evil.example.com/callback")
        assert r.status_code == 401


class TestTokenExchangeFailures:
    async def test_ms_token_endpoint_error_returns_401(
        self, client, sso_active, patch_ms_token_exchange, patch_jwks_verify
    ):
        patch_ms_token_exchange["status_code"] = 400
        r = await _post_callback(client)
        assert r.status_code == 401

    async def test_missing_id_token_returns_401(
        self, client, sso_active, patch_ms_token_exchange, patch_jwks_verify
    ):
        patch_ms_token_exchange["json_override"] = {"access_token": "no-id-token-here"}
        r = await _post_callback(client)
        assert r.status_code == 401

    async def test_token_exchange_network_error_returns_401(
        self, client, sso_active, patch_jwks_verify, monkeypatch
    ):
        import httpx
        import app.services.auth.sso as sso_service

        class _FailingAsyncClient:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *exc):
                return False
            async def post(self, url, data=None, **kwargs):
                raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(sso_service.httpx, "AsyncClient", _FailingAsyncClient)

        r = await _post_callback(client)
        assert r.status_code == 401


class TestIdTokenVerification:
    async def test_invalid_signature_returns_401(
        self, client, sso_active, patch_ms_token_exchange, patch_jwks_verify, other_rsa_keypair
    ):
        # Firma el id_token con una clave DISTINTA a la que PyJWKClient
        # (mockeado) le va a "prestar" al verificador -> firma inválida real.
        claims = {"email": "usuario@empresa.com", "preferred_username": "usuario@empresa.com"}
        patch_ms_token_exchange["id_token_override"] = _sign_id_token(claims, other_rsa_keypair)
        r = await _post_callback(client)
        assert r.status_code == 401

    async def test_no_email_in_claims_returns_401(
        self, client, sso_active, patch_ms_token_exchange, patch_jwks_verify
    ):
        patch_ms_token_exchange["claims"] = {"name": "Sin correo"}
        r = await _post_callback(client)
        assert r.status_code == 401


class TestDomainAllowlist:
    async def test_domain_not_in_allowlist_returns_401(
        self, client, sso_active, db_session, patch_ms_token_exchange, patch_jwks_verify
    ):
        db_session.add(GlobalSetting(key="oauth_allowed_domains", value=["@otraempresa.com"]))
        await db_session.commit()
        r = await _post_callback(client)
        assert r.status_code == 401


class TestUserProvisioning:
    async def test_user_not_found_returns_401(
        self, client, sso_active, patch_ms_token_exchange, patch_jwks_verify
    ):
        r = await _post_callback(client)
        assert r.status_code == 401

    async def test_disabled_account_returns_401(
        self, client, sso_active, make_user, db_session, patch_ms_token_exchange, patch_jwks_verify
    ):
        user = await make_user(email="usuario@empresa.com", role=UserRole.viewer)
        user.is_active = False
        await db_session.commit()

        r = await _post_callback(client)
        assert r.status_code == 401

    async def test_successful_login_issues_tokens(
        self, client, sso_active, make_user, db_session, patch_ms_token_exchange, patch_jwks_verify
    ):
        user = await make_user(email="usuario@empresa.com", role=UserRole.editor)
        r = await _post_callback(client)
        assert r.status_code == 200
        body = r.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["user"]["email"] == "usuario@empresa.com"

        await db_session.refresh(user)
        assert user.last_login_at is not None

    async def test_email_matching_is_case_insensitive(
        self, client, sso_active, make_user, patch_ms_token_exchange, patch_jwks_verify
    ):
        await make_user(email="usuario@empresa.com", role=UserRole.viewer)
        patch_ms_token_exchange["claims"] = {
            "email": "USUARIO@EMPRESA.COM", "preferred_username": "USUARIO@EMPRESA.COM",
        }
        r = await _post_callback(client)
        assert r.status_code == 200
