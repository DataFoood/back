from rest_framework import serializers

from .models import (
    SearchHistory,
    UserAmbientAffinity,
    UserCuisineAffinity,
    UserPriceAffinity,
)


class SearchHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = SearchHistory
        fields = ["id", "query", "created_at"]
        read_only_fields = fields


class CuisineAffinitySerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="cuisine.name", read_only=True)

    class Meta:
        model = UserCuisineAffinity
        fields = ["id", "cuisine", "name", "score", "is_manual"]
        read_only_fields = ["id", "cuisine", "name", "is_manual"]


class AmbientAffinitySerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="ambient.name", read_only=True)

    class Meta:
        model = UserAmbientAffinity
        fields = ["id", "ambient", "name", "score", "is_manual"]
        read_only_fields = ["id", "ambient", "name", "is_manual"]


class PriceAffinitySerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="price_range.name", read_only=True)

    class Meta:
        model = UserPriceAffinity
        fields = ["id", "price_range", "name", "score", "is_manual"]
        read_only_fields = ["id", "price_range", "name", "is_manual"]
