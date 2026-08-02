from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    """Pagination réservée aux vues admin (aucune vue "tenant" existante n'est
    paginée — on ne change pas ce comportement pour ne rien casser côté app)."""
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100
