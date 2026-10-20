from django.contrib import admin

from .models import MessagingPreference, Promotion, PromotionDelivery


@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = ["title", "restaurant", "status", "scheduled_for", "sent_at"]
    list_filter = ["status"]
    search_fields = ["title", "restaurant__name"]


@admin.register(PromotionDelivery)
class PromotionDeliveryAdmin(admin.ModelAdmin):
    list_display = ["promotion", "user", "channel", "status", "sent_at"]
    list_filter = ["channel", "status"]


@admin.register(MessagingPreference)
class MessagingPreferenceAdmin(admin.ModelAdmin):
    list_display = ["user", "promotions_opt_in", "channel_email", "channel_telegram", "telegram_linked_at"]
    exclude = ["telegram_link_token"]
