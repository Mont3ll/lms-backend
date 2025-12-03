from rest_framework import viewsets, permissions, serializers # Added serializers import
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db import models
from .models import Assessment, Question, AssessmentAttempt
from .serializers import AssessmentSerializer, QuestionSerializer, AssessmentAttemptSerializer
from apps.users.permissions import IsAdminOrTenantAdmin, IsInstructorOrAdmin
from apps.courses.permissions import IsCourseInstructorOrAdmin
from drf_spectacular.utils import extend_schema

@extend_schema(tags=['Assessments'])
class AssessmentViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Assessments (CRUD).
    Typically accessed by Instructors or Admins.
    """
    serializer_class = AssessmentSerializer
    permission_classes = [permissions.IsAuthenticated, IsInstructorOrAdmin]
    # lookup_field = 'id' # Default is pk which is UUID id, no need to specify unless different

    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return Assessment.objects.none()

        user = self.request.user
        tenant = self.request.tenant

        if not user.is_authenticated: return Assessment.objects.none()

        if user.is_superuser:
             queryset = Assessment.objects.all()
        elif tenant:
             queryset = Assessment.objects.filter(course__tenant=tenant)
             # Optional: Filter for instructors to only see assessments in courses they teach
             # if user.role == User.Role.INSTRUCTOR:
             #    queryset = queryset.filter(course__instructor=user)
        else:
             queryset = Assessment.objects.none()

        # Optimize query
        return queryset.select_related('course', 'course__tenant').prefetch_related('questions')

    def get_permissions(self):
        """ Assign permissions based on action. """
        if self.action in ['list', 'retrieve', 'attempts']:
            # Allow authenticated users within the tenant (visibility depends on course access)
            # TODO: Refine with enrollment check for learners?
            permission_classes = [permissions.IsAuthenticated]
        elif self.action == 'create':
            permission_classes = [permissions.IsAuthenticated, IsInstructorOrAdmin]
        elif self.action in ['update', 'partial_update', 'destroy']:
            permission_classes = [permissions.IsAuthenticated, IsCourseInstructorOrAdmin] # Checks parent course instructor/admin
        else:
            permission_classes = [permissions.IsAdminUser] # Default restrictive
        return [permission() for permission in permission_classes]

    def perform_create(self, serializer):
        # Course ID should be provided in request data
        course_id = self.request.data.get('course')
        if not course_id:
             raise serializers.ValidationError({"course": "Course ID must be provided."})
        # TODO: Check if request.user has permission to create assessment for this course
        # E.g., is instructor of course_id or tenant admin
        # course = get_object_or_404(Course, pk=course_id, tenant=self.request.tenant)
        # if not (self.request.user.is_staff or course.instructor == self.request.user):
        #      raise PermissionDenied("You cannot create assessments for this course.")
        serializer.save() # Assumes course FK is handled correctly by serializer/data

    @action(detail=True, methods=['get'])
    def attempts(self, request, pk=None):
        """
        Custom action to retrieve all attempts for a specific assessment.
        GET /assessments/{assessment_id}/attempts/
        """
        assessment = self.get_object()
        
        # Get all attempts for this assessment, ordered by most recent first
        attempts = AssessmentAttempt.objects.filter(
            assessment=assessment
        ).select_related('user', 'graded_by').order_by('-start_time')
        
        # Apply tenant filtering for non-superusers
        if not request.user.is_superuser and request.tenant:
            attempts = attempts.filter(assessment__course__tenant=request.tenant)
        
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
