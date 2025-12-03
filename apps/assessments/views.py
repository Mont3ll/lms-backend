import logging
import uuid # Import uuid for type hinting path params
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import Assessment, AssessmentAttempt, Question
from .serializers import (
    AssessmentSerializer,
    AssessmentAttemptSerializer,
    AssessmentAttemptStartSerializer,
    AssessmentAttemptSubmitSerializer,
    QuestionSerializer,
)
from apps.users.permissions import IsLearner
from apps.enrollments.services import EnrollmentService
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

logger = logging.getLogger(__name__)

@extend_schema(
    tags=['Assessment Attempts'], # Group in Swagger
    summary="Start Assessment Attempt",
    description="Initiates a new attempt for the specified assessment if the user is eligible.",
    responses={
        201: AssessmentAttemptStartSerializer, # Define successful response
        400: OpenApiTypes.OBJECT, # Bad Request (e.g., already in progress)
        403: OpenApiTypes.OBJECT, # Forbidden (e.g., not enrolled, max attempts)
        404: OpenApiTypes.OBJECT, # Assessment not found or not published
        409: OpenApiTypes.OBJECT, # Conflict (e.g., existing in-progress attempt)
    }
)
class StartAssessmentAttemptView(APIView):
    """ Starts a new attempt for an assessment if allowed. """
    permission_classes = [permissions.IsAuthenticated, IsLearner]

    def post(self, request, assessment_id: uuid.UUID, format=None): # Add type hint
        # Use get_object_or_404 more defensively
        assessment = get_object_or_404(Assessment, pk=assessment_id, is_published=True)
        user = request.user

        # --- Permission & Eligibility Checks ---
        # Check if user is enrolled in the course
        if not EnrollmentService.has_active_enrollment(user, assessment.course):
            logger.warning(f"User {user.id} attempted to start assessment {assessment.id} without active enrollment")
            return Response(
                {"detail": "You must be enrolled in this course to take this assessment."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        existing_attempts_count = AssessmentAttempt.objects.filter(assessment=assessment, user=user).count()
        if assessment.max_attempts > 0 and existing_attempts_count >= assessment.max_attempts:
            return Response({"detail": f"Maximum number of attempts ({assessment.max_attempts}) reached."}, status=status.HTTP_403_FORBIDDEN)
        if assessment.due_date and timezone.now() > assessment.due_date:
             return Response({"detail": "The due date has passed."}, status=status.HTTP_403_FORBIDDEN)
        if AssessmentAttempt.objects.filter(assessment=assessment, user=user, status=AssessmentAttempt.AttemptStatus.IN_PROGRESS).exists():
             return Response({"detail": "An attempt is already in progress."}, status=status.HTTP_409_CONFLICT)

        # --- Create New Attempt ---
        attempt = AssessmentAttempt.objects.create(assessment=assessment, user=user)
        logger.info(f"User {user.id} started attempt {attempt.id} for assessment {assessment.id}")

        # --- Prepare Response ---
        response_serializer = AssessmentAttemptStartSerializer(attempt, context={'request': request})
        # Manually add full assessment details if StartSerializer doesn't include it
        # response_data = response_serializer.data
        # assessment_detail_serializer = AssessmentSerializer(assessment)
        # response_data['assessment_details'] = assessment_detail_serializer.data # Or similar structure
        # return Response(response_data, status=status.HTTP_201_CREATED)

        # AssessmentAttemptStartSerializer now includes AssessmentSerializer
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=['Assessment Attempts'],
    summary="Submit Assessment Attempt",
    description="Submits answers for an ongoing assessment attempt.",
    request=AssessmentAttemptSubmitSerializer, # Define request body serializer
    responses={
        200: AssessmentAttemptSerializer, # Define successful response
        400: OpenApiTypes.OBJECT, # Bad Request (e.g., already submitted, invalid data)
        403: OpenApiTypes.OBJECT, # Forbidden (e.g., not owner)
        404: OpenApiTypes.OBJECT, # Attempt not found
    }
)
class SubmitAssessmentAttemptView(APIView):
    """ Submits answers for an ongoing assessment attempt. """
    permission_classes = [permissions.IsAuthenticated, IsLearner]

    def post(self, request, attempt_id: uuid.UUID, format=None): # Add type hint
        attempt = get_object_or_404(AssessmentAttempt, pk=attempt_id, user=request.user)

        if attempt.status != AssessmentAttempt.AttemptStatus.IN_PROGRESS:
            return Response({"detail": "This attempt cannot be submitted in its current state."}, status=status.HTTP_400_BAD_REQUEST)

        # --- Check Time Limit ---
        time_limit = attempt.assessment.time_limit_minutes
        force_submit = False
        if time_limit:
             duration_seconds = (timezone.now() - attempt.start_time).total_seconds()
             if duration_seconds > (time_limit * 60):
                 force_submit = True
                 logger.warning(f"Attempt {attempt.id} exceeded time limit. Force submitting.")

        serializer = AssessmentAttemptSubmitSerializer(data=request.data)
        if serializer.is_valid():
            try:
                # The save method in the serializer now handles the submit logic
                serializer.save(attempt=attempt)
                logger.info(f"User {request.user.id} submitted attempt {attempt.id}")

                # --- Prepare Response ---
                attempt.refresh_from_db()
                response_serializer = AssessmentAttemptSerializer(attempt, context={'request': request})
                response_data = response_serializer.data

                # Modify response based on settings AFTER serialization
                if not attempt.assessment.show_results_immediately and attempt.status != AssessmentAttempt.AttemptStatus.GRADED:
                    response_data.pop('score', None)
                    response_data.pop('is_passed', None)
                    response_data.pop('feedback', None)
                    # response_data.pop('answers', None) # Maybe hide submitted answers too?

                return Response(response_data, status=status.HTTP_200_OK)

            except serializers.ValidationError as e:
                 return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                 logger.error(f"Error submitting attempt {attempt.id}: {e}", exc_info=True)
                 return Response({"detail": "An unexpected error occurred during submission."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    tags=['Assessment Attempts'],
    summary="View Assessment Attempt Result",
    description="Retrieves the details and results of a specific assessment attempt.",
    responses={
        200: AssessmentAttemptSerializer,
        403: OpenApiTypes.OBJECT, # Forbidden (not owner/admin/instructor)
        404: OpenApiTypes.OBJECT, # Attempt not found
    }
)
class AssessmentAttemptResultView(generics.RetrieveAPIView):
    """ Retrieves the details and results of a specific assessment attempt. """
    queryset = AssessmentAttempt.objects.select_related(
        'assessment', 'user', 'graded_by', 'assessment__course' # Optimize query
    ).all()
    serializer_class = AssessmentAttemptSerializer
    permission_classes = [permissions.IsAuthenticated] # Object permission checked in get_object
    lookup_field = 'id'
    lookup_url_kwarg = 'id' # Explicitly define if different from lookup_field

    # Override get_object for permission checks
    def get_object(self):
        obj = super().get_object() # Fetches using queryset and lookup field
        user = self.request.user
        # --- Permission Checks ---
        is_owner = obj.user == user
        # Simplified: Allow owner or any staff user (admin/instructor assumed staff)
        # TODO: Refine with IsCourseInstructorOrAdmin check if needed
        if not (is_owner or user.is_staff):
             from rest_framework.exceptions import PermissionDenied
             raise PermissionDenied("You do not have permission to view this attempt.")
        return obj

    # Override retrieve to potentially modify serialized data based on settings
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        data = serializer.data

        # Hide results if not allowed yet (for the owner only)
        if instance.user == request.user and not request.user.is_staff:
             if not instance.assessment.show_results_immediately and instance.status != AssessmentAttempt.AttemptStatus.GRADED:
                  data.pop('score', None)
                  data.pop('is_passed', None)
                  data.pop('feedback', None)
                  # data.pop('answers', None) # Hide answers until results shown?

        return Response(data)
