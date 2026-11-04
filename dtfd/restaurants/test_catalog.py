import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from users.models import User
from .models import Restaurant, RestaurantSource, CatalogImport
from .catalog import osm


class CatalogTest(TestCase):
    def record(self, **tags):
        return osm.normalize(dict(type='node', id=123, lat=-22.21, lon=-49.95,
                                  tags={'name': 'Restaurante teste', 'amenity': 'restaurant', **tags}))

    def test_import_is_idempotent_and_preserves_owner_edits(self):
        self.assertEqual('created', osm.upsert(self.record()))
        self.assertEqual('updated', osm.upsert(self.record()))
        self.assertEqual(1, Restaurant.objects.count())
        restaurant = Restaurant.objects.get()
        self.assertFalse(restaurant.business_hours.exists())
        self.assertEqual(0, restaurant.total_reviews)
        restaurant.owner = User.objects.create_user(email='owner@test.example', name='Owner', password='Testing12345')
        restaurant.name = 'Nome verificado pelo dono'
        restaurant.save()
        osm.upsert(self.record(name='Nome novo no OSM'))
        restaurant.refresh_from_db()
        self.assertEqual('Nome verificado pelo dono', restaurant.name)
        self.assertEqual('Nome novo no OSM', RestaurantSource.objects.get().data['tags']['name'])

    def test_removed_source_is_not_resurrected(self):
        osm.upsert(self.record())
        from django.utils import timezone
        Restaurant.objects.update(deleted_at=timezone.now())
        self.assertEqual('removed', osm.upsert(self.record()))
        self.assertFalse(Restaurant.objects.exists())

    def test_invalid_elements_are_not_restaurants(self):
        self.assertIsNone(osm.normalize({'type': 'node', 'id': 1, 'tags': {'amenity': 'restaurant'}}))
        self.assertIsNone(osm.normalize({'type': 'node', 'id': 1, 'lat': float('nan'), 'lon': 0, 'tags': {'name': 'X', 'amenity': 'restaurant'}}))
        self.assertEqual('', osm.safe_website('javascript:alert(1)'))

    def test_public_source_and_demo_filter(self):
        osm.upsert(self.record())
        Restaurant.objects.create(name='Demo', slug='demo', is_demo=True)
        with override_settings(SHOW_DEMO_RESTAURANTS=False):
            client = APIClient()
            response = client.get('/api/restaurants/')
            self.assertEqual(1, response.json()['count'])
            source = response.json()['results'][0]['sources'][0]
            self.assertEqual('ODbL-1.0', source['license'])
            self.assertNotIn('data', source)
            self.assertEqual(404, client.get('/api/restaurants/by-slug/demo/').status_code)

    def test_dry_run_does_not_write_restaurants(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'osm.json'
            path.write_text(json.dumps({'elements': [dict(type='node', id=123, lat=-22.21, lon=-49.95, tags={'name': 'Teste', 'amenity': 'restaurant'})]}))
            call_command('import_osm', file=path, dry_run=True, stdout=StringIO())
        self.assertFalse(Restaurant.objects.exists())
        self.assertEqual('preview', CatalogImport.objects.get().status)
