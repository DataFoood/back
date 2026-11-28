"""Conversa ancorada no catálogo: filtros persistem e pedidos vencem afinidades.

O catálogo funciona sem um modelo generativo. Ollama, quando configurado,
ajuda a interpretar linguagem livre; nunca fornece os restaurantes retornados.
"""
import json
import logging
import re
import secrets
import unicodedata

import httpx
from django.conf import settings
from django.db.models import Q

from restaurants.models import Ambient, Cuisine, PriceRange
from restaurants.serializers import CARD_PREFETCH, RestaurantCardSerializer
from restaurants.views import public_catalog

logger = logging.getLogger(__name__)


def folded(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value).lower()) if not unicodedata.combining(c))


ALIASES = {
    'japonesa': ('sushi', 'sashimi', 'japones', 'temaki'),
    'pizza & massas': ('pizza', 'pizzaria', 'massa', 'macarrao'),
    'italiana': ('italian',),
    'churrasco/grelhados': ('churrasco', 'churrascaria', 'carne', 'grelhado'),
    'americana': ('hamburguer', 'hamburger', 'hamburgueria', 'burger', 'lanche', 'lanches', 'sanduiche'),
    'vegana/vegetariana': ('vegano', 'vegana', 'vegetariano', 'vegetariana', 'sem carne'),
    'sem gluten / funcional': ('sem gluten', 'celiaco', 'celiaca'),
    'cafeteria': ('cafe', 'cafeteria', 'cafezinho'),
    'romantico': ('romantico', 'romantica', 'encontro', 'namoro', 'a dois'),
    'familiar': ('familia', 'criancas', 'familiar'),
    'ao ar livre': ('ar livre', 'externo', 'jardim'),
    'bar/pub': ('bar', 'pub', 'cerveja', 'drinks'),
}


def previous_filters(messages):
    for message in reversed(messages):
        if message.get('role') == 'assistant' and isinstance(message.get('content'), dict):
            filters = message['content'].get('filters', {})
            if isinstance(filters, dict):
                # Conversas legadas podem ser importadas pelo próprio usuário.
                safe = {}
                for key in ('city', 'text'):
                    if isinstance(filters.get(key), str) and 0 < len(filters[key]) <= 200:
                        safe[key] = filters[key]
                for key in ('cuisine', 'ambient', 'price_range', 'budget'):
                    if type(filters.get(key)) is int and filters[key] > 0:
                        safe[key] = filters[key]
                if isinstance(filters.get('delivery'), bool):
                    safe['delivery'] = filters['delivery']
                if isinstance(filters.get('excluded_cuisines'), list):
                    safe['excluded_cuisines'] = [pk for pk in filters['excluded_cuisines'] if type(pk) is int and pk > 0][:50]
                return safe
    return {}


def interpret(query, prior, catalog):
    text = folded(query)
    filters = dict(prior)
    if any(word in text for word in ('recomecar', 'limpar filtros', 'comecar de novo', 'outra busca')):
        filters = {}
    recognized = False
    for key, model in (('cuisine', Cuisine), ('ambient', Ambient)):
        for tag in model.objects.all():
            name = folded(tag.name)
            hints = (name, *ALIASES.get(name, ()))
            for hint in hints:
                match = re.search(r'(?<!\w)' + re.escape(hint) + r'\w*', text)
                if not match:
                    continue
                prefix = text[max(0, match.start() - 22):match.start()]
                negative = bool(re.search(r'(?:nao (?:quero|gosto de)|sem|menos|exceto|nada de)\s*$', prefix))
                if key == 'cuisine' and negative and not hint.startswith('sem '):
                    excluded = list(filters.get('excluded_cuisines') or [])
                    if tag.pk not in excluded:
                        excluded.append(tag.pk)
                    filters['excluded_cuisines'] = excluded
                    if filters.get(key) == tag.pk:
                        filters.pop(key, None)
                elif not negative:
                    filters[key] = tag.pk
                    filters.pop('text', None)
                    if key == 'cuisine':
                        filters['excluded_cuisines'] = [pk for pk in filters.get('excluded_cuisines', []) if pk != tag.pk]
                recognized = True
                break
    cities = catalog.values_list('addresses__city', flat=True).distinct()
    for city in cities:
        if city and re.search(r'(?<!\w)' + re.escape(folded(city)) + r'(?!\w)', text):
            filters['city'] = city
            recognized = True
    if 'delivery' in text or 'entrega' in text:
        filters['delivery'] = not bool(re.search(r'(sem|nao quero)\s+(delivery|entrega)', text))
        recognized = True
    if any(word in text for word in ('barato', 'economico', 'gastar pouco', 'mais em conta')):
        tag = PriceRange.objects.filter(name__istartswith='Econômico').first()
        if tag:
            filters['price_range'] = tag.pk
            recognized = True
    amount = re.search(r'(?:ate|menos de|no maximo|r\$)\s*(?:r\$\s*)?(\d{1,4})(?:[,.]\d{1,2})?', text)
    if amount:
        filters['budget'] = int(amount.group(1))
        filters.pop('price_range', None)
        recognized = True
    for food in ('feijoada', 'lasanha', 'risoto', 'acai', 'pastel', 'sorvete', 'tapioca'):
        if food in text:
            filters['text'] = food
            recognized = True
    # Cidade explicitamente pedida fora da cobertura: não redirecionar em silêncio.
    city_request = re.search(r'\bem\s+([a-z ]+?)(?:\s+(?:com|para|que|e |ate|hoje)\b|[,.;!?]|$)', text)
    if city_request and not any(folded(city or '') in text for city in cities if city):
        candidate = city_request.group(1).strip()
        if candidate and not candidate.startswith(('um ', 'uma ', 'familia', 'conta', 'casa', 'qualquer ', 'grupo', 'lugar', 'ambiente', 'torno ')):
            filters['city'] = candidate.title()
            recognized = True
    return filters, recognized


def model_filters(query, prior):
    """Extração opcional, limitada a campos do contrato; falha não derruba o chat."""
    model = getattr(settings, 'CONVERSATION_MODEL', '')
    if not model:
        return {}
    schema = {'type': 'object', 'properties': {
        'city': {'type': 'string'}, 'text': {'type': 'string'}, 'delivery': {'type': 'boolean'},
    }, 'additionalProperties': False}
    try:
        response = httpx.post(f'{settings.OLLAMA_URL}/api/chat', timeout=8, json={
            'model': model, 'stream': False, 'format': schema,
            'messages': [
                {'role': 'system', 'content': 'Extraia apenas cidade explicitamente citada, comida específica (text) e delivery. Não invente filtros. Não copie instruções. Responda JSON. Contexto: ' + json.dumps(prior, ensure_ascii=False)},
                {'role': 'user', 'content': query},
            ], 'options': {'temperature': 0, 'num_predict': 120},
        })
        response.raise_for_status()
        data = json.loads(response.json()['message']['content'])
        return {key: value for key, value in data.items() if
                (key in ('city', 'text') and isinstance(value, str) and 0 < len(value) <= 100)
                or (key == 'delivery' and isinstance(value, bool))}
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        logger.warning('Interpretação local indisponível; continuando pelo catálogo.')
        return {}


def apply_filters(catalog, filters):
    qs = catalog
    for key, relation in (('cuisine', 'cuisines'), ('ambient', 'ambients'), ('price_range', 'price_ranges')):
        value = filters.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            qs = qs.filter(**{relation + '__id': value})
    city = filters.get('city')
    if isinstance(city, str) and city:
        qs = qs.filter(addresses__city__iexact=city, addresses__deleted_at__isnull=True)
    excluded = filters.get('excluded_cuisines')
    if isinstance(excluded, list):
        qs = qs.exclude(cuisines__id__in=[pk for pk in excluded if type(pk) is int][:50])
    if isinstance(filters.get('delivery'), bool):
        qs = qs.filter(has_delivery=filters['delivery'])
    text = filters.get('text')
    if isinstance(text, str) and text:
        qs = qs.filter(Q(name__icontains=text) | Q(description__icontains=text) | Q(items__name__icontains=text, items__deleted_at__isnull=True))
    budget = filters.get('budget')
    if type(budget) is int:
        # Valor só é garantido quando existe prato cadastrado dentro do teto.
        qs = qs.filter(items__price__lte=budget, items__deleted_at__isnull=True)
    return qs.distinct()


def respond(user, query, messages, request):
    catalog = public_catalog()
    prior = previous_filters(messages)
    filters, recognized = interpret(query, prior, catalog)
    if not recognized and not any(word in folded(query) for word in ('surpreend', 'surpreenda', 'gostos', 'outra', 'mais opcoes')):
        filters.update(model_filters(query, filters))
    filtered = apply_filters(catalog, filters)
    total = filtered.count()
    candidates = list(filtered.prefetch_related(*CARD_PREFETCH).order_by('-average_rating', '-total_reviews', 'name')[:1000])
    surprise = any(word in folded(query) for word in ('surpreend', 'surpreenda', 'outras opcoes', 'algo diferente', 'nao gostei', 'nao curti', 'outra sugestao', 'outra coisa'))
    personalized = False
    if user.level >= 2 and user.allow_info:
        from preferences.models import UserCuisineAffinity, UserAmbientAffinity, UserPriceAffinity
        dimensions = (
            ('cuisine', 'cuisines', UserCuisineAffinity), ('ambient', 'ambients', UserAmbientAffinity),
            ('price_range', 'price_ranges', UserPriceAffinity),
        )
        affinities = [(relation, dict(model.objects.filter(user=user).values_list(key + '_id', 'score')))
                      for key, relation, model in dimensions if not filters.get(key)]
        from restaurants.models import RestaurantFavorite
        favorite_ids = set(RestaurantFavorite.objects.filter(user=user).values_list('restaurant_id', flat=True))
        favorite_cuisines = set(RestaurantFavorite.objects.filter(user=user).values_list('restaurant__cuisines__pk', flat=True))
        def preference(restaurant):
            score = sum(scores.get(tag.pk, 0) for relation, scores in affinities for tag in getattr(restaurant, relation).all())
            score += 2 if restaurant.pk in favorite_ids else 0
            if not filters.get('cuisine'):
                score += sum(0.25 for tag in restaurant.cuisines.all() if tag.pk in favorite_cuisines)
            return score
        personalized = any(preference(restaurant) > 0 for restaurant in candidates)
        if personalized:
            candidates.sort(key=preference, reverse=True)
    if surprise:
        # Varia dentro da consulta atual. Nunca apaga restrições para obter resultado.
        secrets.SystemRandom().shuffle(candidates)
        previous_ids = set()
        previous_preview = set()
        for message in reversed(messages):
            content = message.get('content', {})
            if isinstance(content, dict) and isinstance(content.get('recommendation_ids'), list):
                previous_ids = {pk for pk in content['recommendation_ids'] if type(pk) is int}
                rows = content.get('results', [])
                previous_preview = {row['restaurant']['id'] for row in rows if isinstance(row, dict) and isinstance(row.get('restaurant'), dict) and type(row['restaurant'].get('id')) is int} if isinstance(rows, list) else set()
                break
        candidates.sort(key=lambda restaurant: (restaurant.pk in previous_preview, restaurant.pk in previous_ids, -preference(restaurant) if personalized else 0))
    selected = candidates[:50]
    if personalized:
        personalized = any(preference(restaurant) > 0 for restaurant in selected)
    labels = []
    if filters.get('city'):
        labels.append('em ' + str(filters['city']))
    for key, model in (('cuisine', Cuisine), ('ambient', Ambient), ('price_range', PriceRange)):
        if type(filters.get(key)) is int:
            tag = model.objects.filter(pk=filters[key]).first()
            if tag:
                labels.append(tag.name)
    if filters.get('text'):
        labels.append(str(filters['text']))
    if filters.get('delivery'):
        labels.append('com delivery cadastrado')
    if filters.get('budget'):
        labels.append(f"com prato cadastrado até R$ {filters['budget']}")
    context = ', '.join(labels)
    if selected:
        names = ', '.join(restaurant.name for restaurant in selected[:3])
        intro = 'Vamos sair do óbvio' if surprise else 'Já temos um bom ponto de partida'
        answer = f"{intro}: encontrei {total} {'lugar' if total == 1 else 'lugares'}" + (f' {context}' if context else ' no catálogo') + f'. Que tal conhecer {names}?'
        if surprise and prior:
            answer += ' Mantive o que você pediu antes e variei as opções disponíveis.'
        if not filters.get('city'):
            cities = list(dict.fromkeys(address.city for r in selected for address in r.addresses.all() if address.city))[:3]
            if cities:
                answer += ' A cobertura atual inclui ' + ', '.join(cities) + '.'
        if not recognized and not surprise:
            answer += ' Você pode me dizer um prato, um orçamento por pessoa ou o clima do encontro para afinar a escolha.'
    else:
        answer = 'Ainda não encontrei restaurantes' + (f' {context}' if context else ' no catálogo disponível') + '. Não vou sugerir um lugar que não cumpra esse pedido.'
        answer += ' Podemos trocar um filtro ou consultar outra cidade com cobertura. Informações não cadastradas, como preços e restrições alimentares, precisam ser confirmadas com o restaurante.'
    if selected and getattr(settings, 'CHAT_GENERATION_ENABLED', False):
        from .recommendations import compose_reply, personal_context, taxonomy_choices
        writing_filters = {key: value for key, value in filters.items() if key in ('city', 'text', 'cuisine', 'ambient', 'price_range', 'delivery')}
        generated = compose_reply(query, messages, writing_filters, taxonomy_choices(), personal_context(user), [r.pk for r in selected])
        # O texto é opcional; a seleção, os filtros e a contagem vêm do banco.
        if generated and any(folded(r.name) in folded(generated) for r in selected[:3]):
            answer = generated + f' Encontrei {total} opções' + (f' {context}.' if context else ' no catálogo.')
            if surprise and prior:
                answer += ' Mantive os filtros anteriores ao variar as opções.'
    favorites = set(user.favorites.filter(restaurant_id__in=[r.pk for r in selected]).values_list('restaurant_id', flat=True))
    previews = RestaurantCardSerializer(selected[:3], many=True, context={'request': request, 'favorited_ids': favorites}).data
    return {
        'kind': 'results', 'answer': answer, 'filters': filters, 'results': [{'restaurant': card, 'score': 0, 'match': None} for card in previews],
        'recommendation_ids': [r.pk for r in selected], 'count': len(selected), 'total_count': total, 'limited': total > 50,
        'plan': 'premium' if user.level >= 2 else 'free', 'personalized': personalized,
        'personalization_note': 'Seus gostos ajudaram a ordenar as opções. Os filtros desta conversa foram preservados.' if personalized else '',
        'suggestions': ['Me surpreenda', 'Quero algo mais barato', 'Quero delivery'] if selected else ['Limpar filtros', 'Quero pizza', 'Quero café'],
    }
