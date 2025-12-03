from rest_framework import status
from rest_framework.exceptions import APIException


class ServiceUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Service temporarily unavailable, try again later."
    default_code = "service_unavailable"


class PermissionDenied(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "You do not have permission to perform this action."
    default_code = "permission_denied"


class InvalidInput(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Invalid input provided."
    default_code = "invalid_input"


# Add other custom exceptions as needed
