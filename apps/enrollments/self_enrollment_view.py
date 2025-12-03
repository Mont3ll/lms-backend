from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.db import IntegrityError
from apps.courses.models import Course
from .models import Enrollment
from .serializers import EnrollmentSerializer
from .services import EnrollmentService, EnrollmentError
from drf_spectacular.utils import extend_schema
import logging

logger = logging.getLogger(__name__)


class SelfEnrollmentView(APIView):
    """
    Allow users to enroll themselves in a course.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request={
            "type": "object",
            "properties": {
                "course_slug": {"type": "string", "description": "Course slug"}
            },
            "required": ["course_slug"]
        },
        responses={
            201: EnrollmentSerializer,
            200: EnrollmentSerializer,
            400: {"type": "object"},
            403: {"type": "object"},
            404: {"type": "object"}
        }
    )
    def post(self, request):
        """Self-enroll the current user in a course."""
        course_slug = request.data.get('course_slug')
        
        if not course_slug:
            return Response(
                {"error": "course_slug is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Get the course
            course = get_object_or_404(Course, slug=course_slug, status=Course.Status.PUBLISHED)
            
            # Check if course allows self-enrollment (for now, allow all published courses)
            # In the future, you might want to add a field to Course model for this
            
            # Check if already enrolled
            try:
                existing_enrollment = Enrollment.objects.get(
                    course=course,
                    user=request.user,
                    status=Enrollment.Status.ACTIVE
                )
                # Already enrolled, return existing enrollment
                serializer = EnrollmentSerializer(existing_enrollment)
                return Response(serializer.data, status=status.HTTP_200_OK)
            except Enrollment.DoesNotExist:
                pass  # Continue to create new enrollment
            
            # Create enrollment using the service
            try:
                enrollment, created = EnrollmentService.enroll_user(
                    user=request.user,
                    course=course,
                    status=Enrollment.Status.ACTIVE
                )
                
                serializer = EnrollmentSerializer(enrollment)
                response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
                return Response(serializer.data, status=response_status)
                
            except EnrollmentError as e:
                return Response(
                    {"error": str(e)},
                    status=status.HTTP_400_BAD_REQUEST
                )
            except Exception as e:
                logger.error(f"Error during self-enrollment: {e}")
                return Response(
                    {"error": "An error occurred during enrollment"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Course.DoesNotExist:
            return Response(
                {"error": "Course not found or not available for enrollment"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Unexpected error in self-enrollment: {e}")
            return Response(
                {"error": "An unexpected error occurred"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
