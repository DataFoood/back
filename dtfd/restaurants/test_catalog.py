import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
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

    def test_imported_phone_does_not_imply_whatsapp(self):
        osm.upsert(self.record(phone='1433334444'))
        restaurant = Restaurant.objects.get()
        self.assertEqual('1433334444', restaurant.phone)
        self.assertEqual('', restaurant.whatsapp_number)

    def test_explicit_osm_tags_enable_filters_without_guessing_price_or_ambience(self):
        osm.upsert(self.record(cuisine='italian;pizza', outdoor_seating='yes'))
        restaurant = Restaurant.objects.get()
        self.assertSetEqual({'Italiana', 'Pizza & Massas'}, set(restaurant.cuisines.values_list('name', flat=True)))
        self.assertEqual(['Ao Ar Livre'], list(restaurant.ambients.values_list('name', flat=True)))
        self.assertFalse(restaurant.price_ranges.exists())
        osm.upsert(self.record(cuisine='unmapped', outdoor_seating='no'))
        self.assertFalse(restaurant.cuisines.exists())
        self.assertFalse(restaurant.ambients.exists())

    def test_replace_archives_old_catalog_and_keeps_accounts_and_imported_ids(self):
        user = User.objects.create_user(email='keep@test.example', name='Conta', password='Testing12345')
        old = Restaurant.objects.create(name='Catálogo anterior', slug='old', owner=user)
        from promotions.models import Promotion
        promotion = Promotion.objects.create(restaurant=old, title='Campanha antiga', message='Teste', status='scheduled')
        payload = {'elements': [dict(type='node', id=123, lat=-22.21, lon=-49.95,
                    tags={'name': 'Restaurante de Marília', 'amenity': 'restaurant'})]}
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'osm.json'
            path.write_text(json.dumps(payload), encoding='utf-8')
            call_command('import_osm', file=path, replace=True, dry_run=True, stdout=StringIO())
            self.assertTrue(Restaurant.objects.filter(pk=old.pk).exists())
            call_command('import_osm', file=path, replace=True, stdout=StringIO())
            imported = Restaurant.objects.get()
            call_command('import_osm', file=path, replace=True, stdout=StringIO())
        self.assertEqual([imported.pk], list(Restaurant.objects.values_list('pk', flat=True)))
        self.assertTrue(Restaurant.all_objects.filter(pk=old.pk, deleted_at__isnull=False).exists())
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertFalse(Promotion.objects.filter(pk=promotion.pk).exists())
        self.assertTrue(Promotion.all_objects.filter(pk=promotion.pk).exists())
        self.assertEqual('Marília', imported.addresses.get().city)

    def test_replace_requires_nonempty_validated_file_and_rolls_back_partial_failure(self):
        old = Restaurant.objects.create(name='Catálogo anterior', slug='old')
        with self.assertRaises(CommandError):
            call_command('import_osm', replace=True, stdout=StringIO())
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'osm.json'
            for payload in ({'elements': []}, {'elements': [], 'remark': 'timeout'}):
                path.write_text(json.dumps(payload), encoding='utf-8')
                with self.assertRaises(CommandError):
                    call_command('import_osm', file=path, replace=True, stdout=StringIO())
            element = dict(type='node', id=123, lat=-22.21, lon=-49.95,
                           tags={'name': 'Novo', 'amenity': 'restaurant'})
            path.write_text(json.dumps({'elements': [element, {**element, 'id': 124}]}), encoding='utf-8')
            real_upsert = osm.upsert
            def fail_second(record, **kwargs):
                if record['external_id'] == 'node/124':
                    raise ValueError('Falha simulada')
                return real_upsert(record, **kwargs)
            with patch('restaurants.catalog.osm.upsert', side_effect=fail_second):
                with self.assertRaises(CommandError):
                    call_command('import_osm', file=path, replace=True, stdout=StringIO())
        self.assertEqual([old.pk], list(Restaurant.objects.values_list('pk', flat=True)))
        self.assertFalse(RestaurantSource.objects.exists())
