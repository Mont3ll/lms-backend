import logging
import uuid # Import uuid for type hinting path params
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status, serializers
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
from apps.notifications.models import NotificationType
from apps.notifications.services import NotificationService
from apps.ai_engine.services import PersonalizationService
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

logger = logging.getLogger(__name__)


def send_assessment_submission_notification(attempt: AssessmentAttempt):
    """Send notification to the learner confirming their assessment submission."""
    try:
        content = NotificationService.generate_content_for_type(
            NotificationType.ASSESSMENT_SUBMISSION,
            {
                "user_name": attempt.user.get_full_name() or attempt.user.email,
                "assessment_title": attempt.assessment.title,
                "course_name": attempt.assessment.course.title,
            }
        )
        NotificationService.create_notification(
            user=attempt.user,
            notification_type=NotificationType.ASSESSMENT_SUBMISSION,
            subject=content["subject"],
            message=content["message"],
            action_url=f"/courses/{attempt.assessment.course.slug}/assessments/{attempt.assessment.id}/attempts/{attempt.id}",
        )
    except Exception as e:
        logger.error(f"Failed to send assessment submission notification for attempt {attempt.id}: {e}", exc_info=True)

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
        existing_in_progress = AssessmentAttempt.objects.filter(
            assessment=assessment, user=user, status=AssessmentAttempt.AttemptStatus.IN_PROGRESS
        ).first()
        if existing_in_progress:
            # Check if time has expired for this attempt
            if assessment.time_limit_minutes:
                from datetime import timedelta
                time_limit = timedelta(minutes=assessment.time_limit_minutes)
                if timezone.now() > existing_in_progress.start_time + time_limit:
                    # Auto-submit the expired attempt
                    existing_in_progress.status = AssessmentAttempt.AttemptStatus.SUBMITTED
                    existing_in_progress.end_time = existing_in_progress.start_time + time_limit
                    existing_in_progress.max_score = assessment.total_points
                    existing_in_progress.save()
                    logger.info(f"Auto-expired attempt {existing_in_progress.id} for user {user.id}")
                    # Trigger grading for the expired attempt
                    from .services import GradingService
                    GradingService.grade_attempt(existing_in_progress)
                    # Re-check attempt count before allowing new attempt
                    existing_attempts_count = AssessmentAttempt.objects.filter(assessment=assessment, user=user).count()
                    if assessment.max_attempts > 0 and existing_attempts_count >= assessment.max_attempts:
                        return Response({"detail": f"Maximum number of attempts ({assessment.max_attempts}) reached."}, status=status.HTTP_403_FORBIDDEN)
                    # Fall through to create new attempt
                else:
                    # Return existing attempt data so frontend can resume it
                    response_serializer = AssessmentAttemptStartSerializer(existing_in_progress, context={'request': request})
                    return Response({
                        "detail": "An attempt is already in progress.",
                        "existing_attempt": response_serializer.data
                    }, status=status.HTTP_409_CONFLICT)
            else:
                # No time limit - return existing attempt data so frontend can resume it
                response_serializer = AssessmentAttemptStartSerializer(existing_in_progress, context={'request': request})
                return Response({
                    "detail": "An attempt is already in progress.",
                    "existing_attempt": response_serializer.data
                }, status=status.HTTP_409_CONFLICT)

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
    summary="Resume Assessment Attempt",
    description="Retrieves details of an in-progress assessment attempt for resuming. Returns the attempt with full assessment details including questions.",
    responses={
        200: AssessmentAttemptStartSerializer,
        400: OpenApiTypes.OBJECT,  # Bad Request (e.g., attempt not in progress)
        403: OpenApiTypes.OBJECT,  # Forbidden (not owner)
        404: OpenApiTypes.OBJECT,  # Attempt not found
    }
)
class ResumeAssessmentAttemptView(APIView):
    """Retrieves an in-progress attempt for resuming, with full assessment details."""
    permission_classes = [permissions.IsAuthenticated, IsLearner]

    def get(self, request, attempt_id: uuid.UUID, format=None):
        attempt = get_object_or_404(
            AssessmentAttempt.objects.select_related('assessment', 'user'),
            pk=attempt_id
        )

        # --- Permission Check: Only allow owner to resume their own attempts ---
        if attempt.user != request.user:
            return Response(
                {"detail": "You can only resume your own attempts."},
                status=status.HTTP_403_FORBIDDEN
            )

        # --- Check if attempt is still in progress ---
        if attempt.status != AssessmentAttempt.AttemptStatus.IN_PROGRESS:
            return Response(
                {"detail": "This attempt is no longer in progress and cannot be resumed."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # --- Check if time has expired ---
        assessment = attempt.assessment
        if assessment.time_limit_minutes:
            from datetime import timedelta
            time_limit = timedelta(minutes=assessment.time_limit_minutes)
            if timezone.now() > attempt.start_time + time_limit:
                # Auto-submit the expired attempt
                attempt.status = AssessmentAttempt.AttemptStatus.SUBMITTED
                attempt.end_time = attempt.start_time + time_limit
                attempt.max_score = assessment.total_points
                attempt.save()
                logger.info(f"Auto-expired attempt {attempt.id} for user {request.user.id}")
                # Trigger grading for the expired attempt
                from .services import GradingService
                GradingService.grade_attempt(attempt)
                return Response(
                    {"detail": "This attempt has expired and has been automatically submitted."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Return attempt with full assessment details
        response_serializer = AssessmentAttemptStartSerializer(attempt, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_200_OK)


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

                # Send submission confirmation notification
                send_assessment_submission_notification(attempt)

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
        
        # Check if user is the course instructor or admin
        is_course_instructor = (
            obj.assessment.course.instructor == user 
            if obj.assessment and obj.assessment.course 
            else False
        )
        is_admin = user.is_staff
        
        if not (is_owner or is_course_instructor or is_admin):
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


@extend_schema(
    tags=['Assessment Attempts'],
    summary="Get Remedial Recommendations",
    description="Retrieves personalized content recommendations for a user based on their assessment performance. "
                "Optionally filter by a specific assessment attempt.",
    parameters=[
        OpenApiParameter(
            name='attempt_id',
            type=OpenApiTypes.UUID,
            location=OpenApiParameter.QUERY,
            description='Optional: Filter recommendations for a specific assessment attempt',
            required=False,
        ),
        OpenApiParameter(
            name='limit',
            type=OpenApiTypes.INT,
            location=OpenApiParameter.QUERY,
            description='Maximum number of recommendations to return (default: 10)',
            required=False,
        ),
    ],
    responses={
        200: OpenApiTypes.OBJECT,
        401: OpenApiTypes.OBJECT,
    }
)
class RemedialRecommendationsView(APIView):
    """
    Returns personalized remedial content recommendations based on assessment performance.
    
    Suggests content items (videos, documents, text) from courses where the user
    performed poorly on assessments. Recommendations are prioritized by severity.
    """
    permission_classes = [permissions.IsAuthenticated, IsLearner]

    def get(self, request, format=None):
        user = request.user
        attempt_id = request.query_params.get('attempt_id')
        limit = request.query_params.get('limit', 10)

        try:
            limit = int(limit)
            limit = min(max(limit, 1), 50)  # Clamp between 1 and 50
        except (ValueError, TypeError):
            limit = 10

        context = {'limit': limit}

        # If attempt_id is provided, get recommendations for that specific assessment
        if attempt_id:
            try:
                attempt = get_object_or_404(AssessmentAttempt, pk=attempt_id, user=user)
                context['assessment_id'] = str(attempt.assessment_id)
            except Exception:
                return Response(
                    {"detail": "Invalid attempt ID or attempt not found."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        recommendations = PersonalizationService.get_remedial_recommendations(user, context)

        return Response({
            'count': len(recommendations),
            'recommendations': recommendations,
        })


@extend_schema(
    tags=['Assessment Attempts'],
    summary="Check Remedial Path Availability",
    description="Checks if a remedial learning path can be generated for a failed assessment attempt. "
                "Returns eligibility status and the URL to generate the path.",
    responses={
        200: OpenApiTypes.OBJECT,
        403: OpenApiTypes.OBJECT,  # Forbidden (not owner)
        404: OpenApiTypes.OBJECT,  # Attempt not found
    }
)
class RemedialPathAvailabilityView(APIView):
    """
    Checks if a remedial learning path can be generated for an assessment attempt.
    
    Returns:
    - is_eligible: Whether the attempt qualifies for remedial path generation
    - reason: Human-readable explanation of eligibility status
    - generate_url: API endpoint to generate the remedial path (if eligible)
    - assessment_info: Basic assessment details for UI display
    """
    permission_classes = [permissions.IsAuthenticated, IsLearner]

    def get(self, request, attempt_id: uuid.UUID, format=None):
        attempt = get_object_or_404(
            AssessmentAttempt.objects.select_related('assessment', 'user', 'assessment__course'),
            pk=attempt_id
        )

        # --- Permission Check: Only allow owner to check their own attempts ---
        if attempt.user != request.user:
            return Response(
                {"detail": "You can only check remedial path availability for your own attempts."},
                status=status.HTTP_403_FORBIDDEN
            )

        assessment = attempt.assessment
        
        # Build response data
        response_data = {
            "attempt_id": str(attempt.id),
            "assessment_info": {
                "id": str(assessment.id),
                "title": assessment.title,
                "course_title": assessment.course.title if assessment.course else None,
                "pass_mark_percentage": assessment.pass_mark_percentage,
            },
            "attempt_info": {
                "status": attempt.status,
                "score": float(attempt.score) if attempt.score is not None else None,
                "max_score": float(attempt.max_score) if attempt.max_score is not None else None,
                "is_passed": attempt.is_passed,
            },
            "is_eligible": False,
            "reason": None,
            "generate_url": None,
        }

        # --- Eligibility Checks ---
        
        # Check 1: Attempt must be graded
        if attempt.status != AssessmentAttempt.AttemptStatus.GRADED:
            response_data["reason"] = "Assessment attempt has not been graded yet."
            return Response(response_data)

        # Check 2: Attempt must be failed
        if attempt.is_passed is True:
            response_data["reason"] = "Congratulations! You passed this assessment. No remedial path needed."
            return Response(response_data)

        if attempt.is_passed is None:
            response_data["reason"] = "Assessment result is pending. Please wait for grading to complete."
            return Response(response_data)

        # Check 3: Assessment must have skills to remediate (check if questions have skills)
        questions_with_skills = Question.objects.filter(
            assessment=assessment,
            skills__isnull=False
        ).exists()

        if not questions_with_skills:
            response_data["reason"] = "This assessment doesn't have skill mappings for personalized remediation."
            response_data["is_eligible"] = False
            return Response(response_data)

        # --- User is eligible for remedial path ---
        response_data["is_eligible"] = True
        response_data["reason"] = "You can generate a personalized remedial learning path to strengthen the skills covered in this assessment."
        response_data["generate_url"] = "/api/v1/personalized-paths/generate/remedial/"
        response_data["generate_payload"] = {
            "assessment_attempt_id": str(attempt.id),
        }

        return Response(response_data)


@extend_schema(
    tags=['Assessment Attempts'],
    summary="Get Skill Breakdown for Attempt",
    description="Retrieves a detailed skill-by-skill performance breakdown for a graded assessment attempt. "
                "Shows how the learner performed on each skill evaluated by the assessment.",
    responses={
        200: OpenApiTypes.OBJECT,
        400: OpenApiTypes.OBJECT,  # Not graded yet
        403: OpenApiTypes.OBJECT,  # Forbidden (not owner/admin/instructor)
        404: OpenApiTypes.OBJECT,  # Attempt not found
    }
)
class AssessmentAttemptSkillBreakdownView(APIView):
    """
    Returns a skill-by-skill breakdown of an assessment attempt's results.
    
    For each skill evaluated by the assessment, shows:
    - Number of questions correct vs total
    - Points earned vs possible
    - Accuracy percentage
    - Demonstrated proficiency level
    
    Only available for graded attempts.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, attempt_id: uuid.UUID, format=None):
        attempt = get_object_or_404(
            AssessmentAttempt.objects.select_related('assessment', 'user', 'assessment__course'),
            pk=attempt_id
        )
        user = request.user

        # --- Permission Checks ---
        is_owner = attempt.user == user
        is_course_instructor = (
            attempt.assessment.course.instructor == user
            if attempt.assessment and attempt.assessment.course
            else False
        )
        is_admin = user.is_staff

        if not (is_owner or is_course_instructor or is_admin):
            return Response(
                {"detail": "You do not have permission to view this attempt's skill breakdown."},
                status=status.HTTP_403_FORBIDDEN
            )

        # --- Check if attempt is graded ---
        if attempt.status != AssessmentAttempt.AttemptStatus.GRADED:
            return Response(
                {"detail": "Skill breakdown is only available for graded attempts."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # --- Calculate Skill Breakdown ---
        from apps.skills.signals import calculate_skill_breakdown_for_attempt

        breakdown = calculate_skill_breakdown_for_attempt(attempt)

        return Response(breakdown)


@extend_schema(
    tags=['Assessment Attempts'],
    summary="Get My Assessment Attempts",
    description="Retrieves all assessment attempts for the current user. "
                "Optionally filter by status (e.g., 'GRADED' for remedial path generation).",
    parameters=[
        OpenApiParameter(
            name='status',
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            description='Filter by attempt status: IN_PROGRESS, SUBMITTED, or GRADED',
            required=False,
            enum=['IN_PROGRESS', 'SUBMITTED', 'GRADED'],
        ),
        OpenApiParameter(
            name='limit',
            type=OpenApiTypes.INT,
            location=OpenApiParameter.QUERY,
            description='Maximum number of attempts to return (default: 50)',
            required=False,
        ),
    ],
    responses={
        200: OpenApiTypes.OBJECT,
        401: OpenApiTypes.OBJECT,
    }
)
class MyAssessmentAttemptsView(APIView):
    """
    Returns all assessment attempts for the current authenticated user.
    
    Useful for:
    - Displaying user's assessment history
    - Getting graded attempts for remedial path generation
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, format=None):
        user = request.user
        status_filter = request.query_params.get('status')
        limit = request.query_params.get('limit', 50)

        try:
            limit = int(limit)
            limit = min(max(limit, 1), 100)  # Clamp between 1 and 100
        except (ValueError, TypeError):
            limit = 50

        # Build queryset
        queryset = AssessmentAttempt.objects.filter(
            user=user
        ).select_related(
            'assessment', 'assessment__course', 'graded_by'
        ).order_by('-start_time')

        # Apply tenant filtering if applicable
        if hasattr(request, 'tenant') and request.tenant:
            queryset = queryset.filter(assessment__course__tenant=request.tenant)

        # Apply status filter if provided
        if status_filter and status_filter in ['IN_PROGRESS', 'SUBMITTED', 'GRADED']:
            queryset = queryset.filter(status=status_filter)

        # Apply limit
        attempts = queryset[:limit]

        serializer = AssessmentAttemptSerializer(attempts, many=True)
        return Response({
            'count': len(serializer.data),
            'results': serializer.data,
        })
