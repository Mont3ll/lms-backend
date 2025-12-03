from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20  # Default page size
    page_size_query_param = "page_size"  # Allow client to override page size
    max_page_size = 100  # Maximum page size allowed

    def get_paginated_response(self, data):
        return Response(
            {
                "count": self.page.paginator.count,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "current_page": self.page.number,
                "total_pages": self.page.paginator.num_pages,
                "page_size": self.get_page_size(self.request),
                "results": data,
            }
        )


class SmallResultsSetPagination(StandardResultsSetPagination):
    page_size = 10
