from unittest.mock import patch

import httpx
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase

from address.models import Address
from preferences.models import UserCuisineAffinity, SearchHistory
from restaurants.models import Restaurant, Cuisine, Ambient, RestaurantItem
from users.models import User
from .models import ChatConversation


@override_settings(CONVERSATION_MODEL='')
class ConversationTest(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email='conversation@test.example', name='Ana', password='Testpass1234')
        self.other = User.objects.create_user(email='other@test.example', name='Outra', password='Testpass1234')
        self.client.force_authenticate(self.user)
        self.pizza = Cuisine.objects.get(name='Pizza & Massas')
        self.sushi = Cuisine.objects.get(name='Japonesa')
        self.romantic = Ambient.objects.get(name='Romântico')
        self.places = []
        for i in range(5):
            restaurant = Restaurant.objects.create(name=f'Pizza {i}', slug=f'pizza-{i}', has_delivery=i < 2)
            restaurant.cuisines.add(self.pizza)
            Address.objects.create(content_type=ContentType.objects.get_for_model(Restaurant), object_id=restaurant.pk, street='Rua Teste', city='Marília', state='SP', zipcode='')
            self.places.append(restaurant)
        self.places[0].ambients.add(self.romantic)
        self.japanese = Restaurant.objects.create(name='Sushi', slug='sushi')
        self.japanese.cuisines.add(self.sushi)

    def turn(self, text, pk=None):
        response = self.client.post('/api/chats/respond/', {'query': text, 'conversation_id': pk}, format='json')
        self.assertEqual(200, response.status_code, response.data)
        return response.json()

    def test_grounded_preview_and_deferred_selection(self):
        chat = self.turn('Quero pizza em Marília')
        content = chat['messages'][-1]['content']
        self.assertEqual(5, content['count'])
        self.assertEqual(3, len(content['results']))
        self.assertIn('Pizza', content['answer'])
        self.assertEqual(5, len(self.client.get(f"/api/chats/{chat['id']}/recommendations/1/").json()['results']))

    def test_refinement_and_surprise_preserve_request(self):
        chat = self.turn('Quero pizza em Marília')
        chat = self.turn('Com delivery', chat['id'])
        chat = self.turn('Me surpreenda', chat['id'])
        content = chat['messages'][-1]['content']
        self.assertEqual(2, content['count'])
        self.assertEqual(self.pizza.pk, content['filters']['cuisine'])
        self.assertEqual('Marília', content['filters']['city'])
        self.assertTrue(content['filters']['delivery'])
        self.assertIn('Mantive', content['answer'])

    def test_new_cuisine_replaces_previous_and_negative_excludes(self):
        chat = self.turn('Quero pizza')
        chat = self.turn('Prefiro sushi', chat['id'])
        self.assertEqual([self.japanese.pk], chat['messages'][-1]['content']['recommendation_ids'])
        chat = self.turn('Não quero sushi', chat['id'])
        self.assertNotIn(self.japanese.pk, chat['messages'][-1]['content']['recommendation_ids'])

    def test_empty_and_unknown_city_are_honest(self):
        chat = self.turn('Quero pizza em Curitiba')
        content = chat['messages'][-1]['content']
        self.assertEqual(0, content['count'])
        self.assertIn('Curitiba', content['answer'])
        self.assertEqual([], content['results'])

    def test_budget_needs_actual_menu_price(self):
        RestaurantItem.objects.create(restaurant=self.places[0], name='Pizza pequena', price='25.00')
        chat = self.turn('Quero pizza até R$ 30')
        self.assertEqual([self.places[0].pk], chat['messages'][-1]['content']['recommendation_ids'])

    def test_preferences_cannot_override_explicit_request(self):
        self.user.level, self.user.allow_info = 2, True
        self.user.save()
        UserCuisineAffinity.objects.create(user=self.user, cuisine=self.sushi, score=1)
        chat = self.turn('Quero pizza')
        self.assertNotIn(self.japanese.pk, chat['messages'][-1]['content']['recommendation_ids'])

    def test_favorites_help_pro_even_before_affinity_recompute(self):
        from restaurants.models import RestaurantFavorite
        self.user.level, self.user.allow_info = 2, True
        self.user.save()
        RestaurantFavorite.objects.create(user=self.user, restaurant=self.japanese)
        chat = self.turn('Sugira algo pelos meus gostos')
        content = chat['messages'][-1]['content']
        self.assertTrue(content['personalized'])
        self.assertEqual(self.japanese.pk, content['recommendation_ids'][0])

    def test_invalid_legacy_filters_are_not_trusted(self):
        chat = ChatConversation.objects.create(user=self.user, title='Legada', messages=[
            {'role': 'assistant', 'content': {'filters': {'city': [], 'excluded_cuisines': 1, 'cuisine': True}}},
        ])
        updated = self.turn('Não quero sushi', chat.pk)
        self.assertNotIn(self.japanese.pk, updated['messages'][-1]['content']['recommendation_ids'])

    def test_occasion_is_not_invented_as_a_city(self):
        content = self.turn('Quero comer em um lugar romântico')['messages'][-1]['content']
        self.assertNotIn('city', content['filters'])
        self.assertEqual([self.places[0].pk], content['recommendation_ids'])

    def test_surprise_handles_malformed_legacy_selection(self):
        chat = ChatConversation.objects.create(user=self.user, title='Legada', messages=[
            {'role': 'assistant', 'content': {'recommendation_ids': [{}], 'results': 1}},
        ])
        content = self.turn('Me surpreenda', chat.pk)['messages'][-1]['content']
        self.assertGreater(content['count'], 0)

    def test_concurrent_turn_is_not_overwritten(self):
        from .services import respond
        chat = ChatConversation.objects.create(user=self.user, title='Duas abas', messages=[])
        other_messages = [{'role': 'user', 'text': 'Outra aba'}]
        def while_generating(*args):
            result = respond(*args)
            chat.messages = other_messages
            chat.save()
            return result
        with patch('chats.services.respond', side_effect=while_generating):
            response = self.client.post('/api/chats/respond/', {'query': 'pizza', 'conversation_id': chat.pk}, format='json')
        self.assertEqual(409, response.status_code)
        chat.refresh_from_db()
        self.assertEqual(other_messages, chat.messages)

    def test_pro_uses_preferences_only_with_consent(self):
        self.user.level = 2
        self.user.save()
        UserCuisineAffinity.objects.create(user=self.user, cuisine=self.sushi, score=1)
        chat = self.turn('Sugira algo pelos meus gostos')
        self.assertFalse(chat['messages'][-1]['content']['personalized'])
        self.assertEqual(0, SearchHistory.objects.filter(user=self.user).count())
        self.user.allow_info = True
        self.user.save()
        chat = self.turn('Sugira algo pelos meus gostos')
        content = chat['messages'][-1]['content']
        self.assertTrue(content['personalized'])
        self.assertEqual(self.japanese.pk, content['recommendation_ids'][0])

    def test_conversation_and_selection_are_private(self):
        chat = ChatConversation.objects.create(user=self.other, title='Privada', messages=[])
        self.assertEqual(404, self.client.post('/api/chats/respond/', {'query': 'pizza', 'conversation_id': chat.pk}, format='json').status_code)
        self.assertEqual(404, self.client.get(f'/api/chats/{chat.pk}/recommendations/0/').status_code)

    def test_invalid_and_oversized_turns(self):
        for query in ('', 'x' * 501, None):
            self.assertEqual(400, self.client.post('/api/chats/respond/', {'query': query}, format='json').status_code)
        chat = ChatConversation.objects.create(user=self.user, title='Cheia', messages=[{'role': 'user', 'text': 'pizza'}] * 200)
        self.assertEqual(400, self.client.post('/api/chats/respond/', {'query': 'pizza', 'conversation_id': chat.pk}, format='json').status_code)

    def test_removed_restaurant_disappears_from_selection(self):
        from django.utils import timezone
        chat = self.turn('Quero pizza')
        self.places[0].deleted_at = timezone.now()
        self.places[0].save()
        selection = self.client.get(f"/api/chats/{chat['id']}/recommendations/1/").json()['results']
        self.assertNotIn(self.places[0].pk, [r['id'] for r in selection])

    @override_settings(CONVERSATION_MODEL='test-model')
    @patch('chats.services.httpx.post', side_effect=httpx.ConnectError('offline'))
    def test_ollama_failure_still_returns_useful_catalog(self, remote):
        chat = self.turn('Onde podemos jantar hoje?')
        self.assertGreater(chat['messages'][-1]['content']['count'], 0)
        remote.assert_called_once()

    @override_settings(CHAT_GENERATION_ENABLED=True, CHAT_MODEL='test-model')
    @patch('restaurants.generation.httpx.post', side_effect=httpx.ConnectError('offline'))
    def test_writing_failure_keeps_grounded_results(self, remote):
        chat = self.turn('Quero pizza em Marília')
        content = chat['messages'][-1]['content']
        self.assertEqual(5, content['count'])
        self.assertIn('Pizza', content['answer'])
        self.assertNotIn('Qual cidade', content['answer'])
        remote.assert_called_once()

    @override_settings(CHAT_GENERATION_ENABLED=True)
    @patch('restaurants.generation.generate_answer', return_value='Conheça um lugar totalmente inventado.')
    def test_unknown_restaurant_in_generated_text_uses_fallback(self, writer):
        content = self.turn('Quero pizza')['messages'][-1]['content']
        self.assertNotIn('inventado', content['answer'])
        self.assertEqual(5, content['count'])
