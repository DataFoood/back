"""Carga de demonstração: restaurantes de Marília/SP (conteúdo do protótipo
do front). Idempotente — roda de novo sem duplicar (chave = slug).

    python manage.py seed_demo                 # só restaurantes
    python manage.py seed_demo --demo-users    # + contas demo (NÃO use em prod)
"""

from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction

from address.models import Address
from restaurants.models import (
    Ambient,
    BusinessHour,
    Cuisine,
    PriceRange,
    Restaurant,
    RestaurantItem,
    TargetAudience,
)
from users.models import User

DEMO_PASSWORD = "Demo@12345"
PRICE = {
    "$": "Econômico (até R$ 30/pessoa)",
    "$$": "Moderado (R$ 30–80/pessoa)",
    "$$$": "Intermediário (R$ 80–150/pessoa)",
}
CLOSED = None

# horários por dia (seg..dom): lista de (inicio, fim) ou CLOSED.
# Fechamentos após meia-noite são truncados em 23:59:59 (modelo não cruza o dia).
LUNCH = [("11:00", "15:00")]


def _week(*days):
    return list(days)


RESTAURANTS = [
    {
        "slug": "canto-da-serra", "name": "Canto da Serra",
        "description": "Churrasco e frango caipira em ambiente familiar, amplo e sem pressa. "
        "Referência em Marília para quem busca comida caseira bem feita: o frango caipira assado "
        "na brasa é o carro-chefe, servido com arroz, feijão tropeiro e couve. Almoço executivo "
        "durante a semana com prato feito por preço fixo.",
        "cuisines": ["Brasileira", "Churrasco/Grelhados"], "ambients": ["Familiar", "Casual Dining"],
        "audiences": ["Familiar", "Corporativo"], "price": "$$",
        "phone": "1434221870", "street": "R. Quinze de Novembro", "number": "340", "neighborhood": "Centro",
        "flags": {"has_dine_in": True, "has_take_out": True, "accepts_vale_refeicao": True},
        "items": [
            ("Frango caipira na brasa", "Meio frango caipira assado lentamente na brasa, com arroz, feijão tropeiro e couve.", "52"),
            ("Costelinha de porco", "Costelinha temperada na véspera, assada por 3h, com mandioca frita e vinagrete.", "68"),
            ("Pudim de leite condensado", "Pudim caseiro, calda de caramelo escuro, porção generosa.", "18"),
        ],
        "hours": _week(LUNCH, LUNCH, LUNCH, LUNCH, [("11:00", "15:00"), ("19:00", "23:00")], [("11:00", "16:00")], LUNCH),
    },
    {
        "slug": "mr-beer-marilia", "name": "Mr. Beer Marília",
        "description": "Happy hour com chopps gelados e petiscos fartos no centro. Ponto de encontro "
        "para uma roda de amigos ou confraternizações; aos fins de semana tem música ao vivo e o "
        "salão enche cedo.",
        "cuisines": ["Brasileira"], "ambients": ["Bar/Pub"], "audiences": ["Universitário / Jovem"],
        "price": "$$", "phone": "1434334020", "street": "Av. Sampaio Vidal", "number": "752", "neighborhood": "Centro",
        "flags": {"has_dine_in": True},
        "items": [
            ("Frango à passarinho", "Frango crocante frito, temperado com alho e limão, porção para 2.", "48"),
            ("Calabresa acebolada", "Calabresa na chapa com cebola caramelada e pimenta dedo-de-moça.", "42"),
            ("Chopp pilsen 500ml", "Chopp gelado tirado na hora, colarinho perfeito.", "14"),
        ],
        "hours": _week(CLOSED, [("17:00", "23:59:59")], [("17:00", "23:59:59")], [("17:00", "23:59:59")],
                       [("17:00", "23:59:59")], [("12:00", "23:59:59")], [("12:00", "22:00")]),
    },
    {
        "slug": "dallas-restaurante", "name": "Dallas Restaurante",
        "description": "Jantar em ambiente sofisticado, a melhor opção para ocasiões especiais em Marília. "
        "Iluminação baixa, mesas bem espaçadas e serviço atento. Cortes nobres, massas artesanais e "
        "a carta de vinhos mais completa da cidade.",
        "cuisines": ["Mediterrânea", "Pizza & Massas"], "ambients": ["Romântico", "Casual Dining"],
        "audiences": ["Gourmet / Alta gastronomia", "Corporativo"], "price": "$$$",
        "phone": "1434225588", "street": "R. Bahia", "number": "144", "neighborhood": "Centro",
        "flags": {"has_dine_in": True, "has_reservation": True},
        "items": [
            ("Filé ao molho de vinho", "Filé mignon grelhado, molho de vinho tinto reduzido, risoto de cogumelos.", "98"),
            ("Massa ao funghi secchi", "Tagliatelle artesanal com creme de funghi secchi, parmesão e salsinha.", "72"),
            ("Petit gateau", "Bolinho quente de chocolate meio amargo, sorvete de creme e calda de framboesa.", "32"),
        ],
        "hours": _week(CLOSED, CLOSED, [("19:00", "23:00")], [("19:00", "23:00")], [("19:00", "23:59:59")],
                       [("12:00", "15:30"), ("19:00", "23:59:59")], [("12:00", "15:30")]),
    },
    {
        "slug": "ki-sushi-marilia", "name": "Ki Sushi",
        "description": "Rodízio de sushi e temaki bem avaliado, popular entre universitários. Grande "
        "variedade de peças, temakis e pratos quentes por preço acessível. Ambiente animado e serviço "
        "ágil; reserva aconselhada nos fins de semana.",
        "cuisines": ["Japonesa"], "ambients": ["Casual Dining"], "audiences": ["Universitário / Jovem"],
        "price": "$$", "phone": "1434152200", "street": "Av. das Esmeraldas", "number": "512",
        "neighborhood": "Vila Universitária",
        "flags": {"has_dine_in": True, "has_delivery": True, "has_reservation": True},
        "items": [
            ("Temaki de salmão", "Cone de alga com arroz temperado, salmão, cream cheese e cebolinha.", None),
            ("Hot roll de camarão", "Uramaki empanado com camarão e cream cheese, molho tarê.", None),
            ("Guioza na chapa", "Pastel japonês de carne e repolho, tostado na chapa, molho ponzu.", None),
        ],
        "hours": _week(CLOSED, [("18:30", "23:00")], [("18:30", "23:00")], [("18:30", "23:00")],
                       [("18:30", "23:59:59")], [("12:00", "15:30"), ("18:30", "23:59:59")], [("12:00", "15:30")]),
    },
    {
        "slug": "pizza-del-rei", "name": "Pizza Del Rei",
        "description": "Pizzaria tradicional com massa fina e forno a lenha, há mais de 20 anos em Marília. "
        "Ambiente familiar e tranquilo, com entrega para boa parte da cidade. A pizza doce de banana "
        "com canela tem fila de fãs.",
        "cuisines": ["Pizza & Massas", "Italiana"], "ambients": ["Familiar"], "audiences": ["Familiar"],
        "price": "$$", "phone": "1434228844", "street": "R. Joaquim Nabuco", "number": "889",
        "neighborhood": "Jardim Califórnia",
        "flags": {"has_dine_in": True, "has_delivery": True, "has_take_out": True},
        "items": [
            ("Calabresa com alho", "Pizza média, massa fina, calabresa, alho tostado, azeitona e orégano.", "62"),
            ("Quatro queijos", "Mussarela, provolone, gorgonzola e parmesão gratinados.", "68"),
            ("Banana com canela", "Pizza doce com banana, canela, açúcar mascavo e leite condensado.", "58"),
        ],
        "hours": _week(CLOSED, [("18:00", "23:30")], [("18:00", "23:30")], [("18:00", "23:30")],
                       [("18:00", "23:59:59")], [("18:00", "23:59:59")], [("18:00", "23:00")]),
    },
    {
        "slug": "cafe-oficina", "name": "Café Oficina",
        "description": "Café especial e brunch em ambiente descolado, decorado com peças de oficina "
        "mecânica. Wi-fi estável, tomadas em todas as mesas — o lugar favorito para trabalhar fora "
        "de casa. O flat white e o croissant são os mais pedidos.",
        "cuisines": ["Brasileira"], "ambients": ["Cafeteria", "Bistrô"], "audiences": ["Corporativo", "Universitário / Jovem"],
        "price": "$$", "phone": "14998123344", "street": "R. Said Nacib Cury", "number": "210", "neighborhood": "Centro",
        "flags": {"has_dine_in": True, "has_take_out": True},
        "items": [
            ("Flat white", "Espresso duplo com leite vaporizado em microespuma, grão do cerrado.", "16"),
            ("Brunch completo", "Ovos mexidos, croissant, frios, geleia artesanal, suco e café.", "42"),
            ("Bolo de fubá com goiabada", "Bolo de fubá úmido com goiabada artesanal.", "14"),
        ],
        "hours": _week([("08:00", "18:00")], [("08:00", "18:00")], [("08:00", "18:00")], [("08:00", "18:00")],
                       [("08:00", "20:00")], [("09:00", "16:00")], CLOSED),
    },
    {
        "slug": "espeto-do-alemao", "name": "Espeto do Alemão",
        "description": "Espetinhos na brasa em ambiente aberto e informal, ponto de encontro do "
        "Jardim Europa aos fins de semana. Carne, frango, coração e queijo coalho feitos na hora, "
        "com pão de alho e vinagrete. Sem reserva: chegue cedo.",
        "cuisines": ["Churrasco/Grelhados"], "ambients": ["Ao Ar Livre", "Bar/Pub"], "audiences": ["Familiar"],
        "price": "$", "phone": "14996547788", "street": "R. Pioneiro Sebastião Garcia", "number": "455",
        "neighborhood": "Jardim Europa",
        "flags": {"has_dine_in": True, "has_take_out": True},
        "items": [
            ("Espeto de fraldinha", "Fraldinha temperada grelhada na brasa, ponto ao pedido.", "12"),
            ("Espeto de queijo coalho", "Queijo coalho grelhado com orégano e manteiga de garrafa.", "10"),
            ("Pão de alho na brasa", "Pão francês com manteiga de alho e ervas, tostado na brasa.", "8"),
        ],
        "hours": _week(CLOSED, CLOSED, CLOSED, [("18:00", "23:00")], [("18:00", "23:59:59")],
                       [("17:00", "23:59:59")], [("16:00", "22:00")]),
    },
    {
        "slug": "laguna-restaurante", "name": "Laguna Restaurante",
        "description": "Frutos do mar frescos com vista para a represa — o jantar romântico mais especial "
        "de Marília. Janelas que enquadram a água, iluminação baixa e música suave. Destaques: moqueca "
        "de camarão e polvo grelhado.",
        "cuisines": ["Frutos do Mar"], "ambients": ["Romântico", "Ao Ar Livre"],
        "audiences": ["Gourmet / Alta gastronomia"], "price": "$$$",
        "phone": "1434129900", "street": "Estrada Municipal da Represa", "number": "km 3", "neighborhood": "Mirante",
        "flags": {"has_dine_in": True, "has_reservation": True},
        "items": [
            ("Moqueca de camarão", "Camarão no leite de coco e dendê, pimentões e coentro. Arroz e pirão.", "98"),
            ("Polvo grelhado", "Polvo cozido e grelhado, azeite, alho, batatas ao murro e rúcula.", "115"),
            ("Mousse de maracujá", "Mousse cremosa com calda de maracujá fresco.", "28"),
        ],
        "hours": _week(CLOSED, CLOSED, [("19:00", "23:00")], [("19:00", "23:00")], [("19:00", "23:59:59")],
                       [("12:00", "16:00"), ("19:00", "23:59:59")], [("12:00", "16:00")]),
    },
    {
        "slug": "chopperia-marilia", "name": "Chopperia Marília",
        "description": "Chopps artesanais e tábuas fartíssimas: um dos bares mais movimentados da cidade, "
        "sempre com 4 torneiras diferentes. Ambiente animado, com música ao vivo às sextas e sábados.",
        "cuisines": ["Brasileira"], "ambients": ["Bar/Pub"], "audiences": ["Universitário / Jovem"],
        "price": "$$", "phone": "1434337755", "street": "Av. Princesa d'Oeste", "number": "1240",
        "neighborhood": "Vila São Francisco",
        "flags": {"has_dine_in": True},
        "items": [
            ("Tábua de frios premium", "Presunto cru, salame, gouda, gorgonzola, pão artesanal e geleia de pimenta.", "72"),
            ("Frango empanado da casa", "Tiras de frango na farinha panko, molho secreto da casa.", "52"),
            ("Chopp artesanal weiss", "Chopp de trigo, notas frutadas, 400ml bem gelado.", "18"),
        ],
        "hours": _week(CLOSED, [("17:00", "23:59:59")], [("17:00", "23:59:59")], [("17:00", "23:59:59")],
                       [("17:00", "23:59:59")], [("14:00", "23:59:59")], [("14:00", "22:00")]),
    },
]


def _t(value):
    return value if value.count(":") == 2 else f"{value}:00"


class Command(BaseCommand):
    help = "Carrega restaurantes de demonstração (Marília/SP). Idempotente."

    def add_arguments(self, parser):
        parser.add_argument(
            "--demo-users", action="store_true",
            help=f"Cria contas demo (cliente@/dono@datafood.demo, senha {DEMO_PASSWORD}). Não use em produção.",
        )

    @transaction.atomic
    def handle(self, *args, demo_users=False, **options):
        owner = None
        if demo_users:
            owner = self._user("dono@datafood.demo", "Dono Demo", User.Role.OWNER)
            self._user("cliente@datafood.demo", "Cliente Demo", User.Role.CUSTOMER)

        ct = ContentType.objects.get_for_model(Restaurant)
        created = 0
        for data in RESTAURANTS:
            restaurant, was_created = Restaurant.objects.get_or_create(
                slug=data["slug"],
                defaults={
                    "name": data["name"], "description": data["description"],
                    "phone": data["phone"], **data["flags"],
                },
            )
            if not was_created:
                continue
            created += 1
            # dono demo fica com o Dallas (painel do restaurante)
            if owner and data["slug"] == "dallas-restaurante":
                restaurant.owner = owner
                restaurant.save(update_fields=["owner"])
            restaurant.cuisines.set(Cuisine.objects.filter(name__in=data["cuisines"]))
            restaurant.ambients.set(Ambient.objects.filter(name__in=data["ambients"]))
            restaurant.target_audiences.set(TargetAudience.objects.filter(name__in=data["audiences"]))
            restaurant.price_ranges.set(PriceRange.objects.filter(name=PRICE[data["price"]]))
            for position, (name, description, price) in enumerate(data["items"]):
                RestaurantItem.objects.create(
                    restaurant=restaurant, name=name, description=description,
                    price=Decimal(price) if price else None, position=position,
                )
            for day, intervals in enumerate(data["hours"]):
                BusinessHour.objects.create(
                    restaurant=restaurant, day_week=day, is_closed=intervals is None,
                    meta_interval={
                        f"turno{i + 1}": [_t(start), _t(end)]
                        for i, (start, end) in enumerate(intervals or [])
                    },
                )
            Address.objects.create(
                content_type=ct, object_id=restaurant.pk, street=data["street"],
                number=data["number"], neighborhood=data["neighborhood"], city="Marília",
                state="SP", zipcode="17500-000", is_default=True,
            )

        self.stdout.write(self.style.SUCCESS(
            f"{created} restaurante(s) criado(s); {len(RESTAURANTS) - created} já existia(m). "
            "Gere os embeddings com: python manage.py reindex_restaurants"
        ))

    def _user(self, email, name, role):
        user, created = User.objects.get_or_create(email=email, defaults={"name": name, "role": role})
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save(update_fields=["password"])
            self.stdout.write(f"conta demo: {email} / {DEMO_PASSWORD}")
        return user
