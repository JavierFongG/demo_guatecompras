"""Autenticación con Supabase Auth.

El frontend inicia sesión con Supabase (enlace mágico por correo) y envía el token de acceso en
`Authorization: Bearer <token>`. Aquí se verifica la firma con las claves públicas del proyecto
(JWKS), sin llamar a Supabase en cada solicitud: las claves se guardan en caché.

  GC_SUPABASE_URL     https://<proyecto>.supabase.co
  GC_AUTH_REQUIRED    1 por defecto en modo api; 0 en modo local (desarrollo sin login)

Administradores: usuarios con app_metadata.role = "admin" (se asigna con SQL en Supabase).
Las tareas automáticas (pipeline) siguen usando X-Admin-Token = GC_ADMIN_TOKEN.
"""
from __future__ import annotations

import base64
import json

import jwt
from fastapi import Depends, Header, HTTPException

from . import config

ALGORITHMS = ["ES256", "RS256"]
AUDIENCE = "authenticated"
LOCAL_USER = {"sub": "local", "email": None, "app_metadata": {"role": "admin"}}

_jwks: jwt.PyJWKClient | None = None


def check_config() -> None:
    """Se llama al arrancar: sin GC_SUPABASE_URL no se puede exigir login."""
    if config.AUTH_REQUIRED and not config.SUPABASE_URL:
        raise RuntimeError("GC_AUTH_REQUIRED=1 pero falta GC_SUPABASE_URL (https://<proyecto>.supabase.co)")


def _client() -> jwt.PyJWKClient:
    global _jwks
    if _jwks is None:
        _jwks = jwt.PyJWKClient(f"{config.SUPABASE_URL}/auth/v1/.well-known/jwks.json",
                                cache_keys=True, lifespan=3600)
    return _jwks


def verify(token: str) -> dict:
    try:
        key = _client().get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=ALGORITHMS, audience=AUDIENCE,
                          issuer=f"{config.SUPABASE_URL}/auth/v1", options={"require": ["exp", "sub"]})
    except (jwt.PyJWTError, jwt.PyJWKClientError) as e:
        raise HTTPException(401, "Sesión inválida o vencida; vuelve a iniciar sesión") from e


def bearer(authorization: str) -> str | None:
    if authorization[:7].lower() == "bearer ":
        return authorization[7:].strip() or None
    return None


def current_user(authorization: str = Header(default="")) -> dict:
    """Dependencia de FastAPI: usuario autenticado (o usuario local si no se exige login)."""
    if not config.AUTH_REQUIRED:
        token = bearer(authorization)
        return verify(token) if token and config.SUPABASE_URL else LOCAL_USER
    token = bearer(authorization)
    if not token:
        raise HTTPException(401, "Inicia sesión para usar el buscador")
    return verify(token)


def is_admin(user: dict) -> bool:
    return (user.get("app_metadata") or {}).get("role") == "admin"


def admin_user(user: dict = Depends(current_user)) -> dict:
    if not is_admin(user):
        raise HTTPException(403, "Solo administradores")
    return user


def unverified_sub(authorization: str) -> str | None:
    """`sub` del token SIN verificar la firma. Solo sirve como clave del límite de solicitudes;
    la verificación real ocurre en current_user."""
    token = bearer(authorization)
    if not token or token.count(".") != 2:
        return None
    try:
        part = token.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        sub = data.get("sub")
        return str(sub)[:64] if sub else None
    except (ValueError, UnicodeDecodeError):
        return None
