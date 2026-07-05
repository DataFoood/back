from rest_framework import status
from rest_framework.test import APITestCase

from restaurants.models import (
    Cuisine,
    Restaurant,
    RestaurantFavorite,
    RestaurantView,
)
from users.models import User

from .models import UserCuisineAffinity
from .services import compute_user_preferences


def make_user(email="u@dtfd.com"):
    return User.objects.create_user(email=email, password="SenhaForte123", name="U")


def make_restaurant(name, cuisines):
    r = Restaurant.objects.create(name=name, slug=name.lower())
    r.cuisines.set(cuisines)
    return r


class ComputePreferencesTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()
        cls.italiana = Cuisine.objects.get(name="Italiana")
        cls.japonesa = Cuisine.objects.get(name="Japonesa")
        cls.r_view = make_restaurant("Trattoria", [cls.italiana])
        cls.r_fav = make_restaurant("Sushi", [cls.japonesa])

    def test_favorite_outweighs_view_and_normalizes(self):
        # view x2 (peso 1*2=2) vs favorite (peso 5) -> japonesa domina
        RestaurantView.objects.create(user=self.user, restaurant=self.r_view, count=2)
        RestaurantFavorite.objects.create(user=self.user, restaurant=self.r_fav)
        compute_user_preferences(self.user)

        jap = UserCuisineAffinity.objects.get(user=self.user, cuisine=self.japonesa)
        ita = UserCuisineAffinity.objects.get(user=self.user, cuisine=self.italiana)
        self.assertEqual(1.0, jap.score, "top affinity normaliza pra 1.0")
        self.assertEqual(0.4, ita.score, "2/5 = 0.4")

    def test_no_interactions_no_affinity(self):
        compute_user_preferences(self.user)
        self.assertEqual(0, UserCuisineAffinity.objects.filter(user=self.user).count())

    def test_manual_affinity_not_overwritten(self):
        RestaurantView.objects.create(user=self.user, restaurant=self.r_view, count=1)
        # usuario fixou manualmente
        UserCuisineAffinity.objects.create(
            user=self.user, cuisine=self.italiana, score=0.9, is_manual=True
        )
        compute_user_preferences(self.user)
        ita = UserCuisineAffinity.objects.get(user=self.user, cuisine=self.italiana)
        self.assertEqual(0.9, ita.score, "linha manual nao e sobrescrita pelo recompute")
        self.assertTrue(ita.is_manual)


class PreferencesEndpointTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()
        cls.other = make_user(email="other@dtfd.com")
        cls.italiana = Cuisine.objects.get(name="Italiana")
        cls.affinity = UserCuisineAffinity.objects.create(
            user=cls.user, cuisine=cls.italiana, score=0.5
        )

    def test_get_preferences(self):
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/preferences/")
        with self.subTest():
            self.assertEqual(status.HTTP_200_OK, response.status_code)
        data = response.json()
        self.assertEqual({"cuisines", "ambients", "price_ranges"}, set(data.keys()))
        self.assertEqual("Italiana", data["cuisines"][0]["name"])

    def test_get_unauthenticated(self):
        response = self.client.get("/api/preferences/")
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)

    def test_edit_sets_manual(self):
        self.client.force_authenticate(self.user)
        url = f"/api/preferences/cuisines/{self.affinity.pk}/"
        response = self.client.patch(url, data={"score": 0.95}, format="json")
        with self.subTest():
            self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.affinity.refresh_from_db()
        self.assertEqual(0.95, self.affinity.score)
        self.assertTrue(self.affinity.is_manual, "editar marca is_manual")

    def test_cannot_edit_another_users_affinity(self):
        self.client.force_authenticate(self.other)
        url = f"/api/preferences/cuisines/{self.affinity.pk}/"
        response = self.client.patch(url, data={"score": 0.1}, format="json")
        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)


from unittest.mock import MagicMock, patch

from .models import RankingWeight


class RankingWeightTest(APITestCase):
    def test_weights_seeded(self):
        keys = set(RankingWeight.objects.values_list("key", flat=True))
        self.assertEqual({"semantic", "preference", "review"}, keys)


class RecomputeEndpointTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(email="a@dtfd.com", password="SenhaForte123", name="A")
        cls.common = make_user(email="c@dtfd.com")
        cls.URL = "/api/preferences/recompute/"

    @patch("preferences.views.recompute_all.delay")
    def test_admin_enqueues_recompute(self, mock_delay):
        mock_delay.return_value = MagicMock(id="task-x")
        self.client.force_authenticate(self.admin)
        response = self.client.post(self.URL, data={}, format="json")
        self.assertEqual(status.HTTP_202_ACCEPTED, response.status_code)
        mock_delay.assert_called_once()

    def test_non_admin_forbidden(self):
        self.client.force_authenticate(self.common)
        response = self.client.post(self.URL, data={}, format="json")
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)


from .models import SearchHistory


class SearchHistoryTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()
        cls.other = make_user(email="other2@dtfd.com")

    def test_list_own_searches(self):
        SearchHistory.objects.create(user=self.user, query="feijoada")
        SearchHistory.objects.create(user=self.other, query="sushi")
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/preferences/searches/")
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        data = response.json()
        self.assertEqual(1, len(data))
        self.assertEqual("feijoada", data[0]["query"])

    def test_list_unauthenticated(self):
        response = self.client.get("/api/preferences/searches/")
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)
