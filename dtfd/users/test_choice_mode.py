from django.test import TestCase
from rest_framework.test import APIClient
from .models import User


class ChoiceModeTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='choice@test.example', name='Choice', password='Testing12345')
        self.other = User.objects.create_user(email='other-choice@test.example', name='Other', password='Testing12345')
        self.client = APIClient()

    def test_default_and_preference_survive_new_session(self):
        self.client.force_authenticate(self.user)
        self.assertFalse(self.client.get('/api/users/me/').json()['choice_mode'])
        response = self.client.patch('/api/users/me/', {'choice_mode': True}, format='json')
        self.assertEqual(200, response.status_code)
        self.user.refresh_from_db()
        self.assertTrue(self.user.choice_mode)
        other_browser = APIClient()
        other_browser.force_authenticate(self.user)
        self.assertTrue(other_browser.get('/api/users/me/').json()['choice_mode'])
        self.assertEqual(200, other_browser.patch('/api/users/me/', {'choice_mode': False}, format='json').status_code)
        self.user.refresh_from_db()
        self.assertFalse(self.user.choice_mode)

    def test_private_preference_cannot_be_changed_or_seen_by_other_account(self):
        self.client.force_authenticate(self.other)
        self.assertNotIn('choice_mode', self.client.get(f'/api/users/{self.user.pk}/').json())
        self.assertEqual(403, self.client.patch(f'/api/users/{self.user.pk}/', {'choice_mode': True}, format='json').status_code)
        self.user.refresh_from_db()
        self.assertFalse(self.user.choice_mode)

    def test_invalid_preference_and_anonymous_update_are_rejected(self):
        self.assertEqual(401, self.client.patch('/api/users/me/', {'choice_mode': True}, format='json').status_code)
        self.client.force_authenticate(self.user)
        self.assertEqual(400, self.client.patch('/api/users/me/', {'choice_mode': []}, format='json').status_code)
