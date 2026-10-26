import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

SUPABASE = "https://demo.supabase.co"


def test_local_mode_is_open(make_client):
    c, _ = make_client(GC_MODE="local")
    with c:
        h = c.get("/api/health").json()
        assert h["ready"] is False and h["auth"]["required"] is False
        assert c.get("/api/facets").status_code == 503     # sin índice, pero sin pedir login
        assert c.get("/docs").status_code == 200


def test_api_mode_requires_supabase_url(make_client):
    c, _ = make_client(GC_MODE="api", GC_SUPABASE_URL="")
    with pytest.raises(RuntimeError):
        with c:
            pass


@pytest.fixture
def api_client(make_client, monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    c, auth = make_client(GC_MODE="api", GC_SUPABASE_URL=SUPABASE, GC_ADMIN_TOKEN="secreto")

    class FakeJWKS:
        def get_signing_key_from_jwt(self, token):
            return type("K", (), {"key": key.public_key()})()

    monkeypatch.setattr(auth, "_jwks", FakeJWKS())

    def token(role=None, exp=3600, aud="authenticated"):
        claims = {"sub": "u-1", "email": "a@b.gt", "aud": aud, "iss": f"{SUPABASE}/auth/v1",
                  "exp": int(time.time()) + exp, "app_metadata": {"role": role} if role else {}}
        return jwt.encode(claims, key, algorithm="ES256")
    return c, token


def test_api_mode_blocks_without_token(api_client):
    c, _ = api_client
    with c:
        assert c.get("/api/health").status_code == 200          # pública para el monitoreo
        assert c.get("/api/facets").status_code == 401
        assert c.post("/api/search", json={"q": "x"}).status_code == 401
        assert c.get("/api/me").status_code == 401
        assert c.get("/docs").status_code == 404
        assert c.post("/api/update").status_code in (401, 404)


def test_api_mode_accepts_valid_token(api_client):
    c, token = api_client
    hdr = {"Authorization": f"Bearer {token()}"}
    with c:
        assert c.get("/api/me", headers=hdr).json() == {"id": "u-1", "email": "a@b.gt", "admin": False}
        assert c.get("/api/facets", headers=hdr).status_code == 503   # autenticado; sin índice


def test_api_mode_rejects_bad_tokens(api_client):
    c, token = api_client
    with c:
        for t in (token(exp=-10), token(aud="anon"), "no-es-un-jwt"):
            assert c.get("/api/me", headers={"Authorization": f"Bearer {t}"}).status_code == 401


def test_admin_routes(api_client):
    c, token = api_client
    with c:
        assert c.post("/api/reload").status_code == 401
        assert c.post("/api/reload", headers={"X-Admin-Token": "mal"}).status_code == 401
        assert c.post("/api/reload", headers={"X-Admin-Token": "secreto"}).status_code == 200
        assert c.post("/api/reload", headers={"Authorization": f"Bearer {token()}"}).status_code == 403
        assert c.post("/api/reload", headers={"Authorization": f"Bearer {token('admin')}"}).status_code == 200


def test_index_age_hours(make_client):
    _, _ = make_client(GC_MODE="local")
    from app import main
    assert main._age_hours(None) is None
    assert main._age_hours("2000-01-01T00:00:00Z") > 200000
    # Fechas sin zona = índices antiguos construidos en hora de Guatemala (UTC-6)
    assert abs(main._age_hours("2000-01-01T00:00:00") - main._age_hours("2000-01-01T06:00:00Z")) < 0.1
