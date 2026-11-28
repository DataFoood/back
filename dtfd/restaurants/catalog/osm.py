"""Importação OSM limitada a Marília: idempotente, atribuída e sem scraping."""
import hashlib
import math
from decimal import Decimal
from urllib.parse import urlparse, quote

import httpx
from django.contrib.contenttypes.models import ContentType
from django.db import connection, transaction
from django.utils import timezone

from address.models import Address
from restaurants.models import Restaurant, RestaurantSource, RestaurantImage, Cuisine, Ambient, BusinessHour

ENDPOINT = 'https://overpass-api.de/api/interpreter'
ATTRIBUTION = '© OpenStreetMap contributors'
LICENSE = 'ODbL-1.0'
REGION_CODE = '3529005'
# A consulta usa o município, não um retângulo que inclui cidades vizinhas.
QUERY = '''[out:json][timeout:60];
area["boundary"="administrative"]["admin_level"="8"]["IBGE:GEOCODIGO"="3529005"]->.city;
nwr["amenity"~"^(restaurant|cafe|fast_food|food_court|bar|pub|ice_cream)$"](area.city);
out center tags;'''
TAGS = {'name', 'amenity', 'cuisine', 'phone', 'contact:phone', 'website', 'contact:website',
        'opening_hours', 'addr:street', 'addr:housenumber', 'addr:suburb', 'addr:city', 'addr:postcode',
        'description', 'description:pt', 'email', 'contact:email', 'image', 'wikimedia_commons',
        'delivery', 'takeaway', 'drive_through', 'reservation', 'website:menu', 'contact:menu'}


def fetch():
    # Uma consulta por execução, sem loops agressivos contra serviço público.
    response = httpx.post(ENDPOINT, data={'data': QUERY}, timeout=90,
                          headers={'User-Agent': 'DataFoodCatalog/1.0 (manual city import)'})
    response.raise_for_status()
    data = response.json()
    if data.get('remark'):
        raise ValueError('Overpass retornou resultado parcial; tente mais tarde.')
    return data


def normalize(element):
    if not isinstance(element, dict) or element.get('type') not in ('node', 'way', 'relation'):
        return None
    if not isinstance(element.get('id'), int) or element['id'] <= 0:
        return None
    tags = element.get('tags') or {}
    if not isinstance(tags, dict) or not isinstance(tags.get('name'), str) or not tags['name'].strip():
        return None
    if tags.get('amenity') not in ('restaurant', 'cafe', 'fast_food', 'food_court', 'bar', 'pub', 'ice_cream'):
        return None
    center = element.get('center') or element
    try:
        lat, lon = float(center['lat']), float(center['lon'])
    except (KeyError, ValueError, TypeError):
        return None
    if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    clean = {key: value[:1000] for key, value in tags.items() if key in TAGS and isinstance(value, str)}
    return {'external_id': f"{element['type']}/{element['id']}", 'tags': clean,
            'latitude': round(lat, 6), 'longitude': round(lon, 6)}


def safe_website(raw):
    try:
        parsed = urlparse(raw)
        return raw if parsed.scheme in ('https', 'http') and parsed.hostname and not parsed.username and not parsed.password and len(raw) <= 200 else ''
    except ValueError:
        return ''


def enrich_tags(restaurant, tags, source):
    """Apenas atributos publicados pela fonte, sem inventar avaliações/preços."""
    from .hours import parse_hours
    cuisine_map = {
        'brazilian': 'Brasileira', 'regional': 'Regional (ex: Nordestina, Mineira)',
        'italian': 'Italiana', 'pizza': 'Pizza & Massas', 'japanese': 'Japonesa', 'sushi': 'Japonesa',
        'chinese': 'Chinesa', 'burger': 'Americana', 'barbecue': 'Churrasco/Grelhados',
        'mexican': 'Mexicana', 'arab': 'Árabe', 'seafood': 'Frutos do Mar',
        'vegetarian': 'Vegana/Vegetariana', 'vegan': 'Vegana/Vegetariana',
    }
    cuisine_names = list(dict.fromkeys(cuisine_map[value.strip()] for value in tags.get('cuisine', '').split(';') if value.strip() in cuisine_map))[:3]
    if cuisine_names:
        restaurant.cuisines.set(Cuisine.objects.filter(name__in=cuisine_names))
    ambient = {'cafe': 'Cafeteria', 'bar': 'Bar/Pub', 'pub': 'Bar/Pub'}.get(tags.get('amenity'))
    if ambient:
        restaurant.ambients.add(*Ambient.objects.filter(name=ambient))
    kind = {'cafe': 'Cafeteria', 'bar': 'Bar', 'pub': 'Pub', 'fast_food': 'Lanchonete', 'ice_cream': 'Sorveteria', 'food_court': 'Praça de alimentação'}.get(tags.get('amenity'), 'Restaurante')
    place = ', no bairro ' + tags['addr:suburb'] if tags.get('addr:suburb') else ''
    restaurant.description = tags.get('description:pt', tags.get('description', ''))[:2000] or f'{kind} em Marília{place}.' + (' Cozinha: ' + ', '.join(cuisine_names) + '.' if cuisine_names else '')
    restaurant.email = tags.get('contact:email', tags.get('email', ''))[:254]
    restaurant.menu_url = safe_website(tags.get('website:menu', tags.get('contact:menu', '')))
    for tag, field in (('delivery', 'has_delivery'), ('takeaway', 'has_take_out'), ('drive_through', 'has_drive_thru'), ('reservation', 'has_reservation')):
        if tags.get(tag) in ('yes', 'no'):
            setattr(restaurant, field, tags[tag] == 'yes')
    for day, intervals in parse_hours(tags.get('opening_hours', '')).items():
        BusinessHour.all_objects.update_or_create(restaurant=restaurant, day_week=day,
            defaults={'meta_interval': intervals, 'is_closed': not bool(intervals), 'deleted_at': None})
    image = safe_website(tags.get('image', ''))
    commons = tags.get('wikimedia_commons', '')
    if not image and commons.startswith('File:'):
        image = safe_website('https://commons.wikimedia.org/wiki/Special:FilePath/' + quote(commons[5:]))
    if image:
        RestaurantImage.objects.get_or_create(restaurant=restaurant, url=image,
            defaults={'source_url': source.url, 'attribution': 'Imagem vinculada no OpenStreetMap; consulte a fonte para autoria e licença.'})
        if not restaurant.cover_image:
            restaurant.cover_image = image
    restaurant.save()


@transaction.atomic
def upsert(record, fetched_at=None):
    external = record['external_id']
    # O lock também protege a primeira importação do mesmo objeto concorrente.
    key = int.from_bytes(hashlib.sha256(('osm:' + external).encode()).digest()[:8], 'big', signed=True)
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [key])
    source = RestaurantSource.objects.select_related('restaurant').filter(provider='osm', external_id=external).first()
    tags = record['tags']
    if source and source.restaurant.deleted_at:
        return 'removed'  # reimportar não ressuscita registros removidos
    created = source is None
    if created:
        restaurant = Restaurant.objects.create(
            name=tags['name'].strip()[:200], slug='osm-' + external.replace('/', '-'), origin='osm',
        )
        source = RestaurantSource(restaurant=restaurant, provider='osm', external_id=external)
    else:
        restaurant = source.restaurant
    source.data = record
    source.url = 'https://www.openstreetmap.org/' + external
    source.attribution, source.license, source.fetched_at = ATTRIBUTION, LICENSE, fetched_at or timezone.now()
    # Similaridade nominal pede revisão; nunca fundir estabelecimentos/filiais.
    source.needs_review = Restaurant.objects.filter(name__iexact=tags['name'].strip(), is_demo=False).exclude(pk=restaurant.pk).exists()
    source.save()
    # Dono tem precedência. Atualizar a fonte não sobrescreve cadastro próprio.
    if restaurant.owner_id is None:
        restaurant.name = tags['name'].strip()[:200]
        restaurant.phone = tags.get('contact:phone', tags.get('phone', ''))[:20]
        restaurant.website = safe_website(tags.get('contact:website', tags.get('website', '')))
        restaurant.save(update_fields=['name', 'phone', 'website', 'updated_at'])
        ct = ContentType.objects.get_for_model(Restaurant)
        Address.objects.update_or_create(
            content_type=ct, object_id=restaurant.pk, label='OpenStreetMap',
            defaults=dict(street=tags.get('addr:street', '')[:255], number=tags.get('addr:housenumber', '')[:20],
                          neighborhood=tags.get('addr:suburb', '')[:100], city='Marília', state='SP',
                          zipcode=tags.get('addr:postcode', '')[:20], is_default=True,
                          latitude=Decimal(str(record['latitude'])), longitude=Decimal(str(record['longitude']))),
        )
        enrich_tags(restaurant, tags, source)
    return 'created' if created else 'updated'
