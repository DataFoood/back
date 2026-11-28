"""IP real do cliente quando a requisição chega pelo proxy do front (Vercel).

O navegador fala só com o domínio do front (cookies first-party) e o Next
repassa `/api/*` para cá. Visto daqui, o "cliente" seria o IP da Vercel e o
throttle por IP (login 5/min, cadastro 10/h) seria dividido por todo mundo.

O proxy manda o IP do usuário em `X-DataFood-Client-IP` junto com um segredo
compartilhado (`FRONTEND_PROXY_SECRET`). Só com o segredo certo o IP é aceito;
sem ele os cabeçalhos são descartados e vale o caminho de sempre (NUM_PROXIES).
"""

import hmac
import ipaddress

from django.conf import settings

SECRET_META = "HTTP_X_DATAFOOD_PROXY_SECRET"
CLIENT_IP_META = "HTTP_X_DATAFOOD_CLIENT_IP"


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


class FrontendProxyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        meta = request.META
        secret = meta.pop(SECRET_META, "")
        client_ip = _valid_ip(meta.pop(CLIENT_IP_META, ""))
        expected = settings.FRONTEND_PROXY_SECRET
        if expected and client_ip and hmac.compare_digest(secret.encode(), expected.encode()):
            # o throttle do DRF lê o X-Forwarded-For (NUM_PROXIES > 0) ou o
            # REMOTE_ADDR (NUM_PROXIES = 0): os dois passam a ser o usuário
            meta["REMOTE_ADDR"] = client_ip
            meta["HTTP_X_FORWARDED_FOR"] = client_ip
        return self.get_response(request)
