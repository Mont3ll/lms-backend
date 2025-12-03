from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from django.shortcuts import get_object_or_404
from apps.courses.models import Course
from .models import Enrollment
from drf_spectacular.utils import extend_schema


class EnrollmentStatusView(APIView):
    """
    Check enrollment status for a specific course.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: {
            "type": "object",
            "properties": {
                "is_enrolled": {"type": "boolean"},
                "enrollment_id": {"type": "string", "nullable": True},
                "status": {"type": "string", "nullable": True}
            }
        }}
    )
    def get(self, request, course_slug):
        """Get enrollment status for the current user and specified course."""
        try:
            course = get_object_or_404(Course, slug=course_slug)
            
            try:
                enrollment = Enrollment.objects.get(
                    course=course,
                    user=request.user,
                    status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
                )
                return Response({
                    "is_enrolled": True,
                    "enrollment_id": str(enrollment.id),
                    "status": enrollment.status
                })
            except Enrollment.DoesNotExist:
                return Response({
                    "is_enrolled": False,
                    "enrollment_id": None,
                    "status": None
                })
        except Exception as e:
            return Response(
                {"error": "Failed to check enrollment status"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
