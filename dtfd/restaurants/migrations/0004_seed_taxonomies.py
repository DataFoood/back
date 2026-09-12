from django.db import migrations

SEED = {
    "Cuisine": [
        "Brasileira", "Italiana", "Japonesa", "Chinesa", "Mexicana", "Árabe",
        "Francesa", "Portuguesa", "Indiana", "Americana", "Mediterrânea",
        "Peruana", "Fusion", "Vegana/Vegetariana", "Sem Glúten / Funcional",
        "Frutos do Mar", "Churrasco/Grelhados", "Pizza & Massas",
        "Regional (ex: Nordestina, Mineira)",
    ],
    "Ambient": [
        "Alta Gastronomia (Fine Dining)", "Casual Dining", "Fast Food",
        "Fast Casual", "Bistrô", "Cafeteria", "Familiar", "Temático",
        "Romântico", "Corporativo", "Bar/Pub", "Ao Ar Livre",
        "Dark Kitchen (só delivery)",
    ],
    "ServiceModel": [
        "À la carte", "Buffet a quilo", "Buffet livre", "Rodízio",
        "Self-service (bandejão)", "Fast food (balcão)", "Delivery only",
        "Take-out", "Drive-thru", "Omakase / Menu degustação",
    ],
    "PriceRange": [
        "Econômico (até R$ 30/pessoa)", "Moderado (R$ 30–80/pessoa)",
        "Intermediário (R$ 80–150/pessoa)", "Premium (R$ 150–300/pessoa)",
        "Luxo (acima de R$ 300/pessoa)",
    ],
    "TargetAudience": [
        "Familiar", "Corporativo", "Universitário / Jovem", "Turístico",
        "Gourmet / Alta gastronomia",
        "Coletividade (hospital, escola, empresa)", "Fitness / Saudável",
    ],
    "BusinessModel": [
        "Independente", "Franquia", "Rede própria", "Concessionária",
        "Chef assinado / Grife", "Pop-up / Temporário",
    ],
    "PhysicalFormat": [
        "Restaurante fixo (salão)", "Food Truck", "Quiosque",
        "Dentro de shopping", "Dentro de hotel", "Dentro de hospital/empresa",
        "Dark Kitchen", "Restaurante de destino",
    ],
}


def seed(apps, schema_editor):
    for model_name, values in SEED.items():
        Model = apps.get_model("restaurants", model_name)
        Model.objects.bulk_create(
            [Model(name=v) for v in values], ignore_conflicts=True
        )


def unseed(apps, schema_editor):
    for model_name, values in SEED.items():
        Model = apps.get_model("restaurants", model_name)
        Model.objects.filter(name__in=values).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("restaurants", "0003_ambient_businessmodel_cuisine_physicalformat_and_more"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
