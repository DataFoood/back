import json
import re
import unicodedata
from typing import Literal

from django.db.models import Case, Count, IntegerField, Q, Value, When
from pydantic import BaseModel, ConfigDict, Field

from preferences.models import SearchHistory, UserAmbientAffinity, UserCuisineAffinity, UserPriceAffinity
from restaurants.generation import complete_chat
from restaurants.models import Ambient, Cuisine, PriceRange, RestaurantFavorite, RestaurantView
from restaurants.views import public_catalog

MAX_RECOMMENDATIONS = 50


class SelectionFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    text: str | None = Field(default=None, min_length=1, max_length=200)
    cuisine: int | None = Field(default=None, gt=0)
    ambient: int | None = Field(default=None, gt=0)
    price_range: int | None = Field(default=None, gt=0)
    delivery: bool | None = None


class AssistantTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reply: str = Field(min_length=1, max_length=500)
    ready: bool
    filters: SelectionFilters
    remove_filters: list[Literal["city", "text", "cuisine", "ambient", "price_range", "delivery"]] = Field(default_factory=list, max_length=6)


def taxonomy_choices():
    # shortcut: até 32 tags por categoria no contexto; rever ao ampliar as taxonomias.
    choices = {key: [{"id": row["id"], "name": row["name"][:48]} for row in model.objects.values("id", "name")[:32]]
               for key, model in (("cuisine", Cuisine), ("ambient", Ambient), ("price_range", PriceRange))}
    choices["city"] = [{"name": city} for city in public_catalog().filter(
        addresses__deleted_at__isnull=True, addresses__city__isnull=False,
    ).exclude(addresses__city="").order_by("addresses__city").values_list("addresses__city", flat=True).distinct()[:32]]
    choices["text"] = [{"name": name} for name in public_catalog().order_by("name", "id").values_list("name", flat=True)[:50]]
    return choices


def personal_context(user):
    if user.level < 2 or not user.allow_info:
        return {}
    context = {}
    for key, model, field in (("cuisine", UserCuisineAffinity, "cuisine"),
                              ("ambient", UserAmbientAffinity, "ambient"),
                              ("price_range", UserPriceAffinity, "price_range")):
        rows = model.objects.filter(user=user, score__gt=0).order_by("-is_manual", "-score")
        context[key] = [{"id": pk, "name": name[:40]} for pk, name in rows.values_list(f"{field}_id", f"{field}__name")[:3]]
    for key, model, order in (("favorites", RestaurantFavorite, "-created_at"), ("views", RestaurantView, "-count")):
        rows = model.objects.filter(user=user, restaurant__in=public_catalog()).order_by(order, "id")
        context[key] = [{"id": pk, "name": name[:80]} for pk, name in rows.values_list("restaurant_id", "restaurant__name")[:3]]
    context["recent_searches"] = [query[:80] for query in SearchHistory.objects.filter(user=user).values_list("query", flat=True)[:2]]
    return {key: value for key, value in context.items() if value}


def folded(text):
    return " ".join(re.sub(r"[^\w]+", " ", "".join(
        char for char in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(char)
    )).split())


def personal_discovery(query):
    return folded(query) in ("sugira algo pelos meus gostos", "o que combina comigo", "me surpreenda")


def conversation_guidance(filters, choices, profile, ids, ready):
    guidance = {"suggestions": []}
    if ready and not ids:
        for key in ("ambient", "cuisine", "price_range", "text", "city"):
            if key in filters:
                label = next((row["name"] for row in choices.get(key, []) if row.get("id") == filters[key]), filters[key])
                guidance["suggestions"].append(f"Retire {label}")
        if not guidance["suggestions"]:
            guidance["suggestions"].append("Mostrar todos")
    else:
        candidates = public_catalog().filter(pk__in=ids) if ids else public_catalog()
        for key, relation in (("cuisine", "cuisines"), ("ambient", "ambients"), ("price_range", "price_ranges")):
            if key in filters:
                continue
            available = set(candidates.values_list(f"{relation}__pk", flat=True))
            for row in choices[key]:
                if row["id"] in available:
                    turn = interpret_turn(row["name"], filters, choices)
                    if turn and turn.ready and getattr(turn.filters, key) == row["id"]:
                        guidance["suggestions"].append(row["name"])
        if not filters.get("city"):
            guidance["suggestions"] = [row["name"] for row in choices["city"][:1]] + guidance["suggestions"]
    guidance["suggestions"] = list(dict.fromkeys(guidance["suggestions"]))[:3]
    if profile and ids:
        first = public_catalog().filter(pk=ids[0]).prefetch_related("cuisines", "ambients", "price_ranges").first()
        note = "Considerei seu perfil, mas não encontrei afinidades cadastradas entre estas opções."
        if first:
            matches = [row["name"] for key, relation in (("cuisine", "cuisines"), ("ambient", "ambients"), ("price_range", "price_ranges"))
                       for row in profile.get(key, []) if row["id"] in {tag.pk for tag in getattr(first, relation).all()}]
            if first.pk in {row["id"] for row in profile.get("favorites", [])}:
                note = f"{first.name} aparece primeiro e está nos seus favoritos. Seus pedidos continuam tendo prioridade."
            elif matches:
                note = f"{first.name} combina com seus gostos por {', '.join(matches[:2])}. Isso ajudou a ordenar as opções."
            elif first.pk in {row["id"] for row in profile.get("views", [])}:
                note = f"Você já acessou {first.name}. Esse interesse ajudou a ordenar as opções."
        guidance["personalization_note"] = note
    return guidance


ALIASES = {
    "Ao Ar Livre": ("lugar aberto", "ambiente aberto", "area externa"),
    "Pizza & Massas": ("pizza", "pizzaria", "massas"),
    "Japonesa": ("japones", "sushi"), "Italiana": ("italiano",),
    "Cafeteria": ("cafe",), "Churrasco/Grelhados": ("churrasco", "grelhados"),
}


def interpret_turn(query, previous_filters, choices):
    text, patch, removed = folded(query), {}, []
    if text in ("sem filtros", "limpar filtros", "mostrar todos", "todos os restaurantes", "qualquer restaurante"):
        return AssistantTurn(reply="Você pode abrir as opções ou continuar refinando.", ready=True,
                             filters={}, remove_filters=list(previous_filters))
    for key in ("city", "text", "cuisine", "ambient", "price_range"):
        matches = []
        for row in choices.get(key, []):
            name = row["name"]
            aliases = {folded(name), folded(name.partition("(")[0]), *(folded(alias) for alias in ALIASES.get(name, ()))}
            for alias in sorted(aliases, key=len, reverse=True):
                if not alias:
                    continue
                match = re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text)
                if match is None:
                    continue
                if key == "ambient" and alias in ("lugar aberto", "ambiente aberto") and "aberto agora" in text:
                    continue
                if key == "price_range" and alias in ("premium", "luxo") and not re.search(r"(?:preco|faixa) (?:de )?" + alias, text):
                    continue
                before = text[:match.start()]
                remove = bool(re.search(r"(?:nao (?:precisa|preciso)(?: ser| de)?(?: em)?|sem filtro(?: de)?|qualquer|remova|retire|tire) $", before))
                if not remove and re.search(r"(?:nao quero|sem|evitar) $", before):
                    return None  # Exclusão não é o mesmo que retirar um filtro.
                matches.append((name if key in ("city", "text") else row["id"], remove))
                break
        if len(matches) > 1:
            return None  # Não escolher arbitrariamente entre cidades ou categorias.
        if matches:
            value, remove = matches[0]
            if remove:
                removed.append(key)
            else:
                patch[key] = value
    delivery = re.search(r"\b(?:delivery|entrega)\b", text)
    if delivery:
        patch["delivery"] = not bool(re.search(r"(?:sem|nao (?:precisa|preciso)(?: de| ter)?) $", text[:delivery.start()]))
    ready = bool(patch or removed) or bool(previous_filters and text in ("sim", "pode mostrar", "ver recomendacoes", "mostrar opcoes"))
    reply = "Você pode abrir as opções ou continuar refinando." if ready else "Qual cidade, tipo de cozinha ou ambiente você procura?"
    return AssistantTurn(reply=reply, ready=ready, filters=patch, remove_filters=removed)


def compose_reply(query, messages, filters, choices, profile, ids):
    labels = {}
    field_names = {"city": "cidade", "text": "nome", "cuisine": "cozinha", "ambient": "ambiente", "price_range": "preco", "delivery": "delivery"}
    for key, value in filters.items():
        label = next((row["name"] for row in choices.get(key, []) if row.get("id") == value), value)
        labels[field_names[key]] = label[:80] if isinstance(label, str) else label
    rows = public_catalog().filter(pk__in=ids[:2]).prefetch_related("cuisines", "ambients")
    by_id = {row.pk: {"nome": row.name[:80], "cozinhas": [tag.name[:24] for tag in row.cuisines.all()[:2]],
                      "ambientes": [tag.name[:24] for tag in row.ambients.all()[:2]]} for row in rows}
    context = {"pedido": query[:160], "busca": labels, "restaurantes": [by_id[pk] for pk in ids[:2] if pk in by_id]}
    if profile:
        context["preferencias"] = [row["name"][:40] for key in ("cuisine", "ambient", "price_range") for row in profile.get(key, [])[:1]]
        context["favoritos"] = [row["name"][:60] for row in profile.get("favorites", [])[:1]]
        context["visitados"] = [row["name"][:60] for row in profile.get("views", [])[:1]]
        context["pesquisas"] = [text[:60] for text in profile.get("recent_searches", [])[:1]]
    history = [message["text"][:80] for message in messages[-4:] if message.get("role") == "user" and isinstance(message.get("text"), str)]
    if history:
        context["pedido_anterior"] = history[-1]
    answer = complete_chat([
        {"role": "system", "content": "Ajude o cliente a escolher onde comer. Sugira em português um dos restaurantes cadastrados, citando o nome exatamente como foi fornecido. Use somente fatos dos dados. Escreva até duas frases."},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False, separators=(",", ":"))},
    ], num_ctx=1024, num_predict=120)
    if not answer or len(answer) > 500 or answer.lstrip().startswith(("{", "[", "```")):
        return None
    answer = answer.replace("**", "")  # O chat exibe texto simples.
    normalized = folded(answer)
    if re.search(r"nao (?:ha|encontrei|existem|temos) (?:nenhum |nenhuma |informacoes sobre )?(?:restaurantes|opcoes|locais)", normalized):
        return None
    if not any(row["nome"] and re.search(r"(?<!\w)" + re.escape(folded(row["nome"])) + r"(?!\w)", normalized)
               for row in context["restaurantes"]):
        return None
    return answer


def select_restaurants(filters, profile):
    qs = public_catalog()
    if filters.get("city"):
        qs = qs.filter(addresses__city__iexact=filters["city"].strip(), addresses__deleted_at__isnull=True)
    if filters.get("text"):
        text = filters["text"].strip()
        qs = qs.filter(Q(name__icontains=text) | Q(description__icontains=text) | Q(items__name__icontains=text))
    for key, field in (("cuisine", "cuisines"), ("ambient", "ambients"), ("price_range", "price_ranges")):
        if filters.get(key):
            qs = qs.filter(**{f"{field}__id": filters[key]})
    if filters.get("delivery") is True:
        qs = qs.filter(has_delivery=True)
    ordering = ["-average_rating", "name", "id"]
    if profile:
        score = Value(0, output_field=IntegerField())
        for key, field in (("cuisine", "cuisines"), ("ambient", "ambients"), ("price_range", "price_ranges")):
            ids = [row["id"] for row in profile.get(key, [])]
            if ids:
                score += Count(field, filter=Q(**{f"{field}__id__in": ids}), distinct=True)
        for key, weight in (("favorites", 2), ("views", 1)):
            ids = [row["id"] for row in profile.get(key, [])]
            if ids:
                score += Case(When(pk__in=ids, then=Value(weight)), default=Value(0))
        qs = qs.annotate(chat_preference=score)
        ordering.insert(0, "-chat_preference")
    ids = list(qs.order_by(*ordering).values_list("pk", flat=True).distinct()[:MAX_RECOMMENDATIONS + 1])
    return ids[:MAX_RECOMMENDATIONS], len(ids) > MAX_RECOMMENDATIONS
