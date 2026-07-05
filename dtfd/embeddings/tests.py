from unittest.mock import MagicMock, patch

from django.test import TestCase

from restaurants.models import Cuisine, Restaurant, RestaurantItem

from .documents import build_restaurant_document
from .models import RestaurantEmbedding
from .services import reindex_all, reindex_restaurant

FAKE_VECTOR = [0.1] * 768


def make_restaurant(name="Trattoria"):
    return Restaurant.objects.create(name=name, slug=name.lower())


class DocumentBuilderTest(TestCase):
    def test_document_includes_semantic_fields(self):
        r = make_restaurant()
        r.cuisines.set([Cuisine.objects.get(name="Italiana")])
        RestaurantItem.objects.create(restaurant=r, name="Feijoada")
        r.has_delivery = True
        r.description = "Comida caseira"
        r.save(update_fields=["has_delivery", "description"])

        doc = build_restaurant_document(r)
        self.assertIn("Trattoria", doc)
        self.assertIn("Comida caseira", doc)
        self.assertIn("Italiana", doc)
        self.assertIn("Feijoada", doc)
        self.assertIn("delivery", doc)


class ReindexTest(TestCase):
    @patch("embeddings.services.embed_text", return_value=FAKE_VECTOR)
    def test_reindex_creates_embedding_and_clears_stale(self, _mock):
        r = make_restaurant()
        self.assertTrue(r.embedding_stale, "novo restaurante nasce stale")
        reindex_restaurant(r)

        self.assertTrue(RestaurantEmbedding.objects.filter(restaurant=r).exists())
        r.refresh_from_db()
        self.assertFalse(r.embedding_stale, "reindex limpa o flag")

    @patch("embeddings.services.embed_text", return_value=FAKE_VECTOR)
    def test_reindex_all_only_stale(self, _mock):
        r1 = make_restaurant("A")
        r2 = make_restaurant("B")
        reindex_restaurant(r1)  # r1 deixa de ser stale
        count = reindex_all(only_stale=True)
        self.assertEqual(1, count, "só r2 (stale) deve ser processado")

    @patch("embeddings.services.embed_text", return_value=FAKE_VECTOR)
    def test_reindex_all_force(self, _mock):
        make_restaurant("A")
        make_restaurant("B")
        reindex_all(only_stale=True)  # zera ambos
        count = reindex_all(only_stale=False)
        self.assertEqual(2, count, "--all reprocessa todos")


class StaleSignalTest(TestCase):
    @patch("embeddings.services.embed_text", return_value=FAKE_VECTOR)
    def _fresh_restaurant(self, mock):
        r = make_restaurant()
        reindex_restaurant(r)
        r.refresh_from_db()
        return r

    def test_name_change_marks_stale(self):
        r = self._fresh_restaurant()
        r.name = "Novo Nome"
        r.save(update_fields=["name"])
        r.refresh_from_db()
        self.assertTrue(r.embedding_stale)

    def test_adding_cuisine_marks_stale(self):
        r = self._fresh_restaurant()
        r.cuisines.add(Cuisine.objects.get(name="Japonesa"))
        r.refresh_from_db()
        self.assertTrue(r.embedding_stale)

    def test_adding_item_marks_stale(self):
        r = self._fresh_restaurant()
        RestaurantItem.objects.create(restaurant=r, name="Sushi")
        r.refresh_from_db()
        self.assertTrue(r.embedding_stale)

    def test_rating_recalc_does_not_mark_stale(self):
        r = self._fresh_restaurant()
        r.recalc_rating()  # save(update_fields=[average_rating, total_reviews])
        r.refresh_from_db()
        self.assertFalse(r.embedding_stale, "mudança de rating não reindexar")


from rest_framework import status
from rest_framework.test import APITestCase
from users.models import User


class ReindexEndpointTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(email="a@dtfd.com", password="SenhaForte123", name="A")
        cls.common = User.objects.create_user(email="c@dtfd.com", password="SenhaForte123", name="C")
        cls.URL = "/api/embeddings/reindex/"

    @patch("embeddings.views.reindex_all_task.delay")
    def test_admin_enqueues_reindex(self, mock_delay):
        mock_delay.return_value = MagicMock(id="task-123")
        self.client.force_authenticate(self.admin)
        response = self.client.post(self.URL, data={"all": True}, format="json")
        self.assertEqual(status.HTTP_202_ACCEPTED, response.status_code)
        self.assertEqual("task-123", response.json()["task_id"])
        mock_delay.assert_called_once()

    def test_non_admin_forbidden(self):
        self.client.force_authenticate(self.common)
        response = self.client.post(self.URL, data={}, format="json")
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)
