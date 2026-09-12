from collections import defaultdict

from restaurants.models import Restaurant, RestaurantFavorite, RestaurantView

from .models import UserAmbientAffinity, UserCuisineAffinity, UserPriceAffinity

# Pesos dos sinais (viram tabela de config no ranking, Fase 4).
VIEW_WEIGHT = 1.0
FAVORITE_WEIGHT = 5.0

# (campo M2M no Restaurant, model de afinidade, nome do FK)
DIMENSIONS = [
    ("cuisines", UserCuisineAffinity, "cuisine"),
    ("ambients", UserAmbientAffinity, "ambient"),
    ("price_ranges", UserPriceAffinity, "price_range"),
]


def _interaction_weights(user) -> dict[int, float]:
    """restaurante_id -> peso acumulado de interação do usuário."""
    weights: dict[int, float] = defaultdict(float)
    for rid, count in RestaurantView.objects.filter(user=user).values_list("restaurant", "count"):
        weights[rid] += VIEW_WEIGHT * count
    for rid in RestaurantFavorite.objects.filter(user=user).values_list("restaurant", flat=True):
        weights[rid] += FAVORITE_WEIGHT
    return weights


def compute_user_preferences(user) -> None:
    """Recalcula as afinidades do usuário a partir das interações.
    Linhas com is_manual=True são preservadas (controle do usuário)."""
    weights = _interaction_weights(user)
    if not weights:
        return

    rids = list(weights.keys())
    for m2m_field, AffinityModel, fk_name in DIMENSIONS:
        raw: dict[int, float] = defaultdict(float)
        pairs = Restaurant.objects.filter(id__in=rids).values_list("id", m2m_field)
        for rid, value_id in pairs:
            if value_id is None:
                continue
            raw[value_id] += weights[rid]
        if not raw:
            continue

        mx = max(raw.values())
        for value_id, total in raw.items():
            norm = round(total / mx, 4) if mx else 0.0
            obj, created = AffinityModel.objects.get_or_create(
                user=user, **{f"{fk_name}_id": value_id}, defaults={"score": norm}
            )
            if not created and not obj.is_manual:
                obj.score = norm
                obj.save(update_fields=["score"])
