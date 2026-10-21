"""Sessão do navegador em cookies HttpOnly.

O front nunca vê os tokens: o login grava `access` e `refresh` em cookies
HttpOnly e o front só chama o refresh. Clientes de API (Swagger, Postman,
testes) continuam com `Authorization: Bearer` e tokens no corpo.

CSRF: cookie vai sozinho em toda requisição, então escrita autenticada por
cookie exige o cabeçalho `X-Requested-With`. Um site de terceiro só manda
cabeçalho customizado com preflight de CORS — e o CORS só libera a origem do
front. SameSite=Lax completa a proteção.
"""

from django.conf import settings
from rest_framework import exceptions
from rest_framework.permissions import SAFE_METHODS
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

BROWSER_HEADER = "X-Requested-With"


def is_browser(request) -> bool:
    """Requisição do front (cookie mode): manda o cabeçalho anti-CSRF."""
    return bool(request.headers.get(BROWSER_HEADER))


class CookieJWTAuthentication(JWTAuthentication):
    """Bearer quando houver; senão o access do cookie HttpOnly."""

    def authenticate(self, request):
        if self.get_header(request) is not None:
            return super().authenticate(request)
        raw = request.COOKIES.get(settings.AUTH_COOKIE_ACCESS)
        if not raw:
            return None
        try:
            token = self.get_validated_token(raw.encode())
        except (InvalidToken, TokenError):
            # access vencido/forjado = visitante: rota pública segue, rota
            # protegida responde 401 e o front roda o refresh
            return None
        if request.method not in SAFE_METHODS and not is_browser(request):
            raise exceptions.PermissionDenied(f"Cabeçalho {BROWSER_HEADER} obrigatório com sessão por cookie.")
        return self.get_user(token), token


def _cookie_kwargs():
    return {
        "httponly": True,
        "secure": settings.AUTH_COOKIE_SECURE,
        "samesite": settings.AUTH_COOKIE_SAMESITE,
        "domain": settings.AUTH_COOKIE_DOMAIN,
    }


def access_seconds() -> int:
    return int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds())


def set_auth_cookies(response, access: str, refresh: str | None = None):
    response.set_cookie(
        settings.AUTH_COOKIE_ACCESS, access, max_age=access_seconds(), path="/", **_cookie_kwargs()
    )
    if refresh:
        response.set_cookie(
            settings.AUTH_COOKIE_REFRESH, refresh,
            max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
            # só as rotas de sessão recebem o refresh
            path=settings.AUTH_COOKIE_REFRESH_PATH, **_cookie_kwargs(),
        )
    return response


def clear_auth_cookies(response):
    domain = settings.AUTH_COOKIE_DOMAIN
    response.delete_cookie(settings.AUTH_COOKIE_ACCESS, path="/", domain=domain, samesite=settings.AUTH_COOKIE_SAMESITE)
    response.delete_cookie(
        settings.AUTH_COOKIE_REFRESH, path=settings.AUTH_COOKIE_REFRESH_PATH, domain=domain,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )
    return response


def to_cookie_session(response):
    """Corpo com tokens -> cookies. Os tokens saem do corpo (o JS não os lê)."""
    data = response.data
    set_auth_cookies(response, data.pop("access"), data.pop("refresh", None))
    data["access_expires_in"] = access_seconds()
    return response
