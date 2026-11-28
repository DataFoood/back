"""Metadados públicos de sites explicitamente autorizados na linha de comando.

Não segue catálogos, redes sociais, páginas de avaliações ou links recursivos.
Fotos continuam ligadas à fonte original; a licença nunca é presumida ODbL.
"""
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        if tag != 'meta':
            return
        attrs = dict(attrs)
        key = attrs.get('property', attrs.get('name', '')).lower()
        if key in ('og:image', 'og:description', 'description') and attrs.get('content'):
            self.values.setdefault(key, attrs['content'])


def public_url(url, allowed_hosts):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in allowed_hosts or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('Host HTTPS não autorizado.')
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('Endereço não público.')
    return url


def fetch_metadata(url, allowed_hosts):
    # Sem redirects automáticos: cada novo destino passa pela autorização.
    with httpx.Client(timeout=8, follow_redirects=False, headers={'User-Agent': 'DataFoodCatalog/1.0 (public website metadata)'}) as client:
        for _ in range(4):
            public_url(url, allowed_hosts)
            with client.stream('GET', url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get('location', ''))
                    continue
                response.raise_for_status()
                if 'text/html' not in response.headers.get('content-type', ''):
                    raise ValueError('A fonte não retornou HTML.')
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 512 * 1024:
                        break
                parser = Metadata()
                parser.feed(body[:512 * 1024].decode(response.encoding or 'utf-8', errors='replace'))
                return url, parser.values
    raise ValueError('Redirecionamentos demais.')


def image_url(value, page):
    url = urljoin(page, value)
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or len(url) > 200:
        return ''
    # Metadado de imagem é exibido no navegador; nunca solicitado pelo servidor.
    try:
        if not ipaddress.ip_address(parsed.hostname).is_global:
            return ''
    except ValueError:
        if parsed.hostname == 'localhost' or '.' not in parsed.hostname:
            return ''
    return url
