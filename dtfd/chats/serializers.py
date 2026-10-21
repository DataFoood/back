import json

from rest_framework import serializers

from .models import ChatConversation

MAX_MESSAGES = 200
MAX_BYTES = 256 * 1024  # resultados trazem os cards; limite contra abuso


class ChatSummarySerializer(serializers.ModelSerializer):
    """Item da lista lateral: sem as mensagens."""

    class Meta:
        model = ChatConversation
        fields = ["id", "title", "created_at", "updated_at"]
        read_only_fields = fields


class ChatConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatConversation
        fields = ["id", "title", "messages", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Informe um título.")
        return value

    def validate_messages(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Deve ser uma lista.")
        if len(value) > MAX_MESSAGES:
            raise serializers.ValidationError(f"Máximo de {MAX_MESSAGES} mensagens por conversa.")
        for message in value:
            if not isinstance(message, dict) or message.get("role") not in ("user", "assistant"):
                raise serializers.ValidationError("Cada mensagem precisa de role 'user' ou 'assistant'.")
        if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_BYTES:
            raise serializers.ValidationError("Conversa grande demais. Comece uma nova.")
        return value
