from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated

from .models import ChatConversation
from .serializers import ChatConversationSerializer, ChatSummarySerializer

# conversas mantidas por conta; as mais antigas saem ao criar uma nova
KEEP = 50


class ChatListCreateView(ListCreateAPIView):
    """GET /api/chats/?q= — conversas do usuário (paginado, sem mensagens).
    POST — cria {title, messages}."""
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        return ChatConversationSerializer if self.request.method == "POST" else ChatSummarySerializer

    def get_queryset(self):
        qs = ChatConversation.objects.filter(user=self.request.user)
        q = (self.request.query_params.get("q") or "").strip()
        return qs.filter(title__icontains=q) if q else qs

    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(user=user)
        keep = ChatConversation.objects.filter(user=user).values_list("id", flat=True)[:KEEP]
        ChatConversation.objects.filter(user=user).exclude(id__in=list(keep)).delete()


class ChatDetailView(RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/chats/<id>/ — só a própria conversa (404 nas
    dos outros). DELETE apaga de verdade."""
    permission_classes = [IsAuthenticated]
    serializer_class = ChatConversationSerializer
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return ChatConversation.objects.filter(user=self.request.user)
