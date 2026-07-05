"""Auth 2 camadas:
1. service token (Django -> shinzou)
2. JWT do usuário (mesmo simplejwt do Django, mesma SECRET_KEY)."""

import hmac

import jwt
from fastapi import Header, HTTPException

from .config import settings


def verify_service_token(x_service_token: str = Header(...)) -> None:
    # comparação constant-time evita timing attack no token
    if not hmac.compare_digest(x_service_token, settings.SERVICE_TOKEN):
        raise HTTPException(status_code=401, detail="Service token inválido.")


def get_user_id(authorization: str = Header(...)) -> int:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token ausente.")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado.")
    # só access token autoriza — refresh token (mesma chave) NÃO pode passar
    if payload.get("token_type") != "access":
        raise HTTPException(status_code=401, detail="Tipo de token inválido.")
    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Token sem user_id.")
    return int(user_id)
