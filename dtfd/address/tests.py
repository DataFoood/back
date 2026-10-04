from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from rest_framework import status
from rest_framework.test import APITestCase

from restaurants.models import Restaurant
from users.models import User

from .models import Address


def make_user(email="user@dtfd.com", name="User"):
    return User.objects.create_user(email=email, password="SenhaForte123", name=name)


def make_admin(email="admin@dtfd.com"):
    return User.objects.create_superuser(email=email, password="SenhaForte123", name="Admin")


def make_restaurant(owner, name="Cantina"):
    return Restaurant.objects.create(owner=owner, name=name, slug=name.lower())


def address_for(entity):
    ct = ContentType.objects.get_for_model(entity.__class__)
    return Address.objects.create(
        content_type=ct, object_id=entity.pk,
        street="Rua A", city="SP", state="SP", zipcode="01000-000",
    )


BASE = "/api/addresses/"


# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------
class AddressCreateTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()
        cls.other = make_user(email="other@dtfd.com")
        cls.restaurant = make_restaurant(cls.user)
        cls.foreign_restaurant = make_restaurant(cls.other, name="Alheio")

    def _payload(self, entity_type, object_id):
        return {
            "entity_type": entity_type,
            "object_id": object_id,
            "street": "Av Paulista",
            "number": "1000",
            "city": "Sao Paulo",
            "state": "SP",
            "zipcode": "01310-100",
        }

    # --- happy ---
    def test_create_address_for_self(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(BASE, data=self._payload("user", self.user.pk), format="json")
        with self.subTest():
            self.assertEqual(status.HTTP_201_CREATED, response.status_code)
        self.assertEqual("user", response.json()["entity_type"])
        self.assertEqual(1, Address.objects.count())

    def test_create_address_for_owned_restaurant(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            BASE, data=self._payload("restaurant", self.restaurant.pk), format="json"
        )
        with self.subTest():
            self.assertEqual(status.HTTP_201_CREATED, response.status_code)
        self.assertEqual("restaurant", response.json()["entity_type"])

    # --- unhappy ---
    def test_create_unauthenticated(self):
        response = self.client.post(BASE, data=self._payload("user", self.user.pk), format="json")
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)

    def test_create_for_another_user_forbidden(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(BASE, data=self._payload("user", self.other.pk), format="json")
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)

    def test_create_for_unowned_restaurant_forbidden(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            BASE, data=self._payload("restaurant", self.foreign_restaurant.pk), format="json"
        )
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)

    def test_create_invalid_entity_type(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(BASE, data=self._payload("planet", self.user.pk), format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("entity_type", response.json())

    def test_create_nonexistent_target(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(BASE, data=self._payload("user", 99999), format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("object_id", response.json())

    def test_create_without_required_fields(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(BASE, data={}, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_new_default_unsets_previous(self):
        self.client.force_authenticate(self.user)
        p1 = {**self._payload("user", self.user.pk), "is_default": True}
        p2 = {**self._payload("user", self.user.pk), "is_default": True, "street": "Rua Nova"}
        r1 = self.client.post(BASE, data=p1, format="json")
        r2 = self.client.post(BASE, data=p2, format="json")
        addr1 = Address.objects.get(pk=r1.json()["id"])
        addr2 = Address.objects.get(pk=r2.json()["id"])
        self.assertFalse(addr1.is_default, "endereço default anterior deve ser desmarcado")
        self.assertTrue(addr2.is_default)
        # so um default por entidade
        defaults = Address.objects.filter(
            content_type=addr1.content_type, object_id=self.user.pk, is_default=True
        ).count()
        self.assertEqual(1, defaults)


# ---------------------------------------------------------------------------
# LIST
# ---------------------------------------------------------------------------
class AddressListTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()
        cls.other = make_user(email="other@dtfd.com")
        cls.restaurant = make_restaurant(cls.user)
        cls.own_user_addr = address_for(cls.user)
        cls.own_rest_addr = address_for(cls.restaurant)
        cls.foreign_addr = address_for(cls.other)

    def test_list_returns_only_owned(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(BASE)
        with self.subTest():
            self.assertEqual(status.HTTP_200_OK, response.status_code)
        ids = {a["id"] for a in response.json()}
        self.assertIn(self.own_user_addr.pk, ids)
        self.assertIn(self.own_rest_addr.pk, ids, "endereço do restaurante do user deve aparecer")
        self.assertNotIn(self.foreign_addr.pk, ids, "endereço alheio não deve vazar")

    def test_list_unauthenticated(self):
        response = self.client.get(BASE)
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)


# ---------------------------------------------------------------------------
# DETAIL / UPDATE / DELETE
# ---------------------------------------------------------------------------
class AddressModifyTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()
        cls.other = make_user(email="other@dtfd.com")
        cls.admin = make_admin()
        cls.addr = address_for(cls.user)
        cls.URL = f"{BASE}{cls.addr.pk}/"

    # --- happy ---
    def test_owner_retrieves(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(self.URL)
        self.assertEqual(status.HTTP_200_OK, response.status_code)

    def test_owner_updates(self):
        self.client.force_authenticate(self.user)
        response = self.client.patch(self.URL, data={"city": "Campinas"}, format="json")
        with self.subTest():
            self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.addr.refresh_from_db()
        self.assertEqual("Campinas", self.addr.city)

    def test_admin_updates(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch(self.URL, data={"city": "Admin City"}, format="json")
        self.assertEqual(status.HTTP_200_OK, response.status_code)

    def test_owner_soft_deletes(self):
        self.client.force_authenticate(self.user)
        response = self.client.delete(self.URL)
        with self.subTest():
            self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        self.assertFalse(Address.objects.filter(pk=self.addr.pk).exists())
        self.assertIsNotNone(Address.all_objects.get(pk=self.addr.pk).deleted_at)

    # --- unhappy ---
    def test_other_cannot_retrieve(self):
        self.client.force_authenticate(self.other)
        response = self.client.get(self.URL)
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)

    def test_other_cannot_update(self):
        self.client.force_authenticate(self.other)
        response = self.client.patch(self.URL, data={"city": "Hack"}, format="json")
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)

    def test_other_cannot_delete(self):
        self.client.force_authenticate(self.other)
        response = self.client.delete(self.URL)
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)

    def test_update_cannot_rebind_entity(self):
        # tentar trocar object_id pra outra entidade deve ser ignorado
        self.client.force_authenticate(self.user)
        self.client.patch(self.URL, data={"object_id": self.other.pk}, format="json")
        self.addr.refresh_from_db()
        self.assertEqual(self.user.pk, self.addr.object_id, "object_id não pode ser remapeado em update")


# ---------------------------------------------------------------------------
# GEOCODING (Nominatim falso)
# ---------------------------------------------------------------------------
from unittest.mock import MagicMock, patch

from .geocoding import geocode
from .tasks import geocode_address


def nominatim(*responses):
    """httpx.get falso que devolve as respostas em ordem."""
    fakes = []
    for body in responses:
        fake = MagicMock()
        fake.json.return_value = body
        fakes.append(fake)
    return patch("address.geocoding.httpx.get", side_effect=fakes)


class GeocodingTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user()
        cls.restaurant = make_restaurant(cls.owner)

    def test_geocode_falls_back_to_city(self):
        address = address_for(self.restaurant)
        with nominatim([], [{"lat": "-22.2139", "lon": "-49.9458"}]) as get:
            self.assertEqual((Decimal("-22.213900"), Decimal("-49.945800")), geocode(address))
        self.assertIn("street", get.call_args_list[0].kwargs["params"])
        self.assertNotIn("street", get.call_args_list[1].kwargs["params"])
        self.assertIn("DataFood", get.call_args.kwargs["headers"]["User-Agent"])

    def test_task_saves_coordinates(self):
        address = address_for(self.restaurant)
        with nominatim([{"lat": "-22.2", "lon": "-49.9"}]):
            self.assertTrue(geocode_address(address.pk))
        address.refresh_from_db()
        self.assertEqual(Decimal("-22.200000"), address.latitude)

    def test_task_survives_nominatim_down(self):
        import httpx
        address = address_for(self.restaurant)
        with patch("address.geocoding.httpx.get", side_effect=httpx.ConnectError("down")):
            self.assertFalse(geocode_address(address.pk))

    @patch("address.views.geocode_address.delay")
    def test_restaurant_address_is_geocoded_after_commit(self, delay):
        self.client.force_authenticate(self.owner)
        body = {"entity_type": "restaurant", "object_id": self.restaurant.pk,
                "street": "Rua A", "city": "Marília", "state": "SP", "zipcode": "17500-000"}
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(BASE, body, format="json")
        delay.assert_called_once_with(response.json()["id"])

    @patch("address.views.geocode_address.delay")
    def test_user_address_never_leaves(self, delay):
        self.client.force_authenticate(self.owner)
        body = {"entity_type": "user", "object_id": self.owner.pk,
                "street": "Rua A", "city": "Marília", "state": "SP", "zipcode": "17500-000"}
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(BASE, body, format="json")
        delay.assert_not_called()

    @patch("address.views.geocode_address.delay")
    def test_manual_coordinates_are_respected(self, delay):
        self.client.force_authenticate(self.owner)
        address = address_for(self.restaurant)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(f"{BASE}{address.pk}/", {"street": "Rua B", "latitude": "-22.1", "longitude": "-49.9"}, format="json")
        delay.assert_not_called()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(f"{BASE}{address.pk}/", {"street": "Rua C"}, format="json")
        delay.assert_called_once_with(address.pk)
