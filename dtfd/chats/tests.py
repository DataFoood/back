from rest_framework import status
from rest_framework.test import APITestCase

from users.models import User

from .models import ChatConversation
from .views import KEEP

URL = "/api/chats/"
MESSAGES = [{"role": "user", "text": "pizza"}, {"role": "assistant", "content": {"kind": "results", "results": []}}]


class ChatConversationTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="c@dtfd.com", password="SenhaForte123", name="C")
        self.other = User.objects.create_user(email="o@dtfd.com", password="SenhaForte123", name="O")
        self.client.force_authenticate(self.user)

    def test_create_list_detail(self):
        created = self.client.post(URL, {"title": "pizza", "messages": MESSAGES}, format="json")
        self.assertEqual(status.HTTP_201_CREATED, created.status_code)
        listing = self.client.get(URL).json()
        self.assertEqual(1, listing["count"])
        self.assertNotIn("messages", listing["results"][0], "lista lateral sem mensagens")
        detail = self.client.get(f"{URL}{created.json()['id']}/").json()
        self.assertEqual(MESSAGES, detail["messages"])

    def test_patch_appends(self):
        chat = ChatConversation.objects.create(user=self.user, title="pizza", messages=MESSAGES[:1])
        response = self.client.patch(f"{URL}{chat.pk}/", {"messages": MESSAGES}, format="json")
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        chat.refresh_from_db()
        self.assertEqual(2, len(chat.messages))

    def test_others_conversations_are_404(self):
        chat = ChatConversation.objects.create(user=self.other, title="segredo", messages=[])
        self.assertEqual(status.HTTP_404_NOT_FOUND, self.client.get(f"{URL}{chat.pk}/").status_code)
        self.assertEqual(status.HTTP_404_NOT_FOUND, self.client.delete(f"{URL}{chat.pk}/").status_code)
        self.assertEqual(0, self.client.get(URL).json()["count"])

    def test_delete_is_hard(self):
        chat = ChatConversation.objects.create(user=self.user, title="pizza", messages=[])
        self.assertEqual(status.HTTP_204_NO_CONTENT, self.client.delete(f"{URL}{chat.pk}/").status_code)
        self.assertFalse(ChatConversation.objects.filter(pk=chat.pk).exists())

    def test_search_by_title(self):
        ChatConversation.objects.create(user=self.user, title="feijoada no centro", messages=[])
        ChatConversation.objects.create(user=self.user, title="sushi", messages=[])
        titles = [c["title"] for c in self.client.get(URL, {"q": "FEIJ"}).json()["results"]]
        self.assertEqual(["feijoada no centro"], titles)

    def test_invalid_messages(self):
        for messages in ("texto", [{"role": "hacker"}], [1]):
            response = self.client.post(URL, {"title": "x", "messages": messages}, format="json")
            self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code, messages)

    def test_oversized_rejected(self):
        big = [{"role": "user", "text": "x" * 300_000}]
        response = self.client.post(URL, {"title": "x", "messages": big}, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_keeps_latest(self):
        ChatConversation.objects.bulk_create(
            ChatConversation(user=self.user, title=f"c{i}", messages=[]) for i in range(KEEP)
        )
        self.client.post(URL, {"title": "nova", "messages": []}, format="json")
        self.assertEqual(KEEP, ChatConversation.objects.filter(user=self.user).count())
        self.assertTrue(ChatConversation.objects.filter(user=self.user, title="nova").exists())

    def test_unauthenticated(self):
        self.client.force_authenticate(None)
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, self.client.get(URL).status_code)


class DefaultPaginationTest(APITestCase):
    """Toda listagem responde no mesmo formato paginado."""

    def test_every_list_is_paginated(self):
        from restaurants.models import Restaurant

        owner = User.objects.create_superuser(email="adm@dtfd.com", password="SenhaForte123", name="Adm")
        restaurant = Restaurant.objects.create(owner=owner, name="Cantina", slug="cantina")
        self.client.force_authenticate(owner)
        urls = [
            "/api/users/", "/api/users/removed/", "/api/restaurants/", "/api/restaurants/mine/",
            "/api/restaurants/favorites/", "/api/addresses/", "/api/preferences/searches/", URL,
            *(f"/api/restaurants/{restaurant.pk}/{child}/" for child in ("items", "reviews", "images", "hours")),
            f"/api/restaurants/{restaurant.pk}/promotions/", f"/api/restaurants/{restaurant.pk}/promotions/active/",
        ]
        for url in urls:
            with self.subTest(url=url):
                body = self.client.get(url, {"page_size": 2}).json()
                self.assertEqual({"count", "next", "previous", "results"}, set(body))
