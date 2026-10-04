from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from restaurants.models import Restaurant, RestaurantItem
from users.models import User

from .models import FlashPromotion, PromotionItem


def make_user(email):
    return User.objects.create_user(email=email, password="SenhaForte123", name="Pessoa")


class PromotionTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("dono@dtfd.com")
        cls.other = make_user("outro@dtfd.com")
        cls.restaurant = Restaurant.objects.create(owner=cls.owner, name="Cantina", slug="cantina")
        cls.lasanha = RestaurantItem.objects.create(restaurant=cls.restaurant, name="Lasanha", price=Decimal("60.00"))
        cls.pudim = RestaurantItem.objects.create(restaurant=cls.restaurant, name="Pudim", price=Decimal("18.00"))
        cls.sem_preco = RestaurantItem.objects.create(restaurant=cls.restaurant, name="Prato do dia")
        alheio = Restaurant.objects.create(owner=cls.other, name="Outro", slug="outro")
        cls.alheio = RestaurantItem.objects.create(restaurant=alheio, name="Alheio", price=Decimal("10"))
        cls.URL = f"/api/restaurants/{cls.restaurant.pk}/promotions/"

    def body(self, hours=2, **extra):
        return {
            "title": "Fim de noite",
            "ends_at": (timezone.now() + timedelta(hours=hours)).isoformat(),
            "items": [
                {"item": self.lasanha.pk, "discount_type": "percent", "discount_value": "30"},
                {"item": self.pudim.pk, "discount_type": "amount", "discount_value": "5.50"},
            ],
            **extra,
        }

    def test_owner_creates_and_final_prices_are_computed(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.URL, self.body(), format="json")
        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.content)
        finals = {row["name"]: row["final_price"] for row in response.json()["items"]}
        self.assertEqual({"Lasanha": "42.00", "Pudim": "12.50"}, finals)
        self.assertTrue(response.json()["is_active"])

    def test_card_and_detail_expose_active_promotion(self):
        self.client.force_authenticate(self.owner)
        self.client.post(self.URL, self.body(), format="json")
        self.client.force_authenticate(self.other)
        card = next(r for r in self.client.get("/api/restaurants/").json()["results"] if r["id"] == self.restaurant.pk)
        self.assertEqual((2, 31), (card["promotion"]["items_count"], card["promotion"]["max_discount_percent"]),
                         "pudim: 5,50 de 18 = 30,6% → maior que 30%")
        detail = self.client.get(f"/api/restaurants/{self.restaurant.pk}/").json()
        self.assertEqual("42.00", detail["promotion"]["items"][0]["final_price"])
        promo_only = self.client.get("/api/restaurants/", {"promo": "true"}).json()["results"]
        self.assertEqual([self.restaurant.pk], [r["id"] for r in promo_only])

    def test_expired_promotion_disappears(self):
        promo = FlashPromotion.objects.create(restaurant=self.restaurant, ends_at=timezone.now() + timedelta(hours=1))
        PromotionItem.objects.create(promotion=promo, item=self.pudim, discount_type="percent", discount_value=10)
        FlashPromotion.objects.filter(pk=promo.pk).update(
            starts_at=timezone.now() - timedelta(hours=3), ends_at=timezone.now() - timedelta(minutes=1)
        )
        detail = self.client.get(f"/api/restaurants/{self.restaurant.pk}/").json()
        self.assertIsNone(detail["promotion"])

    def test_validation(self):
        self.client.force_authenticate(self.owner)
        cases = {
            "sem itens": self.body(items=[]),
            "item sem preço": self.body(items=[{"item": self.sem_preco.pk, "discount_type": "percent", "discount_value": "10"}]),
            "item de outro restaurante": self.body(items=[{"item": self.alheio.pk, "discount_type": "percent", "discount_value": "10"}]),
            "percentual acima de 90": self.body(items=[{"item": self.pudim.pk, "discount_type": "percent", "discount_value": "95"}]),
            "valor maior que o preço": self.body(items=[{"item": self.pudim.pk, "discount_type": "amount", "discount_value": "18"}]),
            "repetido": self.body(items=[{"item": self.pudim.pk, "discount_type": "percent", "discount_value": "10"}] * 2),
            "mais de 24h": self.body(hours=30),
            "expira no passado": self.body(hours=-1),
        }
        for label, body in cases.items():
            with self.subTest(label):
                self.assertEqual(status.HTTP_400_BAD_REQUEST, self.client.post(self.URL, body, format="json").status_code)

    def test_no_overlap_and_end_now(self):
        self.client.force_authenticate(self.owner)
        first = self.client.post(self.URL, self.body(), format="json").json()
        self.assertEqual(status.HTTP_400_BAD_REQUEST, self.client.post(self.URL, self.body(hours=3), format="json").status_code)
        self.assertEqual(status.HTTP_204_NO_CONTENT, self.client.delete(f"{self.URL}{first['id']}/").status_code)
        self.assertFalse(FlashPromotion.objects.get(pk=first["id"]).is_active, "encerrada, mas no histórico")
        self.assertEqual(status.HTTP_201_CREATED, self.client.post(self.URL, self.body(), format="json").status_code)

    def test_only_owner_writes(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(status.HTTP_403_FORBIDDEN, self.client.post(self.URL, self.body(), format="json").status_code)
        self.client.force_authenticate(None)
        self.assertEqual(status.HTTP_200_OK, self.client.get(self.URL).status_code, "leitura pública")
