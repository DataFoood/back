from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from preferences.models import RankingWeight, UserCuisineAffinity
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


from statistics import pstdev

from django.test import SimpleTestCase

from users.models import User

from .search import DEFAULT_WEIGHTS, Candidate, _zscores, haversine_km, rank, search

WEIGHTS = DEFAULT_WEIGHTS


def unit_vector(i):
    v = [0.0] * 768
    v[i] = 1.0
    return v


class RankingTest(SimpleTestCase):
    def test_zscores_mean_zero_std_one(self):
        z = _zscores([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertAlmostEqual(0.0, sum(z), msg="média 0")
        self.assertAlmostEqual(1.0, pstdev(z), msg="desvio populacional 1")

    def test_zscores_constant_returns_zeros(self):
        self.assertEqual([0.0, 0.0, 0.0], _zscores([7.0, 7.0, 7.0]))

    def test_semantic_dominates_preference(self):
        # A: melhor semântica, preferência zero. B: pior semântica, preferência alta.
        candidates = [
            Candidate(restaurant_id=1, semantic=0.95, preference=0.0, review=3.0),
            Candidate(restaurant_id=2, semantic=0.50, preference=10.0, review=3.0),
        ]
        ranked = rank(candidates, WEIGHTS, limit=15)
        self.assertEqual(1, ranked[0][0], "semântica manda mais que preferência")

    def test_preference_breaks_tie(self):
        candidates = [
            Candidate(restaurant_id=1, semantic=0.8, preference=0.0, review=4.0),
            Candidate(restaurant_id=2, semantic=0.8, preference=5.0, review=4.0),
        ]
        ranked = rank(candidates, WEIGHTS, limit=15)
        self.assertEqual(2, ranked[0][0])

    def test_limit_truncates(self):
        candidates = [
            Candidate(restaurant_id=i, semantic=i / 10, preference=0.0, review=0.0)
            for i in range(20)
        ]
        self.assertEqual(15, len(rank(candidates, WEIGHTS, limit=15)))

    def test_empty(self):
        self.assertEqual([], rank([], WEIGHTS, 15))

    def test_zscores_unknown_is_neutral(self):
        self.assertEqual([-1.0, 0.0, 1.0], _zscores([1.0, None, 3.0]))
        self.assertEqual([0.0, 0.0], _zscores([None, None]))

    def test_nearer_wins_when_rest_ties(self):
        candidates = [
            Candidate(1, semantic=0.8, preference=0.0, review=4.0, distance_km=9.0),
            Candidate(2, semantic=0.8, preference=0.0, review=4.0, distance_km=1.0),
            Candidate(3, semantic=0.8, preference=0.0, review=4.0, distance_km=None),
        ]
        ranked = [rid for rid, _ in rank(candidates, WEIGHTS, 15)]
        self.assertEqual([2, 3, 1], ranked, "sem coordenada fica neutro, no meio")

    def test_semantic_still_dominates_distance(self):
        candidates = [
            Candidate(1, semantic=0.95, preference=0.0, review=4.0, distance_km=20.0),
            Candidate(2, semantic=0.50, preference=0.0, review=4.0, distance_km=0.5),
        ]
        self.assertEqual(1, rank(candidates, WEIGHTS, 15)[0][0])

    def test_haversine(self):
        # São Paulo (Sé) -> Marília: ~370 km em linha reta
        self.assertAlmostEqual(375, haversine_km(-23.5505, -46.6333, -22.2139, -49.9458), delta=15)
        self.assertEqual(0, haversine_km(-22.2, -49.9, -22.2, -49.9))


@patch("embeddings.search.embed_text", return_value=unit_vector(0))
class SearchPipelineTest(TestCase):
    """kNN real no pgvector; só o Ollama é falso."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email="u@dtfd.com", password="SenhaForte123", name="U")
        cls.near = make_restaurant("Perto")
        cls.far = make_restaurant("Longe")
        for r, vec in ((cls.near, unit_vector(0)), (cls.far, unit_vector(1))):
            RestaurantEmbedding.objects.create(restaurant=r, embedding=vec, document="d", model="m")

    def test_orders_by_similarity(self, _mock):
        results = search(self.user, "perto", limit=10)
        self.assertEqual([self.near.pk, self.far.pk], [rid for rid, *_ in results])
        self.assertAlmostEqual(1.0, results[0][2], places=5, msg="similaridade de cosseno")

    def test_ignores_soft_deleted(self, _mock):
        Restaurant.objects.filter(pk=self.near.pk).update(deleted_at=timezone.now())
        self.assertEqual([self.far.pk], [rid for rid, *_ in search(self.user, "perto", 10)])

    def _place(self, restaurant, lat, lon):
        from address.models import Address
        from django.contrib.contenttypes.models import ContentType

        Address.objects.create(
            content_type=ContentType.objects.get_for_model(Restaurant), object_id=restaurant.pk,
            street="Rua", city="Marília", state="SP", zipcode="17500-000",
            latitude=lat, longitude=lon, is_default=True,
        )

    def test_distance_and_radius(self, _mock):
        self._place(self.near, Decimal("-22.2139"), Decimal("-49.9458"))  # centro
        self._place(self.far, Decimal("-22.3000"), Decimal("-49.9458"))   # ~9,6 km ao sul
        results = search(self.user, "perto", 10, origin=(-22.2139, -49.9458))
        self.assertAlmostEqual(0.0, results[0][3], places=3)
        self.assertAlmostEqual(9.6, results[1][3], delta=0.2)
        within = search(self.user, "perto", 10, origin=(-22.2139, -49.9458), radius_km=5)
        self.assertEqual([self.near.pk], [rid for rid, *_ in within])

    def test_radius_drops_restaurants_without_coordinates(self, _mock):
        self.assertEqual([], search(self.user, "perto", 10, origin=(-22.2, -49.9), radius_km=50))

    def test_preference_uses_user_affinities(self, _mock):
        italiana = Cuisine.objects.get(name="Italiana")
        self.far.cuisines.set([italiana])
        UserCuisineAffinity.objects.create(user=self.user, cuisine=italiana, score=1.0)
        # zera o peso semântico: só a preferência decide
        RankingWeight.objects.filter(key="semantic").update(weight=0.0)
        self.assertEqual(self.far.pk, search(self.user, "perto", 10)[0][0])
