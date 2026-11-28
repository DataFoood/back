"""Captura manual e limitada do diretório oficial de turismo de Marília.

Uma requisição por segundo, páginas públicas, sem avaliações ou preços inferidos.
Uso: python scripts/fetch_tourism_catalog.py --output catalog/marilia-tourism.json
"""
import argparse
import datetime
import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

ORIGIN = 'https://turismo.marilia.sp.gov.br'
CATEGORIES = {16: 'Churrascaria', 17: 'Restaurantes gourmet', 18: 'Hamburgueria', 19: 'Cafeterias',
              20: 'Restaurantes mexicanos', 21: 'Restaurantes orientais', 22: 'Gastronomia e entretenimento',
              23: 'Restaurantes rurais', 24: 'Pizzarias', 25: 'Pastelarias', 27: 'Gelateria e açaí'}


def address_line(lines):
    for i, line in enumerate(lines):
        if re.match(r'^(?:R(?:ua)?[.: ]|Av(?:enida)?[.: ]|Rodovia[.: ]|Estrada[.: ]|Alameda[.: ]|Endere[çc]o)', line, re.I):
            if re.fullmatch(r'Endere[çc]o\s*:?\s*', line, re.I) and i + 1 < len(lines):
                return lines[i + 1][:400]
            return line[:400]
    return ''


def fetch(path, data=None):
    time.sleep(1)
    request = Request(urljoin(ORIGIN, path), data=urlencode(data).encode() if data else None,
                      headers={'User-Agent': 'DataFoodCatalog/1.0 (Marilia local pilot; public tourism directory)'})
    with urlopen(request, timeout=20) as response:
        return response.read(2 * 1024 * 1024).decode('utf-8', errors='replace')


class Listing(HTMLParser):
    def __init__(self):
        super().__init__()
        self.records, self.current = [], None
        self.title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and re.fullmatch(r'/turismo/[^/]+/\d+', attrs.get('href', '')):
            self.current = {'source_url': urljoin(ORIGIN, attrs['href']), 'source_id': attrs['href'].rsplit('/', 1)[-1], 'name': '', 'image_url': ''}
        if self.current and tag == 'img':
            self.current['image_url'] = urljoin(ORIGIN, attrs.get('src', ''))
        if self.current and 'titulo_turismo' in attrs.get('class', ''):
            self.title = True

    def handle_data(self, data):
        if self.current and self.title:
            self.current['name'] += data.strip()

    def handle_endtag(self, tag):
        if tag == 'div':
            self.title = False
        if tag == 'a' and self.current:
            if self.current['name']:
                self.records.append(self.current)
            self.current = None


class Detail(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth, self.lines, self.links = 0, [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'div' and 'area_descricao_turismo' in attrs.get('class', ''):
            self.depth = 1
        elif self.depth and tag == 'div':
            self.depth += 1
        if self.depth and tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])

    def handle_endtag(self, tag):
        if tag == 'div' and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth and data.strip():
            self.lines.append(' '.join(data.split()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    records = {}
    for category, label in CATEGORIES.items():
        listing = Listing()
        listing.feed(fetch(f'/turismo_carregar.php?id={category}', {'pagina': 1, 'quantidade_por_pagina': 100}))
        for record in listing.records:
            records.setdefault(record['source_id'], {**record, 'categories': []})['categories'].append(label)
        print(f'{label}: {len(listing.records)} registros', flush=True)
    for index, record in enumerate(records.values()):
        try:
            detail = Detail()
            detail.feed(fetch(record['source_url']))
            record['address_raw'] = address_line(detail.lines)
            text = ' '.join(detail.lines)
            phone = re.search(r'(?:\(?0?14\)?[ .-]*)[9]?\d{4}[ .-]\d{4}', text)
            record['phone'] = re.sub(r'\D', '', phone.group()).lstrip('0') if phone else ''
            for i, line in enumerate(detail.lines):
                if 'rio de Funcionamento' in line:
                    record['opening_hours'] = ' '.join(detail.lines[i + 1:i + 3]).split('https://')[0][:300]
                    break
            record['service_notes'] = next((line for line in detail.lines if 'de servi' in line.lower()), '')[:250]
            record['links'] = [link for link in detail.links if link.startswith('https://')][:8]
        except (OSError, ValueError):
            record['detail_unavailable'] = True
        if (index + 1) % 10 == 0:
            print(f'Detalhes: {index + 1}/{len(records)}', flush=True)
    payload = {'provider': 'marilia_tourism', 'source_url': ORIGIN + '/-onde-comer-e-beber/',
               'fetched_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'attribution': 'Diretório de Turismo da Prefeitura de Marília',
               'license': '', 'records': list(records.values())}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(f'{len(records)} cadastros públicos salvos em {args.output}', flush=True)


if __name__ == '__main__':
    main()
