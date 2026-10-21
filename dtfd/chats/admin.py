from django.contrib import admin

from .models import ChatConversation


@admin.register(ChatConversation)
class ChatConversationAdmin(admin.ModelAdmin):
    list_display = ["title", "user", "updated_at"]
    # conteúdo é da pessoa: o admin vê que existe, não lê
    exclude = ["messages"]
