from django.contrib import admin

from .models import RankingWeight


@admin.register(RankingWeight)
class RankingWeightAdmin(admin.ModelAdmin):
    list_display = ["key", "weight"]
    list_editable = ["weight"]
