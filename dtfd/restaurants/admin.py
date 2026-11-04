from django.contrib import admin
from .models import Restaurant, RestaurantSource, CatalogImport


@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = ['name', 'origin', 'is_demo', 'owner']
    list_filter = ['origin', 'is_demo']
    search_fields = ['name', 'slug']
    raw_id_fields = ['owner']
    readonly_fields = ['view_count', 'average_rating', 'total_reviews']


@admin.register(RestaurantSource)
class SourceAdmin(admin.ModelAdmin):
    list_display = ['restaurant', 'provider', 'external_id', 'needs_review', 'fetched_at']
    list_filter = ['provider', 'needs_review']
    search_fields = ['restaurant__name', 'external_id']
    raw_id_fields = ['restaurant']
    readonly_fields = ['provider', 'external_id', 'url', 'attribution', 'license', 'fetched_at', 'data']

    def has_delete_permission(self, request, obj=None):
        return False  # não retirar atribuição de dados derivados ainda publicados

    def has_add_permission(self, request):
        return False


@admin.register(CatalogImport)
class ImportAdmin(admin.ModelAdmin):
    list_display = ['provider', 'region_code', 'status', 'started_at', 'finished_at']
    readonly_fields = ['provider', 'region_code', 'status', 'started_at', 'finished_at', 'counts', 'error']

    def has_add_permission(self, request):
        return False
