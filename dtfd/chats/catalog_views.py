import json

from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from restaurants.serializers import RestaurantCardSerializer

from .models import ChatConversation
from .serializers import ChatConversationSerializer, MAX_BYTES, MAX_MESSAGES
from .views import KEEP


class TurnSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=500, trim_whitespace=True)
    conversation_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class ChatRespondView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'search'

    @extend_schema(request=TurnSerializer, responses=ChatConversationSerializer)
    def post(self, request):
        from .services import respond

        serializer = TurnSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        query = serializer.validated_data['query']
        pk = serializer.validated_data.get('conversation_id')
        if pk:
            chat = get_object_or_404(ChatConversation, pk=pk, user=request.user)
        else:
            chat = ChatConversation(user=request.user, title=query[:120], messages=[])
        if len(chat.messages) > MAX_MESSAGES - 2:
            raise ValidationError({'query': 'Esta conversa chegou ao limite. Comece uma nova busca.'})
        content = respond(request.user, query, chat.messages, request)
        messages = [*chat.messages, {'role': 'user', 'text': query}, {'role': 'assistant', 'content': content}]
        if len(json.dumps(messages, ensure_ascii=False).encode()) > MAX_BYTES:
            raise ValidationError({'query': 'Esta conversa chegou ao limite de tamanho. Comece uma nova busca.'})
        # A inferência não segura uma transação aberta. Ao anexar o turno,
        # detectamos uma edição concorrente para não perder a outra resposta.
        with transaction.atomic():
            if pk:
                current = get_object_or_404(ChatConversation.objects.select_for_update(), pk=pk, user=request.user)
                if current.updated_at != chat.updated_at:
                    return Response({'detail': 'A conversa mudou em outra aba. Reabra a conversa antes de continuar.'}, status=409)
                chat = current
            chat.messages = messages
            chat.save()
            keep = list(ChatConversation.objects.filter(user=request.user).values_list('pk', flat=True)[:KEEP])
            ChatConversation.objects.filter(user=request.user).exclude(pk__in=keep).delete()
            if request.user.allow_info:
                from preferences.models import SearchHistory
                SearchHistory.objects.create(user=request.user, query=query)
                keep_searches = list(SearchHistory.objects.filter(user=request.user).values_list('pk', flat=True)[:50])
                SearchHistory.objects.filter(user=request.user).exclude(pk__in=keep_searches).delete()
        return Response(ChatConversationSerializer(chat).data)


class ChatRecommendationsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=inline_serializer('ChatRecommendations', {'results': RestaurantCardSerializer(many=True)}))
    def get(self, request, pk, message_index):
        from restaurants.serializers import CARD_PREFETCH, RestaurantCardSerializer
        from restaurants.views import public_catalog

        chat = get_object_or_404(ChatConversation, pk=pk, user=request.user)
        if message_index >= len(chat.messages):
            raise ValidationError({'message_index': 'Mensagem não encontrada.'})
        message = chat.messages[message_index]
        content = message.get('content', {})
        if message.get('role') != 'assistant' or not isinstance(content, dict):
            raise ValidationError({'message_index': 'Esta mensagem não contém recomendações.'})
        ids = content.get('recommendation_ids', [])
        if not ids and isinstance(content.get('results'), list):
            ids = [row['restaurant']['id'] for row in content['results'] if isinstance(row, dict) and isinstance(row.get('restaurant'), dict) and 'id' in row['restaurant']]
        if not isinstance(ids, list):
            ids = []
        ids = list(dict.fromkeys(pk for pk in ids if type(pk) is int))[:50]
        by_id = {r.pk: r for r in public_catalog().filter(pk__in=ids).prefetch_related(*CARD_PREFETCH)}
        favorites = set(request.user.favorites.filter(restaurant_id__in=ids).values_list('restaurant_id', flat=True))
        cards = RestaurantCardSerializer([by_id[pk] for pk in ids if pk in by_id], many=True,
                                        context={'request': request, 'favorited_ids': favorites}).data
        return Response({'count': len(cards), 'results': cards})
