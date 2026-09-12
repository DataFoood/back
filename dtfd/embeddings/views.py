from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .tasks import reindex_all_task, reindex_stale


class ReindexView(APIView):
    """POST /api/embeddings/reindex/ — enfileira reindexação (admin, async).
    body: {"all": bool}  (default: só os stale)"""
    permission_classes = [IsAdminUser]

    @extend_schema(
        request=inline_serializer(
            "ReindexRequest",
            {"all": serializers.BooleanField(required=False, default=False)},
        ),
        responses=inline_serializer(
            "ReindexResponse",
            {
                "task_id": serializers.CharField(),
                "scope": serializers.CharField(),
                "status": serializers.CharField(),
            },
        ),
    )
    def post(self, request):
        if bool(request.data.get("all", False)):
            task = reindex_all_task.delay()
            scope = "todos"
        else:
            task = reindex_stale.delay()
            scope = "stale"
        return Response(
            {"task_id": task.id, "scope": scope, "status": "enfileirado"},
            status=status.HTTP_202_ACCEPTED,
        )
