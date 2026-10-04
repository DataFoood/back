from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from address.models import Address
from restaurants.models import Restaurant
from users.models import User

from .models import PlatformDailyStat, RestaurantDailyStat

WINDOW_DAYS = 30


class PlatformMetricsView(APIView):
    """GET /api/analytics/platform/ — números da plataforma (admin). Só agregados."""
    permission_classes = [IsAdminUser]

    @extend_schema(
        responses=inline_serializer(
            "PlatformMetrics",
            {
                "users": serializers.DictField(child=serializers.IntegerField()),
                "restaurants": serializers.DictField(child=serializers.IntegerField()),
                "window_days": serializers.IntegerField(),
                "searches_window": serializers.IntegerField(),
                "search_failures_window": serializers.IntegerField(),
                "views_window": serializers.IntegerField(),
                "series": serializers.ListField(child=serializers.DictField()),
            },
        )
    )
    def get(self, request):
        since = timezone.localdate() - timedelta(days=WINDOW_DAYS - 1)
        users = User.objects.aggregate(
            total=Count("id"),
            customers=Count("id", filter=Q(role=User.Role.CUSTOMER)),
            owners=Count("id", filter=Q(role=User.Role.OWNER)),
            admins=Count("id", filter=Q(role=User.Role.ADMIN)),
            consented=Count("id", filter=Q(allow_info=True)),
        )
        users["removed"] = User.all_objects.filter(deleted_at__isnull=False).count()
        geocoded = Address.objects.filter(
            content_type__model="restaurant", latitude__isnull=False
        ).values("object_id").distinct()
        restaurants = Restaurant.objects.aggregate(
            total=Count("id"),
            embedding_stale=Count("id", filter=Q(embedding_stale=True)),
            without_coordinates=Count("id", filter=~Q(id__in=geocoded)),
        )
        restaurants["removed"] = Restaurant.all_objects.filter(deleted_at__isnull=False).count()

        platform = {
            row["date"]: row
            for row in PlatformDailyStat.objects.filter(date__gte=since).values("date", "searches", "search_failures")
        }
        views = dict(
            RestaurantDailyStat.objects.filter(date__gte=since)
            .values_list("date")
            .annotate(total=Sum("views"))
        )
        series = []
        for i in range(WINDOW_DAYS):
            day = since + timedelta(days=i)
            row = platform.get(day, {})
            series.append({
                "date": day.isoformat(),
                "searches": row.get("searches", 0),
                "search_failures": row.get("search_failures", 0),
                "views": views.get(day, 0),
            })
        return Response({
            "users": users,
            "restaurants": restaurants,
            "window_days": WINDOW_DAYS,
            "searches_window": sum(r["searches"] for r in series),
            "search_failures_window": sum(r["search_failures"] for r in series),
            "views_window": sum(r["views"] for r in series),
            "series": series,
        })
