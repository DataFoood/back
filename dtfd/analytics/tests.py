from datetime import date, timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from restaurants.models import Restaurant
from users.models import User

from .insights import restaurant_insights
from .models import AccessStat, GeoCell, PlatformDailyStat
from .services import age_bracket, record_access
from .tasks import label_cell

Event, Age = AccessStat.Event, AccessStat.Age


def make_user(email, **extra):
    return User.objects.create_user(email=email, password="SenhaForte123", name="Pessoa", **extra)


class AgeBracketTest(APITestCase):
    def test_only_with_consent_and_birthday(self):
        today = date(2026, 10, 4)
        consented = make_user("a@dtfd.com", allow_info=True, birthday=date(1980, 10, 5))
        self.assertEqual(Age.AGE_40_59, age_bracket(consented, today), "45 anos (aniversário amanhã)")
        consented.birthday = date(1966, 10, 4)
        self.assertEqual(Age.AGE_60_PLUS, age_bracket(consented, today))
        no_consent = make_user("b@dtfd.com", birthday=date(1980, 1, 1))
        self.assertEqual(Age.UNKNOWN, age_bracket(no_consent, today), "sem consentimento não entra")
        self.assertEqual(Age.UNKNOWN, age_bracket(None, today))


class RecordAccessTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("dono@dtfd.com")
        cls.r1 = Restaurant.objects.create(owner=cls.owner, name="Um", slug="um")
        cls.r2 = Restaurant.objects.create(owner=cls.owner, name="Dois", slug="dois")

    @patch("analytics.services.label_cell.delay")
    def test_increments_same_key_and_coarsens_location(self, delay):
        with self.captureOnCommitCallbacks(execute=True):
            record_access([self.r1.pk, self.r2.pk], Event.IMPRESSION, coords=(-22.21391, -49.94582))
            record_access([self.r1.pk], Event.IMPRESSION, coords=(-22.21409, -49.94611))  # mesma célula
            record_access([self.r1.pk], Event.IMPRESSION)  # sem localização = outra linha
        rows = AccessStat.objects.filter(restaurant=self.r1)
        self.assertEqual({2, 1}, set(rows.values_list("count", flat=True)))
        cell = GeoCell.objects.get()
        self.assertEqual(("-22.21", "-49.95"), (str(cell.lat), str(cell.lon)), "coordenada exata não é guardada")
        delay.assert_called_once_with(cell.pk)

    @patch("analytics.tasks.region_label", return_value="Centro, Marília")
    def test_label_cell(self, _mock):
        cell = GeoCell.objects.create(lat="-22.21", lon="-49.95")
        self.assertTrue(label_cell(cell.pk))
        cell.refresh_from_db()
        self.assertEqual("Centro, Marília", cell.label)


class InsightsTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("dono@dtfd.com")
        cls.other = make_user("outro@dtfd.com")
        cls.restaurant = Restaurant.objects.create(owner=cls.owner, name="Alvo", slug="alvo")
        cls.URL = f"/api/analytics/restaurants/{cls.restaurant.pk}/"
        today = timezone.localdate()
        center = GeoCell.objects.create(lat="-22.21", lon="-49.95", label="Centro, Marília")
        lonely = GeoCell.objects.create(lat="-22.30", lon="-49.90", label="Distrito")

        def add(event, n, hour=20, age=Age.UNKNOWN, cell=None, days_ago=0):
            AccessStat.objects.create(restaurant=cls.restaurant, date=today - timedelta(days=days_ago),
                                      hour=hour, event=event, age=age, cell=cell, count=n)

        add(Event.SEARCH_VIEW, 6, hour=20, cell=center)
        add(Event.VIEW, 4, hour=12, cell=center, age=Age.AGE_40_59)
        add(Event.VIEW, 2, hour=23, cell=lonely, age=Age.AGE_60_PLUS)  # grupo pequeno
        add(Event.IMPRESSION, 30, hour=20)
        add(Event.VIEW, 50, days_ago=60)  # fora da janela

    def get(self, **params):
        self.client.force_authenticate(self.owner)
        return self.client.get(self.URL, params)

    def test_unfiltered(self):
        data = self.get().json()
        self.assertEqual({"views": 12, "impressions": 30, "clicks": 6, "ctr": 0.2}, data["totals"])
        self.assertEqual([{"lat": -22.21, "lon": -49.95, "label": "Centro, Marília", "count": 10}], data["cells"],
                         "célula com menos de K acessos não vai pro mapa")
        self.assertEqual([{"label": "Centro, Marília", "count": 10}], data["regions"])
        hours = {h["hour"]: h["count"] for h in data["by_hour"]}
        self.assertEqual((6, None, None, 0), (hours[20], hours[12], hours[23], hours[3]), "1-4 vira null")
        self.assertEqual({"located": 12, "total": 12}, data["coverage"])

    def test_age_filter_masks_small_totals(self):
        data = self.get(age="40-59,60+").json()
        self.assertEqual(6, data["totals"]["views"])
        self.assertEqual([], data["cells"], "4 + 2 em células diferentes: nenhuma chega a K")
        only_60 = self.get(age="60+").json()
        self.assertIsNone(only_60["totals"]["views"], "2 acessos 60+ não aparecem")
        ages = {a["age"]: a["count"] for a in only_60["by_age"]}
        self.assertEqual(6, ages["unknown"], "distribuição etária ignora o filtro de idade")

    def test_hour_window_crossing_midnight(self):
        data = self.get(hour_from=22, hour_to=2).json()
        self.assertEqual({h["hour"] for h in data["by_hour"] if h["count"] is None}, {23})
        self.assertIsNone(data["coverage"]["total"], "só 2 acessos na madrugada")

    def test_metric_and_validation(self):
        self.assertEqual(30, sum(d["count"] or 0 for d in self.get(metric="impressions").json()["by_day"]))
        for bad in ({"days": 15}, {"metric": "x"}, {"age": "30-35"}, {"hour_from": 25}, {"days": "x"}):
            with self.subTest(bad=bad):
                self.assertEqual(status.HTTP_400_BAD_REQUEST, self.get(**bad).status_code)

    def test_only_owner_or_admin(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(status.HTTP_403_FORBIDDEN, self.client.get(self.URL).status_code)

    def test_pure_function_window(self):
        data = restaurant_insights(self.restaurant, days=90)
        self.assertEqual(62, data["totals"]["views"], "60 dias atrás entra na janela de 90")


class DetailAndSearchTrackingTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("dono@dtfd.com")
        cls.visitor = make_user("visita@dtfd.com", allow_info=True, birthday=date(1970, 1, 1))
        cls.restaurant = Restaurant.objects.create(owner=cls.owner, name="Alvo", slug="alvo")
        cls.URL = f"/api/restaurants/{cls.restaurant.pk}/"

    @patch("analytics.services.label_cell.delay")
    def test_visit_from_search_with_region_and_age(self, _delay):
        self.client.force_authenticate(self.visitor)
        self.client.get(self.URL, {"src": "search", "lat": "-22.2139", "lon": "-49.9458"})
        self.client.get(self.URL)
        rows = {r.event: r for r in AccessStat.objects.all()}
        self.assertEqual({Event.SEARCH_VIEW, Event.VIEW}, set(rows))
        self.assertEqual(age_bracket(self.visitor), rows[Event.VIEW].age)
        self.assertNotEqual(Age.UNKNOWN, rows[Event.VIEW].age, "consentiu e tem data de nascimento")
        self.assertIsNotNone(rows[Event.SEARCH_VIEW].cell)
        self.assertIsNone(rows[Event.VIEW].cell)

    def test_invalid_coordinates_and_anonymous(self):
        self.client.get(self.URL, {"lat": "abc", "lon": "1"})
        row = AccessStat.objects.get()
        self.assertEqual((None, Age.UNKNOWN, 1), (row.cell, row.age, row.count))

    def test_owner_visit_not_counted(self):
        self.client.force_authenticate(self.owner)
        self.client.get(self.URL, {"src": "search"})
        self.assertFalse(AccessStat.objects.exists())

    def test_owner_stats_read_access_stat(self):
        cell = GeoCell.objects.create(lat="-22.21", lon="-49.95", label="Centro, Marília")
        today = timezone.localdate()
        for event, n in ((Event.VIEW, 2), (Event.SEARCH_VIEW, 5), (Event.IMPRESSION, 20)):
            AccessStat.objects.create(restaurant=self.restaurant, date=today, hour=12, event=event, cell=cell, count=n)
        self.client.force_authenticate(self.owner)
        data = self.client.get(f"{self.URL}stats/").json()
        self.assertEqual((7, 20, 5, 0.25), (data["views_window"], data["search_impressions_window"],
                                            data["search_clicks_window"], data["search_ctr"]))
        self.assertEqual(7, data["regions"][0]["visits"])


class PlatformMetricsTest(APITestCase):
    URL = "/api/analytics/platform/"

    def test_admin_only_aggregates(self):
        admin = User.objects.create_superuser(email="adm@dtfd.com", password="SenhaForte123", name="Adm")
        owner = make_user("dono@dtfd.com", role="owner")
        r = Restaurant.objects.create(owner=owner, name="Sem geo", slug="sem-geo")
        PlatformDailyStat.objects.create(date=timezone.localdate(), searches=3, search_failures=1)
        AccessStat.objects.create(restaurant=r, date=timezone.localdate(), hour=1, event=Event.VIEW, count=4)

        self.client.force_authenticate(owner)
        self.assertEqual(status.HTTP_403_FORBIDDEN, self.client.get(self.URL).status_code)

        self.client.force_authenticate(admin)
        data = self.client.get(self.URL).json()
        self.assertEqual({"total": 2, "customers": 0, "owners": 1, "admins": 1, "consented": 0, "removed": 0}, data["users"])
        self.assertEqual(1, data["restaurants"]["without_coordinates"])
        self.assertEqual((3, 1, 4), (data["searches_window"], data["search_failures_window"], data["views_window"]))


@override_settings(DEBUG=True)
class SeedDemoAnalyticsTest(APITestCase):
    def test_generates_rows_near_restaurants(self):
        from address.models import Address
        from django.contrib.contenttypes.models import ContentType

        owner = make_user("dono@dtfd.com")
        r = Restaurant.objects.create(owner=owner, name="Alvo", slug="alvo")
        Address.objects.create(content_type=ContentType.objects.get_for_model(Restaurant), object_id=r.pk,
                               street="Rua", neighborhood="Centro", city="Marília", state="SP",
                               zipcode="17500-000", latitude="-22.2139", longitude="-49.9458", is_default=True)
        call_command("seed_analytics_demo", days=3, verbosity=0)
        call_command("seed_analytics_demo", days=3, clear=True, verbosity=0)  # idempotente com --clear
        self.assertTrue(AccessStat.objects.filter(restaurant=r, cell__isnull=False).exists())
        self.assertTrue(GeoCell.objects.filter(label="Centro, Marília").exists())
