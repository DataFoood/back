from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    """Paginação dos models de maior volume (users, restaurants)."""

    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 50
