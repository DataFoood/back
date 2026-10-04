from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from restaurants.models import Restaurant
from users.models import User

from .models import GeoCell, PlatformDailyStat, RegionVisit, RestaurantDailyStat
from .services import bump_restaurants, record_region_visit
from .tasks import label_cell


def make_user(email, **extra):
    return User.objects.create_user(email=email, password="SenhaForte123", name="Pessoa", **extra)


class CounterTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("dono@dtfd.com")
        cls.r1 = Restaurant.objects.create(owner=cls.owner, name="Um", slug="um")
        cls.r2 = Restaurant.objects.create(owner=cls.owner, name="Dois", slug="dois")

    def test_bump_creates_then_increments(self):
        bump_restaurants([self.r1.pk, self.r2.pk], "search_impressions")
        bump_restaurants([self.r1.pk], "search_impressions")
        self.assertEqual({self.r1.pk: 2, self.r2.pk: 1}, dict(
            RestaurantDailyStat.objects.values_list("restaurant_id", "search_impressions")))

    def test_region_cell_is_coarse_and_labeled_once(self):
        with patch("analytics.services.label_cell.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                record_region_visit(self.r1.pk, -22.21391, -49.94582)
                record_region_visit(self.r1.pk, -22.21409, -49.94611)  # mesma célula de ~1 km
        cell = GeoCell.objects.get()
        self.assertEqual(("-22.21", "-49.95"), (str(cell.lat), str(cell.lon)), "coordenada exata não é guardada")
        self.assertEqual(2, RegionVisit.objects.get().count)
        delay.assert_called_once_with(cell.pk)

    @patch("analytics.tasks.region_label", return_value="Centro, Marília")
    def test_label_cell(self, _mock):
        cell = GeoCell.objects.create(lat="-22.21", lon="-49.95")
        self.assertTrue(label_cell(cell.pk))
        cell.refresh_from_db()
        self.assertEqual("Centro, Marília", cell.label)


class DetailTrackingTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("dono@dtfd.com")
        cls.visitor = make_user("visita@dtfd.com")
        cls.restaurant = Restaurant.objects.create(owner=cls.owner, name="Alvo", slug="alvo")
        cls.URL = f"/api/restaurants/{cls.restaurant.pk}/"

    @patch("analytics.services.label_cell.delay")
    def test_visit_from_search_with_region(self, _delay):
        self.client.force_authenticate(self.visitor)
        self.client.get(self.URL, {"src": "search", "lat": "-22.2139", "lon": "-49.9458"})
        self.client.get(self.URL)
        stat = RestaurantDailyStat.objects.get()
        self.assertEqual((2, 1), (stat.views, stat.search_clicks))
        self.assertEqual(1, RegionVisit.objects.get().count)

    def test_invalid_coordinates_are_ignored(self):
        self.client.get(self.URL, {"lat": "abc", "lon": "1"})
        self.client.get(self.URL, {"lat": "100", "lon": "1"})
        self.assertFalse(RegionVisit.objects.exists())
        self.assertEqual(2, RestaurantDailyStat.objects.get().views)

    def test_owner_visit_not_counted(self):
        self.client.force_authenticate(self.owner)
        self.client.get(self.URL, {"src": "search"})
        self.assertFalse(RestaurantDailyStat.objects.exists())

    def test_owner_stats_include_traffic_and_regions(self):
        cell = GeoCell.objects.create(lat="-22.21", lon="-49.95", label="Centro, Marília")
        today = timezone.localdate()
        RestaurantDailyStat.objects.create(restaurant=self.restaurant, date=today, views=7,
                                           search_impressions=20, search_clicks=5)
        RestaurantDailyStat.objects.create(restaurant=self.restaurant, date=today - timedelta(days=60), views=99)
        RegionVisit.objects.create(restaurant=self.restaurant, cell=cell, date=today, count=4)
        self.client.force_authenticate(self.owner)
        data = self.client.get(f"{self.URL}stats/").json()
        self.assertEqual((7, 20, 5, 0.25), (data["views_window"], data["search_impressions_window"],
                                            data["search_clicks_window"], data["search_ctr"]))
        self.assertEqual(7, data["series"][-1]["views"])
        self.assertEqual([{"label": "Centro, Marília", "lat": -22.21, "lon": -49.95, "visits": 4}], data["regions"])


class PlatformMetricsTest(APITestCase):
    URL = "/api/analytics/platform/"

    def test_admin_only_aggregates(self):
        admin = User.objects.create_superuser(email="adm@dtfd.com", password="SenhaForte123", name="Adm")
        owner = make_user("dono@dtfd.com", role="owner")
        Restaurant.objects.create(owner=owner, name="Sem geo", slug="sem-geo")
        PlatformDailyStat.objects.create(date=timezone.localdate(), searches=3, search_failures=1)

        self.client.force_authenticate(owner)
        self.assertEqual(status.HTTP_403_FORBIDDEN, self.client.get(self.URL).status_code)

        self.client.force_authenticate(admin)
        data = self.client.get(self.URL).json()
        self.assertEqual({"total": 2, "customers": 0, "owners": 1, "admins": 1, "consented": 0, "removed": 0}, data["users"])
        self.assertEqual(1, data["restaurants"]["without_coordinates"])
        self.assertEqual((3, 1), (data["searches_window"], data["search_failures_window"]))
