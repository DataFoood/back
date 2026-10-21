"""Swagger: CookieJWTAuthentication aparece como o mesmo Bearer JWT de sempre
(o cookie é detalhe do navegador; quem testa pelo Swagger usa o Bearer)."""

from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme


class CookieJWTScheme(SimpleJWTScheme):
    target_class = "users.authentication.CookieJWTAuthentication"
    name = "jwtAuth"
