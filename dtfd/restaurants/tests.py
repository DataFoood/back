from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from users.models import User

from .models import (
    BusinessHour,
    Cuisine,
    PriceRange,
    Restaurant,
    RestaurantImage,
    RestaurantReview,
)


def make_user(email="owner@dtfd.com", name="Owner"):
    return User.objects.create_user(email=email, password="SenhaForte123", name=name)


def make_admin(email="admin@dtfd.com"):
    return User.objects.create_superuser(email=email, password="SenhaForte123", name="Admin")


def make_restaurant(owner, name="Cantina", slug=None, **extra):
    return Restaurant.objects.create(owner=owner, name=name, slug=slug or name.lower(), **extra)


# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------
class RestaurantCreateTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.URL = "/api/restaurants/"
        cls.owner = make_user()
        cls.valid = {
            "name": "Cantina da Nonna",
            "description": "Comida italiana",
            "cnpj": "12345678000190",
            "phone": "1133334444",
            "email": "contato@cantina.com",
        }

    # --- happy ---
    def test_create_sets_owner_and_slug(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.URL, data=self.valid, format="json")
        with self.subTest():
            self.assertEqual(status.HTTP_201_CREATED, response.status_code)
        r = Restaurant.objects.get(name="Cantina da Nonna")
        self.assertEqual(self.owner, r.owner, "owner deve vir do request, nao do payload")
        self.assertEqual("cantina-da-nonna", r.slug, "slug deve ser gerado do nome")

    def test_create_generates_unique_slug(self):
        self.client.force_authenticate(self.owner)
        self.client.post(self.URL, data={"name": "Bar do Ze"}, format="json")
        self.client.post(self.URL, data={"name": "Bar do Ze"}, format="json")
        slugs = list(Restaurant.objects.filter(name="Bar do Ze").values_list("slug", flat=True))
        self.assertEqual(len(slugs), len(set(slugs)), "slugs devem ser unicos")

    def test_create_ignores_owner_in_payload(self):
        other = make_user(email="other@dtfd.com")
        self.client.force_authenticate(self.owner)
        self.client.post(self.URL, data={**self.valid, "owner": other.id}, format="json")
        r = Restaurant.objects.get(name="Cantina da Nonna")
        self.assertEqual(self.owner, r.owner, "owner do payload deve ser ignorado")

    # --- unhappy ---
    def test_create_unauthenticated(self):
        response = self.client.post(self.URL, data=self.valid, format="json")
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)

    def test_create_without_name(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.URL, data={"description": "x"}, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("name", response.json())

    def test_create_duplicate_cnpj(self):
        self.client.force_authenticate(self.owner)
        self.client.post(self.URL, data=self.valid, format="json")
        response = self.client.post(self.URL, data={**self.valid, "name": "Outro"}, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("cnpj", response.json())


# ---------------------------------------------------------------------------
# LIST / DETAIL (publico)
# ---------------------------------------------------------------------------
class RestaurantReadTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user()
        cls.restaurant = make_restaurant(cls.owner)

    def test_list_public(self):
        response = self.client.get("/api/restaurants/")
        self.assertEqual(status.HTTP_200_OK, response.status_code)

    def test_detail_public(self):
        response = self.client.get(f"/api/restaurants/{self.restaurant.pk}/")
        with self.subTest():
            self.assertEqual(status.HTTP_200_OK, response.status_code)
        expected = {
            "id", "owner", "name", "slug", "description", "cnpj", "phone",
            "email", "website", "average_rating", "total_reviews",
            "cover_image", "menu_url", "created_at", "updated_at",
            "images", "reviews", "business_hours", "items",
            "cuisines", "ambients", "service_models", "target_audiences",
            "price_ranges", "business_models", "physical_formats",
            "has_dine_in", "has_delivery", "has_take_out", "has_drive_thru",
            "has_reservation", "accepts_vale_refeicao", "accepts_online_order",
        }
        self.assertSetEqual(expected, set(response.json().keys()))

    def test_soft_deleted_not_listed(self):
        from django.utils import timezone
        r = make_restaurant(self.owner, name="Fechado", slug="fechado")
        r.deleted_at = timezone.now()
        r.save(update_fields=["deleted_at"])
        response = self.client.get(f"/api/restaurants/{r.pk}/")
        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)


# ---------------------------------------------------------------------------
# UPDATE / DELETE (owner ou admin)
# ---------------------------------------------------------------------------
class RestaurantModifyTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user()
        cls.other = make_user(email="other@dtfd.com")
        cls.admin = make_admin()
        cls.restaurant = make_restaurant(cls.owner)
        cls.URL = f"/api/restaurants/{cls.restaurant.pk}/"

    # --- happy ---
    def test_update_by_owner(self):
        self.client.force_authenticate(self.owner)
        response = self.client.patch(self.URL, data={"description": "Atualizado"}, format="json")
        with self.subTest():
            self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.restaurant.refresh_from_db()
        self.assertEqual("Atualizado", self.restaurant.description)

    def test_update_by_admin(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch(self.URL, data={"description": "Admin"}, format="json")
        self.assertEqual(status.HTTP_200_OK, response.status_code)

    def test_soft_delete_by_owner(self):
        self.client.force_authenticate(self.owner)
        response = self.client.delete(self.URL)
        with self.subTest():
            self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        self.assertFalse(Restaurant.objects.filter(pk=self.restaurant.pk).exists())
        self.assertIsNotNone(Restaurant.all_objects.get(pk=self.restaurant.pk).deleted_at)

    # --- unhappy ---
    def test_update_by_non_owner_forbidden(self):
        self.client.force_authenticate(self.other)
        response = self.client.patch(self.URL, data={"description": "hack"}, format="json")
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)

    def test_update_unauthenticated(self):
        response = self.client.patch(self.URL, data={"description": "x"}, format="json")
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)

    def test_delete_by_non_owner_forbidden(self):
        self.client.force_authenticate(self.other)
        response = self.client.delete(self.URL)
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)


# ---------------------------------------------------------------------------
# REVIEWS (nested) + recalculo de rating
# ---------------------------------------------------------------------------
class ReviewTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user()
        cls.critic = make_user(email="critic@dtfd.com")
        cls.other = make_user(email="other@dtfd.com")
        cls.restaurant = make_restaurant(cls.owner)
        cls.URL = f"/api/restaurants/{cls.restaurant.pk}/reviews/"

    # --- happy ---
    def test_create_review_sets_author_and_recalcs(self):
        self.client.force_authenticate(self.critic)
        response = self.client.post(self.URL, data={"rating": 4, "title": "Bom"}, format="json")
        with self.subTest():
            self.assertEqual(status.HTTP_201_CREATED, response.status_code)
        review = RestaurantReview.objects.get(restaurant=self.restaurant)
        self.assertEqual(self.critic, review.author, "author vem do request")
        self.restaurant.refresh_from_db()
        self.assertEqual(Decimal("4.00"), self.restaurant.average_rating)
        self.assertEqual(1, self.restaurant.total_reviews)

    def test_rating_average_of_multiple_reviews(self):
        self.client.force_authenticate(self.critic)
        self.client.post(self.URL, data={"rating": 4}, format="json")
        self.client.force_authenticate(self.other)
        self.client.post(self.URL, data={"rating": 2}, format="json")
        self.restaurant.refresh_from_db()
        self.assertEqual(Decimal("3.00"), self.restaurant.average_rating)
        self.assertEqual(2, self.restaurant.total_reviews)

    def test_list_reviews_public(self):
        RestaurantReview.objects.create(restaurant=self.restaurant, author=self.critic, rating=5)
        response = self.client.get(self.URL)
        self.assertEqual(status.HTTP_200_OK, response.status_code)

    def test_delete_review_recalcs(self):
        r1 = RestaurantReview.objects.create(restaurant=self.restaurant, author=self.critic, rating=4)
        RestaurantReview.objects.create(restaurant=self.restaurant, author=self.other, rating=2)
        self.restaurant.recalc_rating()
        self.client.force_authenticate(self.critic)
        response = self.client.delete(f"{self.URL}{r1.pk}/")
        with self.subTest():
            self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        self.restaurant.refresh_from_db()
        self.assertEqual(Decimal("2.00"), self.restaurant.average_rating)
        self.assertEqual(1, self.restaurant.total_reviews)

    # --- unhappy ---
    def test_create_review_unauthenticated(self):
        response = self.client.post(self.URL, data={"rating": 4}, format="json")
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)

    def test_create_review_rating_out_of_range(self):
        self.client.force_authenticate(self.critic)
        for bad in (0, 6):
            response = self.client.post(self.URL, data={"rating": bad}, format="json")
            self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code,
                             f"rating {bad} deveria ser invalido")

    def test_update_another_users_review_forbidden(self):
        review = RestaurantReview.objects.create(restaurant=self.restaurant, author=self.critic, rating=4)
        self.client.force_authenticate(self.other)
        response = self.client.patch(f"{self.URL}{review.pk}/", data={"rating": 1}, format="json")
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)

    def test_delete_another_users_review_forbidden(self):
        review = RestaurantReview.objects.create(restaurant=self.restaurant, author=self.critic, rating=4)
        self.client.force_authenticate(self.other)
        response = self.client.delete(f"{self.URL}{review.pk}/")
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)


# ---------------------------------------------------------------------------
# IMAGES (nested) — gestao do owner
# ---------------------------------------------------------------------------
class ImageTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user()
        cls.other = make_user(email="other@dtfd.com")
        cls.admin = make_admin()
        cls.restaurant = make_restaurant(cls.owner)
        cls.URL = f"/api/restaurants/{cls.restaurant.pk}/images/"

    # --- happy ---
    def test_owner_creates_image(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.URL, data={"url": "https://img.com/1.jpg"}, format="json")
        with self.subTest():
            self.assertEqual(status.HTTP_201_CREATED, response.status_code)
        self.assertEqual(1, RestaurantImage.objects.filter(restaurant=self.restaurant).count())

    def test_list_images_public(self):
        RestaurantImage.objects.create(restaurant=self.restaurant, url="https://img.com/1.jpg")
        response = self.client.get(self.URL)
        self.assertEqual(status.HTTP_200_OK, response.status_code)

    def test_owner_soft_deletes_image(self):
        img = RestaurantImage.objects.create(restaurant=self.restaurant, url="https://img.com/1.jpg")
        self.client.force_authenticate(self.owner)
        response = self.client.delete(f"{self.URL}{img.pk}/")
        with self.subTest():
            self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        self.assertFalse(RestaurantImage.objects.filter(pk=img.pk).exists())
        self.assertIsNotNone(RestaurantImage.all_objects.get(pk=img.pk).deleted_at)

    # --- unhappy ---
    def test_non_owner_create_forbidden(self):
        self.client.force_authenticate(self.other)
        response = self.client.post(self.URL, data={"url": "https://img.com/x.jpg"}, format="json")
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)

    def test_unauthenticated_create(self):
        response = self.client.post(self.URL, data={"url": "https://img.com/x.jpg"}, format="json")
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)

    def test_non_owner_delete_forbidden(self):
        img = RestaurantImage.objects.create(restaurant=self.restaurant, url="https://img.com/1.jpg")
        self.client.force_authenticate(self.other)
        response = self.client.delete(f"{self.URL}{img.pk}/")
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)


# ---------------------------------------------------------------------------
# BUSINESS HOURS (nested) — gestao do owner + validacao meta_interval
# ---------------------------------------------------------------------------
class BusinessHourTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user()
        cls.other = make_user(email="other@dtfd.com")
        cls.restaurant = make_restaurant(cls.owner)
        cls.URL = f"/api/restaurants/{cls.restaurant.pk}/hours/"
        cls.valid = {
            "day_week": 0,
            "meta_interval": {"lunch": ["11:00:00", "15:00:00"]},
            "is_closed": False,
        }

    # --- happy ---
    def test_owner_creates_hour(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.URL, data=self.valid, format="json")
        with self.subTest():
            self.assertEqual(status.HTTP_201_CREATED, response.status_code)
        self.assertEqual(1, BusinessHour.objects.filter(restaurant=self.restaurant).count())

    def test_list_hours_public(self):
        BusinessHour.objects.create(restaurant=self.restaurant, day_week=1)
        response = self.client.get(self.URL)
        self.assertEqual(status.HTTP_200_OK, response.status_code)

    # --- unhappy ---
    def test_non_owner_create_forbidden(self):
        self.client.force_authenticate(self.other)
        response = self.client.post(self.URL, data=self.valid, format="json")
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)

    def test_duplicate_day_rejected(self):
        self.client.force_authenticate(self.owner)
        self.client.post(self.URL, data=self.valid, format="json")
        response = self.client.post(self.URL, data=self.valid, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("day_week", response.json())

    def test_meta_interval_end_before_start(self):
        self.client.force_authenticate(self.owner)
        data = {**self.valid, "meta_interval": {"lunch": ["15:00:00", "11:00:00"]}}
        response = self.client.post(self.URL, data=data, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("meta_interval", response.json())

    def test_meta_interval_invalid_time_format(self):
        self.client.force_authenticate(self.owner)
        data = {**self.valid, "meta_interval": {"lunch": ["11h", "15h"]}}
        response = self.client.post(self.URL, data=data, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("meta_interval", response.json())


# ---------------------------------------------------------------------------
# TAXONOMIAS (M2M) + SALES CHANNEL (flags)
# ---------------------------------------------------------------------------
class RestaurantTaxonomyTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.URL = "/api/restaurants/"
        cls.owner = make_user()

    def test_seed_data_exists(self):
        # data migration semeia as taxonomias
        self.assertEqual(19, Cuisine.objects.count())
        self.assertEqual(5, PriceRange.objects.count())

    def test_create_with_taxonomies_and_flags(self):
        self.client.force_authenticate(self.owner)
        italiana = Cuisine.objects.get(name="Italiana")
        pizza = Cuisine.objects.get(name="Pizza & Massas")
        faixa = PriceRange.objects.get(name__startswith="Moderado")
        payload = {
            "name": "Trattoria",
            "cuisines": [italiana.pk, pizza.pk],
            "price_ranges": [faixa.pk],
            "has_delivery": True,
            "has_reservation": True,
        }
        response = self.client.post(self.URL, data=payload, format="json")
        with self.subTest():
            self.assertEqual(status.HTTP_201_CREATED, response.status_code)
        r = Restaurant.objects.get(name="Trattoria")
        self.assertEqual({italiana.pk, pizza.pk}, set(r.cuisines.values_list("pk", flat=True)))
        self.assertTrue(r.has_delivery)
        self.assertTrue(r.has_reservation)
        self.assertFalse(r.has_drive_thru, "flag nao enviada deve ficar False")

    def test_read_exposes_taxonomies_as_id_name(self):
        r = make_restaurant(self.owner)
        r.cuisines.add(Cuisine.objects.get(name="Japonesa"))
        response = self.client.get(f"{self.URL}{r.pk}/")
        with self.subTest():
            self.assertEqual(status.HTTP_200_OK, response.status_code)
        data = response.json()
        self.assertEqual([{"id": Cuisine.objects.get(name="Japonesa").pk, "name": "Japonesa"}],
                         data["cuisines"])
        self.assertIn("has_delivery", data)

    def test_update_replaces_taxonomies(self):
        r = make_restaurant(self.owner)
        r.cuisines.add(Cuisine.objects.get(name="Chinesa"))
        self.client.force_authenticate(self.owner)
        nova = Cuisine.objects.get(name="Mexicana")
        response = self.client.patch(f"{self.URL}{r.pk}/", data={"cuisines": [nova.pk]}, format="json")
        with self.subTest():
            self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertEqual({nova.pk}, set(r.cuisines.values_list("pk", flat=True)))

    def test_invalid_cuisine_id_rejected(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.URL, data={"name": "X", "cuisines": [99999]}, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("cuisines", response.json())


# ---------------------------------------------------------------------------
# FASE 1: ITEMS, FAVORITES, VIEW-TRACKING
# ---------------------------------------------------------------------------
class RestaurantItemTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user()
        cls.other = make_user(email="other@dtfd.com")
        cls.restaurant = make_restaurant(cls.owner)
        cls.URL = f"/api/restaurants/{cls.restaurant.pk}/items/"

    def test_owner_creates_item(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.URL, data={"name": "Feijoada", "price": "49.90"}, format="json")
        self.assertEqual(status.HTTP_201_CREATED, response.status_code)

    def test_list_items_public(self):
        from .models import RestaurantItem
        RestaurantItem.objects.create(restaurant=self.restaurant, name="Feijoada")
        response = self.client.get(self.URL)
        self.assertEqual(status.HTTP_200_OK, response.status_code)

    def test_non_owner_create_forbidden(self):
        self.client.force_authenticate(self.other)
        response = self.client.post(self.URL, data={"name": "X"}, format="json")
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)

    def test_max_six_items_enforced(self):
        from .models import RestaurantItem
        for i in range(6):
            RestaurantItem.objects.create(restaurant=self.restaurant, name=f"Prato {i}")
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.URL, data={"name": "Setimo"}, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)


class FavoriteTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()
        cls.restaurant = make_restaurant(cls.user)
        cls.URL = f"/api/restaurants/{cls.restaurant.pk}/favorite/"

    def test_favorite_then_unfavorite(self):
        from .models import RestaurantFavorite
        self.client.force_authenticate(self.user)
        r1 = self.client.post(self.URL)
        with self.subTest():
            self.assertEqual(status.HTTP_201_CREATED, r1.status_code)
        self.assertTrue(RestaurantFavorite.objects.filter(user=self.user, restaurant=self.restaurant).exists())
        # idempotente
        r2 = self.client.post(self.URL)
        self.assertEqual(status.HTTP_200_OK, r2.status_code)
        self.assertEqual(1, RestaurantFavorite.objects.filter(user=self.user).count())
        # desfavorita
        r3 = self.client.delete(self.URL)
        self.assertEqual(status.HTTP_204_NO_CONTENT, r3.status_code)
        self.assertFalse(RestaurantFavorite.objects.filter(user=self.user).exists())

    def test_unfavorite_not_favorited(self):
        self.client.force_authenticate(self.user)
        response = self.client.delete(self.URL)
        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

    def test_favorite_unauthenticated(self):
        response = self.client.post(self.URL)
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)

    def test_list_favorites_only_own(self):
        from .models import RestaurantFavorite
        other = make_user(email="other@dtfd.com")
        RestaurantFavorite.objects.create(user=self.user, restaurant=self.restaurant)
        RestaurantFavorite.objects.create(user=other, restaurant=make_restaurant(other, name="X"))
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/restaurants/favorites/")
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertEqual(1, len(response.json()))


class ViewTrackingTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()
        cls.restaurant = make_restaurant(cls.user)
        cls.URL = f"/api/restaurants/{cls.restaurant.pk}/"

    def test_view_increments_count(self):
        from .models import RestaurantView
        self.client.force_authenticate(self.user)
        self.client.get(self.URL)
        self.client.get(self.URL)
        self.client.get(self.URL)
        view = RestaurantView.objects.get(user=self.user, restaurant=self.restaurant)
        self.assertEqual(3, view.count)

    def test_anonymous_view_not_tracked(self):
        from .models import RestaurantView
        self.client.get(self.URL)
        self.assertFalse(RestaurantView.objects.filter(restaurant=self.restaurant).exists())


# ---------------------------------------------------------------------------
# SEARCH — ponte pro shinzou
# ---------------------------------------------------------------------------
from unittest.mock import MagicMock, patch

import httpx


class SearchBridgeTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()
        cls.URL = "/api/search/"

    def test_unauthenticated(self):
        response = self.client.post(self.URL, data={"query": "feijoada"}, format="json")
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)

    def test_missing_query(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(self.URL, data={}, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("query", response.json())

    @patch("restaurants.views.httpx.post")
    def test_proxies_to_shinzou(self, mock_post):
        fake = MagicMock()
        fake.json.return_value = {"results": [{"restaurant": {"id": 1}, "score": 1.2}]}
        fake.status_code = 200
        mock_post.return_value = fake

        self.client.force_authenticate(self.user)
        response = self.client.post(self.URL, data={"query": "feijoada"}, format="json")

        with self.subTest():
            self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertEqual({"results": [{"restaurant": {"id": 1}, "score": 1.2}]}, response.json())
        # passou o service token pro shinzou
        _, kwargs = mock_post.call_args
        self.assertIn("X-Service-Token", kwargs["headers"])
        self.assertEqual("feijoada", kwargs["json"]["query"])

    @patch("restaurants.views.httpx.post", side_effect=httpx.RequestError("down"))
    def test_shinzou_unavailable(self, _mock):
        self.client.force_authenticate(self.user)
        response = self.client.post(self.URL, data={"query": "feijoada"}, format="json")
        self.assertEqual(status.HTTP_503_SERVICE_UNAVAILABLE, response.status_code)

    @staticmethod
    def _ok_mock():
        fake = MagicMock()
        fake.json.return_value = {"results": []}
        fake.status_code = 200
        return fake

    @patch("restaurants.views.httpx.post")
    def test_logged_when_consented(self, mock_post):
        from preferences.models import SearchHistory
        mock_post.return_value = self._ok_mock()
        self.user.allow_info = True
        self.user.save(update_fields=["allow_info"])
        self.client.force_authenticate(self.user)
        self.client.post(self.URL, data={"query": "feijoada mineira"}, format="json")
        self.assertTrue(
            SearchHistory.objects.filter(user=self.user, query="feijoada mineira").exists()
        )

    @patch("restaurants.views.httpx.post")
    def test_not_logged_without_consent(self, mock_post):
        from preferences.models import SearchHistory
        mock_post.return_value = self._ok_mock()
        # allow_info=False (default) -> LGPD: não guarda
        self.client.force_authenticate(self.user)
        self.client.post(self.URL, data={"query": "sem consentimento"}, format="json")
        self.assertFalse(SearchHistory.objects.filter(query="sem consentimento").exists())

    @patch("restaurants.views.httpx.post", side_effect=httpx.RequestError("down"))
    def test_failed_search_not_logged(self, _mock):
        from preferences.models import SearchHistory
        self.user.allow_info = True
        self.user.save(update_fields=["allow_info"])
        self.client.force_authenticate(self.user)
        self.client.post(self.URL, data={"query": "nao loga"}, format="json")
        self.assertFalse(SearchHistory.objects.filter(query="nao loga").exists())
