from rest_framework import viewsets, permissions, serializers, status  # Added serializers import
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.db import models
from django.utils import timezone
import logging
from .models import Assessment, Question, AssessmentAttempt
from .serializers import (
    AssessmentSerializer,
    QuestionSerializer,
    AssessmentAttemptSerializer,
    ManualGradeSerializer,
)
from apps.users.permissions import IsAdminOrTenantAdmin, IsInstructorOrAdmin
from apps.users.models import User
from apps.courses.permissions import IsCourseInstructorOrAdmin
from apps.courses.models import Course
from apps.enrollments.models import Enrollment
from apps.notifications.models import NotificationType
from apps.notifications.services import NotificationService
from drf_spectacular.utils import extend_schema, extend_schema_view

logger = logging.getLogger(__name__)

@extend_schema(tags=['Assessments'])
class AssessmentViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Assessments (CRUD).
    Typically accessed by Instructors or Admins.
    """
    serializer_class = AssessmentSerializer
    permission_classes = [permissions.IsAuthenticated, IsInstructorOrAdmin]
    # lookup_field = 'id' # Default is pk which is UUID id, no need to specify unless different

    def get_permissions(self):
        """ Assign permissions based on action. """
        if self.action in ['list', 'retrieve', 'attempts']:
            # Allow authenticated users within the tenant
            # Learners will be filtered in get_queryset to only see assessments for enrolled courses
            permission_classes = [permissions.IsAuthenticated]
        elif self.action == 'create':
            permission_classes = [permissions.IsAuthenticated, IsInstructorOrAdmin]
        elif self.action in ['update', 'partial_update', 'destroy']:
            permission_classes = [permissions.IsAuthenticated, IsCourseInstructorOrAdmin] # Checks parent course instructor/admin
        else:
            permission_classes = [permissions.IsAdminUser] # Default restrictive
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        """
        Filter assessments based on user role:
        - Superusers see all assessments
        - Instructors/Admins see all assessments in their tenant
        - Learners only see published assessments for courses they're enrolled in
        """
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return Assessment.objects.none()

        user = self.request.user
        tenant = self.request.tenant

        if not user.is_authenticated:
            return Assessment.objects.none()

        if user.is_superuser:
            queryset = Assessment.objects.all()
        elif tenant:
            queryset = Assessment.objects.filter(course__tenant=tenant)
            
            # For learners, filter to only show published assessments for enrolled courses
            if hasattr(user, 'role') and user.role == User.Role.LEARNER:
                # Get courses where user has active enrollment
                enrolled_course_ids = Enrollment.objects.filter(
                    user=user,
                    status=Enrollment.Status.ACTIVE
                ).values_list('course_id', flat=True)
                
                queryset = queryset.filter(
                    course_id__in=enrolled_course_ids,
                    is_published=True
                )
        else:
            queryset = Assessment.objects.none()

        # Optimize query
        return queryset.select_related('course', 'course__tenant').prefetch_related('questions')

    def perform_create(self, serializer):
        """
        Create a new assessment, ensuring the user has permission for the target course.
        """
        course_id = self.request.data.get('course')
        if not course_id:
            raise serializers.ValidationError({"course": "Course ID must be provided."})
        
        # Get the course and verify permissions
        course = get_object_or_404(Course, pk=course_id)
        
        # Check tenant match (unless superuser)
        if not self.request.user.is_superuser:
            if self.request.tenant and course.tenant != self.request.tenant:
                raise PermissionDenied("You cannot create assessments for courses in a different tenant.")
        
        # Check if user is the course instructor or an admin
        is_instructor = course.instructor == self.request.user
        is_admin = self.request.user.is_staff
        
        if not (is_instructor or is_admin):
            raise PermissionDenied("You can only create assessments for courses you instruct.")
        
        serializer.save()

    @action(detail=True, methods=['get'])
    def attempts(self, request, pk=None):
        """
        Custom action to retrieve attempts for a specific assessment.
        GET /assessments/{assessment_id}/attempts/
        
        For learners: returns only their own attempts
        For instructors/admins: returns all attempts for the assessment
        """
        assessment = self.get_object()
        
        # Get all attempts for this assessment, ordered by most recent first
        attempts = AssessmentAttempt.objects.filter(
            assessment=assessment
        ).select_related('user', 'graded_by').order_by('-start_time')
        
        # Apply tenant filtering for non-superusers
        if not request.user.is_superuser and request.tenant:
            attempts = attempts.filter(assessment__course__tenant=request.tenant)
        
        # For learners, filter to only show their own attempts
        if hasattr(request.user, 'role') and request.user.role == User.Role.LEARNER:
            attempts = attempts.filter(user=request.user)
        
        serializer = AssessmentAttemptSerializer(attempts, many=True)
        return Response(serializer.data)


@extend_schema(tags=['Assessments'])
class QuestionViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Questions within a specific Assessment.
    Accessed via nested routes like /api/v1/assessments/{assessment_pk}/questions/
    Requires Instructor/Admin permissions for the parent assessment.
    """
    serializer_class = QuestionSerializer
    permission_classes = [permissions.IsAuthenticated, IsCourseInstructorOrAdmin] # Checks permission on parent course via assessment lookup

    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return Question.objects.none()

        assessment_pk = self.kwargs.get('assessment_pk') # Get from nested router URL
        tenant = self.request.tenant # Get tenant from request context (set by middleware)

        # Basic check: ensure assessment_pk is provided and user has tenant context (unless superuser)
        if not assessment_pk or (not tenant and not self.request.user.is_superuser):
             return Question.objects.none()

        # Build initial filter based on assessment PK
        queryset = Question.objects.filter(assessment_id=assessment_pk)

        # Apply tenant filter unless superuser
        if not self.request.user.is_superuser and tenant:
             queryset = queryset.filter(assessment__course__tenant=tenant)

        # Permission check: Ensure user can actually access the parent assessment
        # This might be implicitly handled by IsCourseInstructorOrAdmin checking the parent assessment,
        # but an explicit check might be safer depending on permission logic.
        # try:
        #     assessment = Assessment.objects.get(pk=assessment_pk)
        #     if not self.check_object_permissions(self.request, assessment): # Reuse object permissions
        #          return Question.objects.none()
        # except Assessment.DoesNotExist:
        #      return Question.objects.none()

        return queryset.select_related('assessment').order_by('order')


    def perform_create(self, serializer):
        assessment_pk = self.kwargs.get('assessment_pk')
        # Fetch assessment, tenant check is implicit via queryset used by permission class on parent
        # We re-check here for clarity and safety before saving.
        assessment = get_object_or_404(Assessment, pk=assessment_pk)

        # Explicit permission check before saving (using object permissions on assessment)
        self.check_object_permissions(self.request, assessment)

        # Assign order automatically
        last_order = Question.objects.filter(assessment=assessment).aggregate(models.Max('order'))['order__max'] or 0
        serializer.save(assessment=assessment, order=last_order + 1)


@extend_schema(tags=['Instructor - Assessments'])
class InstructorAssessmentViewSet(viewsets.ModelViewSet):
    """
    API endpoint for instructors to manage their own assessments.
    Only shows assessments for courses taught by the instructor.
    """
    serializer_class = AssessmentSerializer
    permission_classes = [permissions.IsAuthenticated, IsInstructorOrAdmin]

    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return Assessment.objects.none()

        user = self.request.user
        tenant = self.request.tenant

        if not user.is_authenticated:
            return Assessment.objects.none()

        # For instructors, only show assessments for courses they teach
        if user.is_superuser:
            queryset = Assessment.objects.all()
        elif tenant:
            queryset = Assessment.objects.filter(
                course__tenant=tenant,
                course__instructor=user  # Only courses taught by this instructor
            )
        else:
            queryset = Assessment.objects.none()

        # Optimize query
        return queryset.select_related('course', 'course__tenant').prefetch_related('questions')

    def perform_create(self, serializer):
        # Ensure instructor can only create assessments for their own courses
        course_id = self.request.data.get('course')
        if not course_id:
            raise serializers.ValidationError({"course": "Course ID must be provided."})
        
        # Verify the instructor teaches this course
        from apps.courses.models import Course
        try:
            course = Course.objects.get(
                pk=course_id, 
                tenant=self.request.tenant,
                instructor=self.request.user
            )
        except Course.DoesNotExist:
            raise serializers.ValidationError({"course": "You can only create assessments for courses you teach."})
        
        serializer.save()

    @action(detail=True, methods=['get'])
    def attempts(self, request, pk=None):
        """
        Custom action to retrieve all attempts for a specific assessment.
        GET /api/v1/instructor/assessments/{assessment_id}/attempts/
        """
        assessment = self.get_object()
        
        # Get all attempts for this assessment, ordered by most recent first
        attempts = AssessmentAttempt.objects.filter(
            assessment=assessment
        ).select_related('user', 'graded_by').order_by('-start_time')
        
        serializer = AssessmentAttemptSerializer(attempts, many=True)
        return Response(serializer.data)

    @extend_schema(
        request=ManualGradeSerializer,
        responses={200: AssessmentAttemptSerializer},
        description="Manually grade a submitted assessment attempt",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="attempts/(?P<attempt_id>[^/.]+)/grade",
    )
    def grade_attempt(self, request, pk=None, attempt_id=None):
        """
        Manually grade a submitted assessment attempt.
        POST /api/v1/instructor/assessments/{assessment_id}/attempts/{attempt_id}/grade/
        
        Request body:
        {
            "score": 85.5,
            "feedback": "Good work overall, but...",
            "question_scores": {"question_uuid": 10}  // optional
        }
        """
        assessment = self.get_object()
        
        # Get the attempt and verify it belongs to this assessment
        attempt = get_object_or_404(
            AssessmentAttempt,
            pk=attempt_id,
            assessment=assessment,
        )
        
        # Verify attempt is in a gradable state (SUBMITTED or re-grading GRADED)
        if attempt.status == AssessmentAttempt.AttemptStatus.IN_PROGRESS:
            return Response(
                {"detail": "Cannot grade an attempt that is still in progress."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        # Validate input data
        serializer = ManualGradeSerializer(
            data=request.data,
            context={"attempt": attempt},
        )
        serializer.is_valid(raise_exception=True)
        
        # Update the attempt with grading information
        attempt.score = serializer.validated_data["score"]
        attempt.feedback = serializer.validated_data.get("feedback", "")
        attempt.graded_by = request.user
        attempt.graded_at = timezone.now()
        attempt.status = AssessmentAttempt.AttemptStatus.GRADED
        
        # Determine pass/fail status
        if attempt.max_score and assessment.pass_mark_percentage is not None:
            from decimal import Decimal
            pass_mark = (
                Decimal(assessment.pass_mark_percentage) / Decimal(100)
            ) * Decimal(attempt.max_score)
            attempt.is_passed = attempt.score >= pass_mark
        
        attempt.save()
        
        # Send grading notification to the learner
        try:
            content = NotificationService.generate_content_for_type(
                NotificationType.ASSESSMENT_GRADED,
                {
                    "user_name": attempt.user.get_full_name() or attempt.user.email,
                    "assessment_title": assessment.title,
                    "course_name": assessment.course.title,
                    "score": str(attempt.score) if attempt.score is not None else "",
                    "max_score": str(attempt.max_score) if attempt.max_score else "",
                }
            )
            NotificationService.create_notification(
                user=attempt.user,
                notification_type=NotificationType.ASSESSMENT_GRADED,
                subject=content["subject"],
                message=content["message"],
                action_url=f"/courses/{assessment.course.slug}/assessments/{assessment.id}/attempts/{attempt.id}",
            )
        except Exception as e:
            logger.error(f"Failed to send grading notification for attempt {attempt.id}: {e}", exc_info=True)
        
        # Return the updated attempt
        return Response(
            AssessmentAttemptSerializer(attempt).data,
            status=status.HTTP_200_OK,
        )
