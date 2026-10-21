from django.conf import settings
from django.db import models


class ChatConversation(models.Model):
    """Conversa da busca semântica (chat do front), guardada na conta: segue
    a pessoa entre navegadores e é apagada de verdade (sem soft delete) quando
    ela a exclui ou encerra a conta."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_conversations"
    )
    title = models.CharField(max_length=120)
    # [{role: "user"|"assistant", text?, content?}] — formato do front
    messages = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [models.Index(fields=["user", "-updated_at"])]

    def __str__(self):
        return self.title
