from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from users.models import User
from .catalog import tourism
from .catalog.hours import parse_hours
from .catalog.osm import normalize, upsert
from .catalog.websites import public_url, image_url
from .models import Restaurant, RestaurantSource, RestaurantImage


class CatalogEnrichmentTest(TestCase):
    def record(self, **values):
        return {'source_id': '123', 'source_url': 'https://turismo.marilia.sp.gov.br/turismo/pizza-exemplo/123',
                'name': 'Pizza Exemplo', 'image_url': 'https://turismo.marilia.sp.gov.br/fotos/exemplo.jpg',
                'address_raw': 'Rua Exemplo, 25 - Centro, Marília - SP, 17500-000', 'phone': '1433334444',
                'categories': ['Pizzarias'], 'opening_hours': 'Segunda a sábado, das 18h às 23h', **values}

    def test_official_load_is_idempotent_and_retains_photo_credit(self):
        self.assertEqual('created', tourism.upsert(self.record(), timezone.now()))
        self.assertEqual('updated', tourism.upsert(self.record(), timezone.now()))
        self.assertEqual(1, Restaurant.objects.count())
        self.assertEqual(1, RestaurantImage.objects.count())
        restaurant = Restaurant.objects.get()
        self.assertEqual('Marília', restaurant.addresses.get().city)
        self.assertEqual('Centro', restaurant.addresses.get().neighborhood)
        self.assertEqual('25', restaurant.addresses.get().number)
        self.assertEqual(self.record()['source_url'], restaurant.images.get().source_url)
        self.assertEqual('', restaurant.images.get().license)

    def test_existing_osm_place_is_enriched_not_duplicated(self):
        record = normalize({'type': 'node', 'id': 1, 'lat': -22.2, 'lon': -49.9,
            'tags': {'name': 'Pizza Exemplo', 'amenity': 'restaurant', 'phone': '1433334444'}})
        upsert(record)
        self.assertEqual('updated', tourism.upsert(self.record(), timezone.now()))
        self.assertEqual(1, Restaurant.objects.count())
        self.assertEqual(2, RestaurantSource.objects.count())

    def test_same_name_different_branch_address_is_not_merged(self):
        tourism.upsert(self.record(), timezone.now())
        tourism.upsert(self.record(source_id='124', source_url='https://turismo.marilia.sp.gov.br/turismo/pizza-exemplo/124', address_raw='Rua Outra, 99 - Centro, Marília - SP'), timezone.now())
        self.assertEqual(2, Restaurant.objects.count())

    def test_owner_edits_and_removed_places_are_preserved(self):
        tourism.upsert(self.record(), timezone.now())
        restaurant = Restaurant.objects.get()
        restaurant.owner = User.objects.create_user(email='owner-photo@test.example', name='Dono', password='Test123456')
        restaurant.description = 'Texto do dono'
        restaurant.cover_image = 'https://example.org/owner.jpg'
        restaurant.save()
        tourism.upsert(self.record(), timezone.now())
        restaurant.refresh_from_db()
        self.assertEqual('Texto do dono', restaurant.description)
        self.assertEqual('https://example.org/owner.jpg', restaurant.cover_image)
        restaurant.deleted_at = timezone.now()
        restaurant.save()
        self.assertEqual('removed', tourism.upsert(self.record(), timezone.now()))

    def test_unsafe_source_and_images_are_rejected(self):
        for values in ({'source_url': 'http://localhost/turismo/a/123'}, {'image_url': 'https://localhost/fotos/a.jpg'}):
            with self.assertRaises(ValueError):
                tourism.validate_record(self.record(**values))
        self.assertEqual('', image_url('javascript:alert(1)', 'https://example.org'))
        self.assertEqual('', image_url('https://127.0.0.1/private.jpg', 'https://example.org'))

    @patch('restaurants.catalog.websites.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))])
    def test_website_enrichment_does_not_request_internal_network(self, lookup):
        with self.assertRaises(ValueError):
            public_url('https://example.org', {'example.org'})

    def test_hours_are_only_structured_when_unambiguous(self):
        self.assertEqual(7, len(parse_hours('Mo-Sa 11:00-15:00; Su off')))
        self.assertEqual({}, parse_hours('Mo-Fr 11:00-15:00'))
        self.assertEqual({}, parse_hours('Mo-Su 20:00-02:00'))
        self.assertEqual({}, parse_hours('24/7'))
