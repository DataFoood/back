import hashlib

from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase

from restaurants.models import Restaurant, RestaurantReview, RestaurantImage
from users.models import User


class AccountClosureTest(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email='closed@test.example', name='Ana', password='Testpass1234')
        self.other = User.objects.create_user(email='stays@test.example', name='Bia', password='Testpass1234')
        self.restaurant = Restaurant.objects.create(name='Restaurante', slug='restaurante')
        RestaurantReview.objects.create(restaurant=self.restaurant, author=self.user, rating=1, description='Meu comentário')
        RestaurantReview.objects.create(restaurant=self.restaurant, author=self.other, rating=5)
        self.restaurant.recalc_rating()
        self.client.force_authenticate(self.user)

    def test_soft_closure_removes_reviews_and_recalculates_rating(self):
        response = self.client.delete(f'/api/users/{self.user.pk}/delete/')
        self.assertEqual(204, response.status_code)
        self.assertFalse(RestaurantReview.all_objects.filter(author=self.user).exists())
        self.restaurant.refresh_from_db()
        self.assertEqual(1, self.restaurant.total_reviews)
        self.assertEqual(5, self.restaurant.average_rating)

    def test_database_cascade_also_recalculates_rating(self):
        self.user.delete()
        self.restaurant.refresh_from_db()
        self.assertEqual(1, self.restaurant.total_reviews)
        self.assertEqual(5, self.restaurant.average_rating)

    def test_gallery_image_becomes_api_cover(self):
        RestaurantImage.objects.create(restaurant=self.restaurant, url='https://example.org/real-photo.jpg')
        card = self.client.get('/api/restaurants/').json()['results'][0]
        self.assertEqual('https://example.org/real-photo.jpg', card['cover_image'])

    @override_settings(PREMIUM_TEST_COUPON_SHA256=hashlib.sha256(b'test-only-coupon').hexdigest())
    def test_coupon_changes_plan_only_and_is_persistent(self):
        self.assertEqual(400, self.client.post('/api/users/premium/redeem/', {'code': 'wrong'}, format='json').status_code)
        response = self.client.post('/api/users/premium/redeem/', {'code': 'test-only-coupon'}, format='json')
        self.assertEqual(200, response.status_code)
        self.user.refresh_from_db()
        self.assertEqual(2, self.user.level)
        self.assertFalse(self.user.allow_info)
        self.assertEqual('customer', self.user.role)
        self.assertEqual(2, self.client.get('/api/users/me/').json()['level'])
