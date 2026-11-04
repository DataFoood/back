from unittest.mock import patch
import httpx
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIClient
from address.models import Address
from users.models import User
from .models import Restaurant


class LocationTest(TestCase):
    def setUp(self):
        self.near = Restaurant.objects.create(name='Pizza Centro', slug='pizza-centro')
        self.far = Restaurant.objects.create(name='Pizza Longe', slug='pizza-longe')
        ct = ContentType.objects.get_for_model(Restaurant)
        for r, lat in [(self.near, -22.217), (self.far, -23.5)]:
            Address.objects.create(content_type=ct, object_id=r.pk, street='Teste', city='Marília', state='SP', zipcode='', latitude=lat, longitude=-49.95)
        self.client = APIClient()

    def test_distance_filter_precedes_pagination(self):
        response = self.client.get('/api/restaurants/', {'lat': -22.217, 'lon': -49.95, 'radius_km': 5, 'ordering': 'distance', 'page_size': 1})
        self.assertEqual(200, response.status_code)
        self.assertEqual(1, response.json()['count'])
        self.assertEqual(self.near.pk, response.json()['results'][0]['id'])
        self.assertLess(response.json()['results'][0]['distance_km'], .01)

    def test_invalid_location_is_rejected(self):
        for params in [{'lat': 'NaN', 'lon': 0}, {'lat': 0}, {'radius_km': 10}, {'lat': 0, 'lon': 0, 'radius_km': 500}]:
            self.assertEqual(400, self.client.get('/api/restaurants/', params).status_code)

    @patch('restaurants.views.httpx.post', side_effect=httpx.ConnectError('offline'))
    def test_text_recovery_respects_location(self, remote):
        user = User.objects.create_user(email='search@test.example', name='Search', password='Testing12345')
        self.client.force_authenticate(user)
        response = self.client.post('/api/search/', {'query': 'pizza', 'lat': -22.217, 'lon': -49.95, 'radius_km': 5}, format='json')
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual('text', data['mode'])
        self.assertEqual([self.near.pk], [r['restaurant']['id'] for r in data['results']])
        self.assertIsNone(data['results'][0]['match'])
        self.assertEqual([self.near.pk], remote.call_args.kwargs['json']['candidate_ids'])

    def test_numeric_zero_radius_is_not_treated_as_default(self):
        from rest_framework.exceptions import ValidationError
        from .location import apply_location
        with self.assertRaises(ValidationError):
            apply_location(Restaurant.objects.all(), {'lat': 0, 'lon': 0, 'radius_km': 0})

    @patch('restaurants.views.httpx.post')
    def test_malformed_search_response_uses_text_recovery(self, remote):
        user = User.objects.create_user(email='malformed@test.example', name='Search', password='Testing12345')
        self.client.force_authenticate(user)
        remote.return_value.status_code = 200
        remote.return_value.json.return_value = []
        response = self.client.post('/api/search/', {'query': 'pizza'}, format='json')
        self.assertEqual(200, response.status_code)
        self.assertEqual('text', response.json()['mode'])
        self.assertEqual(2, len(response.json()['results']))
