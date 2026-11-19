import hashlib
import secrets

from django.conf import settings
from django.db.models.functions import Greatest
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import User
from .serializers import UserDetailSerializer


class PremiumCouponSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=80, write_only=True)


class PremiumCouponView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "premium_coupon"

    @extend_schema(request=PremiumCouponSerializer, responses=UserDetailSerializer)
    def post(self, request):
        serializer = PremiumCouponSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = settings.PREMIUM_TEST_COUPON_SHA256
        if not expected:
            return Response({"detail": "O resgate de cupom está indisponível."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        digest = hashlib.sha256(serializer.validated_data["code"].encode()).hexdigest()
        if not secrets.compare_digest(digest, expected):
            return Response({"code": "Cupom inválido."}, status=status.HTTP_400_BAD_REQUEST)
        # Sem cota de resgates; repetir não altera consentimento nem permissões.
        User.objects.filter(pk=request.user.pk).update(level=Greatest("level", 2))
        request.user.refresh_from_db()
        return Response(UserDetailSerializer(request.user).data)
