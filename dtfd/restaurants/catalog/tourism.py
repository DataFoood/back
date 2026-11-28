"""Carga offline do diretório oficial, com identidade e créditos preservados."""
import re
import unicodedata
from urllib.parse import urlparse

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from address.models import Address
from restaurants.models import Restaurant, RestaurantSource, RestaurantImage, Cuisine, Ambient

HOST = 'turismo.marilia.sp.gov.br'


def identity(value):
    return re.sub(r'[^a-z0-9]', '', ''.join(c for c in unicodedata.normalize('NFKD', value.lower()) if not unicodedata.combining(c)))


def address_parts(raw):
    raw = re.sub(r'^Endere[çc]o\s*:\s*', '', raw, flags=re.I)
    match = re.match(r'(.+?)(?:,\s*|\s+n[ºo°]\s*)(\d+\w*)\s*[-–,]?\s*(.*)', raw, re.I)
    street, number, rest = match.groups() if match else (raw, '', '')
    rest = re.sub(r'\bCEP[.: ]*\s*\d{2}\.?\d{3}[-.]?\d{3}\s*[-–,]?\s*', '', rest, flags=re.I)
    neighborhood = re.split(r'[,–-]\s*Mar[íi]lia\b', rest, flags=re.I)[0].split(',')[0].strip(' -–.')[:100] if rest else ''
    if identity(neighborhood) == 'marilia':
        neighborhood = ''
    zipcode = re.search(r'\b\d{2}\.?\d{3}[-.]?\d{3}\b', raw)
    zip_digits = re.sub(r'\D', '', zipcode.group()) if zipcode else ''
    return {'street': street[:255], 'number': number[:20], 'neighborhood': neighborhood,
            'city': 'Marília', 'state': 'SP', 'zipcode': zip_digits[:5] + '-' + zip_digits[5:] if zip_digits else ''}


def name_tokens(name):
    generic = {'restaurante', 'restaurantes', 'pizzaria', 'bar', 'cafe', 'cafeteria', 'churrascaria', 'marilia', 'hamburgueria', 'lanchonete', 'casa', 'grill', 'e', 'de', 'do', 'da'}
    return {identity(word) for word in name.split() if len(identity(word)) >= 4 and identity(word) not in generic}


def street_identity(street):
    return identity(re.sub(r'^(?:Rua\.?|R\.|Avenida|Av\.)\s*', '', street, flags=re.I))


def validate_record(record):
    if not isinstance(record, dict) or not isinstance(record.get('name'), str) or not record['name'].strip():
        raise ValueError('Cadastro turístico inválido.')
    parsed = urlparse(record.get('source_url', ''))
    if parsed.scheme != 'https' or parsed.hostname != HOST or not re.fullmatch(r'/turismo/[^/]+/\d+', parsed.path):
        raise ValueError('Fonte turística inválida.')
    if str(record.get('source_id')) != parsed.path.rsplit('/', 1)[-1]:
        raise ValueError('Identidade turística inválida.')
    for field, length in (('name', 200), ('address_raw', 400), ('phone', 20), ('opening_hours', 300), ('service_notes', 250)):
        if not isinstance(record.get(field, ''), str) or len(record.get(field, '')) > length:
            raise ValueError('Campo turístico inválido: ' + field)
    image = urlparse(record.get('image_url', ''))
    if record.get('image_url') and (image.scheme != 'https' or image.hostname != HOST or not image.path.startswith('/fotos/') or len(record['image_url']) > 200):
        raise ValueError('Imagem turística inválida.')


@transaction.atomic
def upsert(record, fetched_at):
    validate_record(record)
    external = str(record['source_id'])
    # A fonte possui uma chave estável; a trava cobre também a primeira carga.
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s, %s)', [3529005, int(external)])
    source = RestaurantSource.objects.select_related('restaurant').filter(provider='marilia_tourism', external_id=external).first()
    if source and source.restaurant.deleted_at:
        return 'removed'
    restaurant = source.restaurant if source else None
    parts = address_parts(record.get('address_raw', ''))
    if restaurant is None:
        # Só une fontes com nome E telefone/endereço iguais; filiais homônimas
        # não são fundidas por uma aproximação nominal.
        for candidate in Restaurant.objects.filter(is_demo=False):
            exact_name = identity(candidate.name) == identity(record['name'])
            shared_name = bool(name_tokens(candidate.name) & name_tokens(record['name']))
            if not (exact_name or shared_name):
                continue
            same_phone = bool(record.get('phone') and re.sub(r'\D', '', candidate.phone) == record['phone'])
            known_addresses = list(candidate.addresses.all())
            same_address = any(parts['number'] and address.number == parts['number'] and street_identity(address.street) == street_identity(parts['street']) for address in known_addresses)
            conflicting_address = bool(parts['number'] and any(address.number for address in known_addresses) and not same_address)
            if same_address or (same_phone and not conflicting_address):
                restaurant = candidate
                break
    created = restaurant is None
    if created:
        restaurant = Restaurant.objects.create(name=record['name'], slug='turismo-marilia-' + external, origin='tourism')
    source = source or RestaurantSource(provider='marilia_tourism', external_id=external, restaurant=restaurant)
    source.url = record['source_url']
    source.attribution = 'Diretório de Turismo da Prefeitura de Marília'
    source.license = ''  # A licença das fotos não é inferida da licença do OSM.
    source.fetched_at = fetched_at
    source.data = record
    source.needs_review = Restaurant.objects.filter(name__iexact=restaurant.name, is_demo=False).exclude(pk=restaurant.pk).exists()
    source.save()
    if restaurant.owner_id is None:
        categories = record.get('categories', [])
        cuisine_map = {'Churrascaria': 'Churrasco/Grelhados', 'Hamburgueria': 'Americana',
                       'Restaurantes mexicanos': 'Mexicana', 'Pizzarias': 'Pizza & Massas'}
        cuisine_names = [cuisine_map[c] for c in categories if c in cuisine_map]
        restaurant.cuisines.add(*Cuisine.objects.filter(name__in=cuisine_names))
        if 'Cafeterias' in categories:
            restaurant.ambients.add(*Ambient.objects.filter(name='Cafeteria'))
        restaurant.phone = restaurant.phone or record.get('phone', '')
        if not restaurant.description or restaurant.origin == 'tourism':
            restaurant.description = ', '.join(categories) + ' em Marília.' + (f" No bairro {parts['neighborhood']}." if parts['neighborhood'] else '')
        notes = identity(record.get('service_notes', ''))
        if 'entrega' in notes or 'delivery' in notes:
            restaurant.has_delivery = True
        if 'retirada' in notes:
            restaurant.has_take_out = True
        if 'refeicaonolocal' in notes:
            restaurant.has_dine_in = True
        image = record.get('image_url', '')
        if image and not any(word in image.lower() for word in ('sem_imagem', 'sem-imagem', 'no_image')):
            RestaurantImage.objects.get_or_create(restaurant=restaurant, url=image,
                defaults={'source_url': source.url, 'attribution': source.attribution})
            if not restaurant.cover_image:
                restaurant.cover_image = image
        restaurant.save()
        if record.get('address_raw'):
            imported_address = restaurant.addresses.filter(label='Turismo de Marília').first()
            if imported_address:
                for key, value in parts.items():
                    setattr(imported_address, key, value)
                imported_address.save()
            elif not restaurant.addresses.exists():
                Address.objects.create(content_type=ContentType.objects.get_for_model(Restaurant), object_id=restaurant.pk, label='Turismo de Marília', is_default=True, **parts)
    return 'created' if created else 'updated'
