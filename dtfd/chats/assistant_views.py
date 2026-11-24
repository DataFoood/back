from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from preferences.services import record_search
from restaurants.serializers import CARD_PREFETCH, RestaurantCardSerializer
from restaurants.views import favorited_ids, public_catalog
from .models import ChatConversation
from .recommendations import (
    MAX_RECOMMENDATIONS, AssistantTurn, SelectionFilters, compose_reply, conversation_guidance,
    interpret_turn, personal_context, personal_discovery, select_restaurants, selection_reply, taxonomy_choices,
)
from .serializers import ChatConversationSerializer
from .views import KEEP


class ChatTurnSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=500)
    conversation_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class ChatRespondView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "search"

    @extend_schema(request=ChatTurnSerializer, responses=ChatConversationSerializer)
    def post(self, request):
        incoming = ChatTurnSerializer(data=request.data)
        incoming.is_valid(raise_exception=True)
        conversation_id = incoming.validated_data.get("conversation_id")
        chat = get_object_or_404(ChatConversation, pk=conversation_id, user=request.user) if conversation_id else None
        if not settings.CHAT_GENERATION_ENABLED:
            return Response({"detail": "O assistente de conversa está indisponível neste momento."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        query = incoming.validated_data["query"]
        messages = chat.messages if chat else []
        previous = {}
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == "assistant" and isinstance(message.get("content"), dict):
                previous = message["content"]
                break
        try:
            filters = SelectionFilters.model_validate(previous.get("filters", {})).model_dump(exclude_unset=True)
        except ValueError:
            filters = {}
        profile = personal_context(request.user)
        choices = taxonomy_choices()
        turn = interpret_turn(query, filters, choices)
        if personal_discovery(query):
            if request.user.level < 2:
                reply = "A escolha pelos seus gostos faz parte do Premium. Posso ajudar agora: qual cozinha ou cidade você prefere?"
            elif not request.user.allow_info:
                reply = "Para usar seus gostos, autorize a personalização no perfil. Se preferir, me diga uma cozinha ou cidade e seguimos por aqui."
            elif not profile:
                reply = "Ainda não conheço seus gostos. Para começar, salve alguns restaurantes ou ajuste suas preferências no perfil. O que você gosta de comer?"
            else:
                reply = "Vou considerar seus gostos sem limitar as opções. Você pode me contar mais sobre o que procura hoje."
            turn = AssistantTurn(reply=reply, ready=bool(profile), filters={})
        if turn is None:
            reply = "Não consegui interpretar esse pedido agora. Pode reformular ou tentar novamente em instantes?"
            ready = bool(previous.get("recommendation_ids"))
        else:
            filters.update(turn.filters.model_dump(exclude_none=True))
            for key in turn.remove_filters:
                filters.pop(key, None)
            reply, ready = turn.reply.strip(), turn.ready
        ids, limited = select_restaurants(filters, profile) if ready else ([], False)
        if ready and not ids:
            reply = selection_reply(query, filters, 0)
        elif turn is not None and ready:
            written = compose_reply(query, messages, filters, choices, profile, ids)
            reply = written or f"Não consegui escrever a sugestão agora. {selection_reply(query, filters, len(ids))}"
        content = {"kind": "results", "answer": reply, "results": [], "filters": filters,
                   "recommendation_ids": ids, "count": len(ids), "limited": limited,
                   "plan": "premium" if request.user.level >= 2 else "free", "personalized": bool(profile)}
        content.update(conversation_guidance(filters, choices, profile, ids, ready))
        # O modelo roda antes da transação; a trava só protege a anexação das mensagens.
        with transaction.atomic():
            if chat:
                current = get_object_or_404(ChatConversation.objects.select_for_update(), pk=chat.pk, user=request.user)
                if current.updated_at != chat.updated_at:
                    return Response({"detail": "A conversa mudou em outra aba. Reabra a conversa antes de continuar."}, status=status.HTTP_409_CONFLICT)
                chat = current
            values = {"messages": [*(chat.messages if chat else []),
                                   {"role": "user", "text": query}, {"role": "assistant", "content": content}]}
            if chat is None:
                values["title"] = query[:120]
            saved = ChatConversationSerializer(chat, data=values, partial=chat is not None)
            saved.is_valid(raise_exception=True)
            chat = saved.save(user=request.user)
            if turn is not None and ready:
                record_search(request.user, query)
            keep = ChatConversation.objects.filter(user=request.user).values_list("id", flat=True)[:KEEP]
            ChatConversation.objects.filter(user=request.user).exclude(id__in=list(keep)).delete()
        return Response(ChatConversationSerializer(chat).data)


class ChatRecommendationsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=inline_serializer("ChatRecommendations", {
        "count": serializers.IntegerField(), "results": RestaurantCardSerializer(many=True),
    }))
    def get(self, request, pk, message_index):
        chat = get_object_or_404(ChatConversation, pk=pk, user=request.user)
        message = chat.messages[message_index] if message_index < len(chat.messages) else {}
        content = message.get("content") if isinstance(message, dict) and message.get("role") == "assistant" else None
        ids = content.get("recommendation_ids") if isinstance(content, dict) else None
        if not isinstance(ids, list) or len(ids) > MAX_RECOMMENDATIONS or any(isinstance(pk, bool) or not isinstance(pk, int) or pk <= 0 for pk in ids):
            return Response({"detail": "Seleção não encontrada nesta mensagem."}, status=status.HTTP_404_NOT_FOUND)
        ids = list(dict.fromkeys(ids))
        restaurants = list(public_catalog().filter(pk__in=ids).prefetch_related(*CARD_PREFETCH))
        by_id = {restaurant.pk: restaurant for restaurant in restaurants}
        context = {"request": request, "favorited_ids": favorited_ids(request, restaurants)}
        cards = RestaurantCardSerializer([by_id[pk] for pk in ids if pk in by_id], many=True, context=context).data
        return Response({"count": len(cards), "results": cards})
