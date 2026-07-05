"""Constrói o documento-texto de um restaurante pra virar embedding.
Junta os campos semânticos: nome, descrição, taxonomias, pratos, canais."""


def _names(manager):
    return ", ".join(manager.values_list("name", flat=True))


def build_restaurant_document(restaurant) -> str:
    parts = [f"Restaurante: {restaurant.name}"]
    if restaurant.description:
        parts.append(restaurant.description)

    taxonomies = [
        ("Cozinhas", restaurant.cuisines),
        ("Ambientes", restaurant.ambients),
        ("Modelos de serviço", restaurant.service_models),
        ("Público-alvo", restaurant.target_audiences),
        ("Faixas de preço", restaurant.price_ranges),
        ("Modelos de negócio", restaurant.business_models),
        ("Formatos físicos", restaurant.physical_formats),
    ]
    for label, manager in taxonomies:
        names = _names(manager)
        if names:
            parts.append(f"{label}: {names}")

    items = list(restaurant.items.values_list("name", flat=True))
    if items:
        parts.append(f"Pratos principais: {', '.join(items)}")

    channels = []
    if restaurant.has_dine_in:
        channels.append("salão")
    if restaurant.has_delivery:
        channels.append("delivery")
    if restaurant.has_take_out:
        channels.append("retirada")
    if restaurant.has_drive_thru:
        channels.append("drive-thru")
    if restaurant.has_reservation:
        channels.append("reserva")
    if channels:
        parts.append(f"Canais: {', '.join(channels)}")

    return "\n".join(parts)
