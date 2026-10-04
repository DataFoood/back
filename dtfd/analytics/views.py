from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from address.models import Address
from restaurants.models import Restaurant
from users.models import User

from .insights import METRICS, restaurant_insights
from .models import AccessStat, PlatformDailyStat

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
            AccessStat.objects.filter(date__gte=since, event__in=METRICS["views"])
            .values_list("date")
            .annotate(total=Sum("count"))
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


class RestaurantInsightsView(APIView):
    """GET /api/analytics/restaurants/<pk>/ — BI do dono (dono ou admin).
    ?days=7|30|90  ?metric=views|impressions|clicks  ?age=40-59,60+
    ?hour_from=0..23&hour_to=0..23 (from > to cruza a meia-noite).
    Só agregados; grupos com 1-4 acessos saem como null."""
    permission_classes = [IsAuthenticated]
    DAYS = (7, 30, 90)

    @extend_schema(
        parameters=[
            OpenApiParameter("days", int, enum=list(DAYS)),
            OpenApiParameter("metric", str, enum=list(METRICS)),
            OpenApiParameter("age", str, description="faixas separadas por vírgula: " + ", ".join(AccessStat.Age.values)),
            OpenApiParameter("hour_from", int),
            OpenApiParameter("hour_to", int),
        ],
        responses=inline_serializer(
            "RestaurantInsights",
            {
                "k": serializers.IntegerField(),
                "window": serializers.DictField(),
                "filters": serializers.DictField(),
                "totals": serializers.DictField(),
                "by_hour": serializers.ListField(child=serializers.DictField()),
                "by_day": serializers.ListField(child=serializers.DictField()),
                "by_age": serializers.ListField(child=serializers.DictField()),
                "cells": serializers.ListField(child=serializers.DictField()),
                "regions": serializers.ListField(child=serializers.DictField()),
                "coverage": serializers.DictField(),
            },
        ),
    )
    def get(self, request, pk):
        restaurant = get_object_or_404(Restaurant, pk=pk)
        if restaurant.owner_id != request.user.pk and not request.user.is_staff:
            return Response({"detail": "Proibido."}, status=status.HTTP_403_FORBIDDEN)
        p = request.query_params
        try:
            days = int(p.get("days", 30))
            hour_from, hour_to = int(p.get("hour_from", 0)), int(p.get("hour_to", 23))
        except ValueError:
            return Response({"detail": "days, hour_from e hour_to devem ser inteiros."}, status=status.HTTP_400_BAD_REQUEST)
        metric = p.get("metric", "views")
        ages = [a for a in (p.get("age") or "").split(",") if a]
        errors = {}
        if days not in self.DAYS:
            errors["days"] = f"Um de {list(self.DAYS)}."
        if metric not in METRICS:
            errors["metric"] = f"Um de {list(METRICS)}."
        if any(a not in AccessStat.Age.values for a in ages):
            errors["age"] = f"Faixas válidas: {AccessStat.Age.values}."
        if not (0 <= hour_from <= 23 and 0 <= hour_to <= 23):
            errors["hour"] = "Horas entre 0 e 23."
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        return Response(restaurant_insights(
            restaurant, days=days, metric=metric, ages=ages, hour_from=hour_from, hour_to=hour_to,
        ))
