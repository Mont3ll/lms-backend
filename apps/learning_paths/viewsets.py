from rest_framework import viewsets, permissions, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction, models
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from django.utils import timezone
import uuid as uuid_module
from .models import (
    LearningPath,
    LearningPathStep,
    LearningPathProgress,
    LearningPathStepProgress,
    PersonalizedLearningPath,
    PersonalizedPathStep,
    PersonalizedPathProgress,
)
from .serializers import (
    LearningPathSerializer,
    LearningPathStepSerializer,
    LearningPathStepOrderSerializer,
    LearningPathProgressSerializer,
    LearningPathStepProgressSerializer,
    PersonalizedLearningPathSerializer,
    PersonalizedLearningPathListSerializer,
    PersonalizedPathStepSerializer,
    PersonalizedPathProgressSerializer,
    GenerateSkillGapPathSerializer,
    GenerateRemedialPathSerializer,
    GeneratePathPreviewSerializer,
    PathPreviewResponseSerializer,
)
from .services import LearningPathService
from apps.users.permissions import IsAdminOrTenantAdmin, IsInstructorOrAdmin
from apps.courses.models import Course, Module
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse # <-- IMPORTED OpenApiResponse
from drf_spectacular.types import OpenApiTypes # <-- IMPORTED OpenApiTypes for consistency

@extend_schema(tags=['Learning Paths'])
class LearningPathViewSet(viewsets.ModelViewSet):
    """ API endpoint for managing Learning Paths. """
    serializer_class = LearningPathSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'slug'
    lookup_value_regex = r'[-\w]+' # <-- USED RAW STRING (r'')

    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return LearningPath.objects.none()

        tenant = self.request.tenant
        user = self.request.user

        if not user.is_authenticated: return LearningPath.objects.none()

        if user.is_superuser:
            queryset = LearningPath.objects.all()
        elif tenant:
            queryset = LearningPath.objects.filter(tenant=tenant)
            if not user.is_staff:
                 queryset = queryset.filter(status=LearningPath.Status.PUBLISHED)
        else:
             queryset = LearningPath.objects.none()

        return queryset.select_related('tenant').prefetch_related(
            models.Prefetch('steps', queryset=LearningPathStep.objects.order_by('order')
                     .select_related('content_type')
            )
        ).order_by('title')

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.IsAuthenticated()]
        elif self.action == 'create':
            return [permissions.IsAuthenticated(), IsInstructorOrAdmin()]
        elif self.action == 'manage_steps':
            # GET (list steps) is allowed for authenticated users
            # POST (add steps) requires admin permissions
            if self.request.method == 'GET':
                return [permissions.IsAuthenticated()]
            return [permissions.IsAuthenticated(), IsAdminOrTenantAdmin()]
        elif self.action in ['update', 'partial_update', 'destroy', 'manage_single_step', 'reorder_steps']:
            return [permissions.IsAuthenticated(), IsAdminOrTenantAdmin()]
        return [permissions.IsAdminUser()]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        context['view'] = self
        return context

    def perform_create(self, serializer):
        tenant = self.request.tenant
        if not tenant and not self.request.user.is_superuser:
             raise serializers.ValidationError("Tenant context required for non-superusers.")
        req_tenant = serializer.validated_data.get('tenant', tenant) # Allow superuser to specify
        if not req_tenant:
            raise serializers.ValidationError({"tenant": "Tenant must be specified."})
        serializer.save(tenant=req_tenant)


    @extend_schema(
        methods=['GET'], summary="List Path Steps", responses={200: LearningPathStepSerializer(many=True)}
    )
    @extend_schema(
        methods=['POST'], summary="Add Path Step", request=LearningPathStepSerializer, responses={201: LearningPathStepSerializer}
    )
    @action(detail=True, methods=['get', 'post'], url_path='steps', serializer_class=LearningPathStepSerializer)
    def manage_steps(self, request, slug=None): # slug is the LearningPath slug
        learning_path = self.get_object()

        if request.method == 'GET':
            steps = learning_path.steps.select_related('content_type').order_by('order')
            serializer = self.get_serializer(steps, many=True)
            return Response(serializer.data)

        elif request.method == 'POST':
            serializer = self.get_serializer(data=request.data) # LearningPathStepSerializer
            if serializer.is_valid():
                 content_type = serializer.validated_data['content_type'] # This is a ContentType instance
                 object_id = serializer.validated_data['object_id']
                 ModelClass = content_type.model_class()
                 if not ModelClass:
                      return Response({"content_type": "Invalid content type."}, status=status.HTTP_400_BAD_REQUEST)
                 try:
                     content_obj = ModelClass.objects.get(pk=object_id)
                     obj_tenant = getattr(content_obj, 'tenant', None)
                     if isinstance(content_obj, Module):
                         obj_tenant = getattr(getattr(content_obj, 'course', None), 'tenant', None)
                     if obj_tenant != learning_path.tenant:
                          return Response({"object_id": f"{content_type.model.capitalize()} does not belong to this tenant."}, status=status.HTTP_400_BAD_REQUEST)
                 except ModelClass.DoesNotExist:
                      return Response({"object_id": f"{content_type.model.capitalize()} not found."}, status=status.HTTP_404_NOT_FOUND)

                 last_order = learning_path.steps.aggregate(models.Max('order'))['order__max'] or 0
                 order = last_order + 1
                 serializer.save(learning_path=learning_path, order=order) # content_type and object_id already set
                 return Response(serializer.data, status=status.HTTP_201_CREATED)
            else:
                 return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        methods=['PUT', 'PATCH'], summary="Update Path Step", request=LearningPathStepSerializer, responses={200: LearningPathStepSerializer}
    )
    @extend_schema(
        methods=['DELETE'], summary="Delete Path Step", responses={204: OpenApiResponse(description="Step deleted")} # <-- USED OpenApiResponse
    )
    @action(detail=True, methods=['put', 'patch', 'delete'], url_path=r'steps/(?P<step_pk>[^/.]+)', serializer_class=LearningPathStepSerializer) # Use r'' raw string for regex
    def manage_single_step(self, request, slug=None, step_pk=None): # slug is LearningPath slug
        learning_path = self.get_object()
        step = get_object_or_404(LearningPathStep, pk=step_pk, learning_path=learning_path)

        if request.method == 'DELETE':
             step_order = step.order
             step.delete()
             LearningPathStep.objects.filter(
                 learning_path=learning_path, order__gt=step_order
             ).update(order=models.F('order') - 1)
             return Response(status=status.HTTP_204_NO_CONTENT)

        partial = (request.method == 'PATCH')
        serializer = self.get_serializer(step, data=request.data, partial=partial) # LearningPathStepSerializer
        if serializer.is_valid():
            if 'content_type' in serializer.validated_data or 'object_id' in serializer.validated_data:
                 content_type = serializer.validated_data.get('content_type', step.content_type)
                 object_id = serializer.validated_data.get('object_id', step.object_id)
                 ModelClass = content_type.model_class()
                 if not ModelClass: return Response({"content_type": "Invalid content type."}, status=status.HTTP_400_BAD_REQUEST)
                 try:
                     content_obj = ModelClass.objects.get(pk=object_id)
                     obj_tenant = getattr(content_obj, 'tenant', getattr(getattr(content_obj, 'course', None), 'tenant', None))
                     if obj_tenant != learning_path.tenant:
                          return Response({"object_id": f"{content_type.model.capitalize()} does not belong to this tenant."}, status=status.HTTP_400_BAD_REQUEST)
                 except ModelClass.DoesNotExist:
                      return Response({"object_id": f"{content_type.model.capitalize()} not found."}, status=status.HTTP_404_NOT_FOUND)
            serializer.save()
            return Response(serializer.data)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


    @extend_schema(
        tags=['Learning Paths'],
        summary="Reorder Path Steps",
        request=LearningPathStepOrderSerializer,
        responses={200: OpenApiResponse(description="Steps reordered successfully.")} # <-- USED OpenApiResponse
    )
    @action(detail=True, methods=['post'], url_path='reorder-steps', serializer_class=LearningPathStepOrderSerializer)
    @transaction.atomic
    def reorder_steps(self, request, slug=None): # slug is LearningPath slug
        learning_path = self.get_object()
        serializer = self.get_serializer(data=request.data) # LearningPathStepOrderSerializer
        if serializer.is_valid():
            step_ids_in_order = serializer.validated_data['steps']
            current_steps_count = learning_path.steps.count()
            if len(step_ids_in_order) != current_steps_count:
                 return Response({"detail": "Number of step IDs does not match existing steps."}, status=status.HTTP_400_BAD_REQUEST)

            steps_qs = LearningPathStep.objects.filter(id__in=step_ids_in_order, learning_path=learning_path)
            if steps_qs.count() != len(step_ids_in_order): # Checks for alien steps
                 return Response({"detail": "Invalid or duplicate step IDs for this learning path."}, status=status.HTTP_400_BAD_REQUEST)

            # To avoid unique constraint violations during reorder:
            # First, shift all orders to high values (base + current order to maintain relative positions)
            offset = 10000
            for step_id in step_ids_in_order:
                step = LearningPathStep.objects.get(id=step_id, learning_path=learning_path)
                step.order = offset + step.order
                step.save()
            # Then, set them to the final values
            for index, step_id in enumerate(step_ids_in_order):
                LearningPathStep.objects.filter(id=step_id, learning_path=learning_path).update(order=index + 1)
            return Response({"detail": "Steps reordered successfully."}, status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Learning Paths'],
        summary="Get My Progress",
        description="Get the current user's progress for this learning path. POST creates a progress record and auto-enrolls in courses if none exists.",
        responses={200: LearningPathProgressSerializer}
    )
    @action(detail=True, methods=['get', 'post'], url_path='my-progress', serializer_class=LearningPathProgressSerializer)
    def my_progress(self, request, slug=None):
        """
        Get or create the current user's progress for this learning path.
        
        GET: Returns the user's progress, or 404 if not started.
        POST: Creates progress if not started, auto-enrolls user in all courses 
              within the path, then returns the progress.
        """
        learning_path = self.get_object()
        user = request.user
        
        if request.method == 'GET':
            try:
                progress = LearningPathProgress.objects.select_related(
                    'learning_path'
                ).prefetch_related(
                    'step_progress__step'
                ).get(
                    user=user,
                    learning_path=learning_path
                )
                serializer = LearningPathProgressSerializer(progress, context={'request': request})
                return Response(serializer.data)
            except LearningPathProgress.DoesNotExist:
                return Response(
                    {"detail": "You have not started this learning path yet."},
                    status=status.HTTP_404_NOT_FOUND
                )
        
        elif request.method == 'POST':
            # Use the service to enroll in learning path and auto-enroll in courses
            progress, created, course_enrollments = LearningPathService.enroll_in_learning_path(
                user=user,
                learning_path=learning_path
            )
            
            # Refetch with related data
            progress = LearningPathProgress.objects.select_related(
                'learning_path'
            ).prefetch_related(
                'step_progress__step'
            ).get(pk=progress.pk)
            
            serializer = LearningPathProgressSerializer(progress, context={'request': request})
            response_data = serializer.data
            
            # Include info about course enrollments in the response
            response_data['courses_enrolled'] = len(course_enrollments)
            
            return Response(response_data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

@extend_schema(tags=['Learning Path Progress'])
class LearningPathProgressViewSet(viewsets.ModelViewSet):
    """API endpoint for managing user progress through learning paths."""
    serializer_class = LearningPathProgressSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return LearningPathProgress.objects.none()
        
        user = self.request.user
        if not user.is_authenticated:
            return LearningPathProgress.objects.none()
        
        # Users can only see their own progress
        if user.is_superuser or user.is_staff:
            # Admins can see all progress in their tenant
            tenant = self.request.tenant
            if tenant:
                queryset = LearningPathProgress.objects.filter(
                    learning_path__tenant=tenant
                ).select_related('user', 'learning_path').prefetch_related(
                    'step_progress__step'
                ).order_by('-updated_at')
            else:
                queryset = LearningPathProgress.objects.all().select_related(
                    'user', 'learning_path'
                ).prefetch_related('step_progress__step').order_by('-updated_at')
        else:
            # Regular users see only their own progress
            queryset = LearningPathProgress.objects.filter(user=user).select_related(
                'learning_path'
            ).prefetch_related('step_progress__step').order_by('-updated_at')
        
        # Apply optional filters from query params
        learning_path_param = self.request.query_params.get('learning_path')
        if learning_path_param:
            # Support filtering by learning path ID or slug
            # Check if it looks like a UUID before querying by ID
            try:
                uuid_module.UUID(learning_path_param)
                # It's a valid UUID, filter by ID or slug
                queryset = queryset.filter(
                    models.Q(learning_path__id=learning_path_param) | 
                    models.Q(learning_path__slug=learning_path_param)
                )
            except ValueError:
                # Not a UUID, filter by slug only
                queryset = queryset.filter(learning_path__slug=learning_path_param)
        
        status_param = self.request.query_params.get('status')
        if status_param:
            queryset = queryset.filter(status=status_param)
        
        return queryset
    
    def perform_create(self, serializer):
        """Create progress for the current user."""
        serializer.save(user=self.request.user)
    
    @extend_schema(
        summary="Start Learning Path",
        description="Start or resume progress on a learning path."
    )
    @action(detail=True, methods=['post'], url_path='start')
    def start_path(self, request, pk=None):
        """Start a learning path for the current user."""
        progress = self.get_object()
        
        # Only allow users to start their own paths
        if progress.user != request.user and not request.user.is_staff:
            return Response(
                {"detail": "You can only manage your own progress."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if progress.status == LearningPathProgress.Status.NOT_STARTED:
            progress.status = LearningPathProgress.Status.IN_PROGRESS
            progress.started_at = timezone.now()
            progress.save()
            
            # Create step progress for all steps
            steps = progress.learning_path.steps.all()
            for step in steps:
                LearningPathStepProgress.objects.get_or_create(
                    user=progress.user,
                    learning_path_progress=progress,
                    step=step,
                    defaults={'status': LearningPathStepProgress.Status.NOT_STARTED}
                )
        
        serializer = self.get_serializer(progress)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Complete Step",
        description="Mark a step as completed and advance progress."
    )
    @action(detail=True, methods=['post'], url_path=r'steps/(?P<step_pk>[^/.]+)/complete')
    def complete_step(self, request, pk=None, step_pk=None):
        """Mark a step as completed."""
        progress = self.get_object()
        
        # Only allow users to manage their own progress
        if progress.user != request.user and not request.user.is_staff:
            return Response(
                {"detail": "You can only manage your own progress."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            step = LearningPathStep.objects.get(
                pk=step_pk, 
                learning_path=progress.learning_path
            )
        except LearningPathStep.DoesNotExist:
            return Response(
                {"detail": "Step not found in this learning path."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get or create step progress
        step_progress, created = LearningPathStepProgress.objects.get_or_create(
            user=progress.user,
            learning_path_progress=progress,
            step=step,
            defaults={
                'status': LearningPathStepProgress.Status.COMPLETED,
                'started_at': timezone.now(),
                'completed_at': timezone.now()
            }
        )
        
        if not created and step_progress.status != LearningPathStepProgress.Status.COMPLETED:
            step_progress.status = LearningPathStepProgress.Status.COMPLETED
            step_progress.completed_at = timezone.now()
            if not step_progress.started_at:
                step_progress.started_at = timezone.now()
            step_progress.save()
        
        # Update overall progress
        progress.current_step_order = step.order
        if progress.status == LearningPathProgress.Status.NOT_STARTED:
            progress.status = LearningPathProgress.Status.IN_PROGRESS
            progress.started_at = timezone.now()
        
        # Check if all required steps are completed
        total_required_steps = progress.learning_path.steps.filter(is_required=True).count()
        completed_required_steps = LearningPathStepProgress.objects.filter(
            learning_path_progress=progress,
            step__is_required=True,
            status=LearningPathStepProgress.Status.COMPLETED
        ).count()
        
        if completed_required_steps >= total_required_steps:
            progress.status = LearningPathProgress.Status.COMPLETED
            progress.completed_at = timezone.now()
        
        progress.save()
        
        serializer = self.get_serializer(progress)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Reset Step",
        description="Mark a step as incomplete."
    )
    @action(detail=True, methods=['post'], url_path=r'steps/(?P<step_pk>[^/.]+)/reset')
    def reset_step(self, request, pk=None, step_pk=None):
        """Mark a step as incomplete."""
        progress = self.get_object()
        
        # Only allow users to manage their own progress
        if progress.user != request.user and not request.user.is_staff:
            return Response(
                {"detail": "You can only manage your own progress."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            step = LearningPathStep.objects.get(
                pk=step_pk, 
                learning_path=progress.learning_path
            )
        except LearningPathStep.DoesNotExist:
            return Response(
                {"detail": "Step not found in this learning path."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Update step progress
        try:
            step_progress = LearningPathStepProgress.objects.get(
                user=progress.user,
                learning_path_progress=progress,
                step=step
            )
            step_progress.status = LearningPathStepProgress.Status.NOT_STARTED
            step_progress.completed_at = None
            step_progress.save()
            
            # Update overall progress - if this was completed, mark as in progress
            if progress.status == LearningPathProgress.Status.COMPLETED:
                progress.status = LearningPathProgress.Status.IN_PROGRESS
                progress.completed_at = None
                progress.save()
                
        except LearningPathStepProgress.DoesNotExist:
            pass  # Nothing to reset
        
        serializer = self.get_serializer(progress)
        return Response(serializer.data)


@extend_schema(tags=['Learning Path Step Progress'])
class LearningPathStepProgressViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only API endpoint for viewing step progress."""
    serializer_class = LearningPathStepProgressSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return LearningPathStepProgress.objects.none()
        
        user = self.request.user
        if not user.is_authenticated:
            return LearningPathStepProgress.objects.none()
        
        # Users can only see their own step progress
        if user.is_superuser or user.is_staff:
            tenant = self.request.tenant
            if tenant:
                queryset = LearningPathStepProgress.objects.filter(
                    learning_path_progress__learning_path__tenant=tenant
                ).select_related(
                    'user', 'learning_path_progress', 'step'
                ).order_by('step__order')
            else:
                queryset = LearningPathStepProgress.objects.all().select_related(
                    'user', 'learning_path_progress', 'step'
                ).order_by('step__order')
        else:
            queryset = LearningPathStepProgress.objects.filter(user=user).select_related(
                'learning_path_progress', 'step'
            ).order_by('step__order')
        
        # Apply optional filters from query params
        learning_path_progress_param = self.request.query_params.get('learning_path_progress')
        if learning_path_progress_param:
            queryset = queryset.filter(learning_path_progress__id=learning_path_progress_param)
        
        status_param = self.request.query_params.get('status')
        if status_param:
            queryset = queryset.filter(status=status_param)
        
        return queryset


# =============================================================================
# Personalized Learning Path ViewSets
# =============================================================================


@extend_schema(tags=['Personalized Learning Paths'])
class PersonalizedLearningPathViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing AI-generated personalized learning paths.
    
    Personalized paths are generated for individual users based on their
    skill gaps, goals, or remediation needs. Unlike curated learning paths,
    these are specific to one user.
    
    Regular users can only view and manage their own personalized paths.
    Admins can view all personalized paths in their tenant.
    """
    serializer_class = PersonalizedLearningPathSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return PersonalizedLearningPath.objects.none()
        
        user = self.request.user
        if not user.is_authenticated:
            return PersonalizedLearningPath.objects.none()
        
        # Admins can see all paths in their tenant
        if user.is_superuser:
            queryset = PersonalizedLearningPath.objects.all()
        elif user.is_staff:
            tenant = self.request.tenant
            if tenant:
                queryset = PersonalizedLearningPath.objects.filter(tenant=tenant)
            else:
                queryset = PersonalizedLearningPath.objects.none()
        else:
            # Regular users only see their own paths
            queryset = PersonalizedLearningPath.objects.filter(user=user)
        
        return queryset.select_related('user', 'tenant').prefetch_related(
            models.Prefetch(
                'steps',
                queryset=PersonalizedPathStep.objects.order_by('order').select_related('module')
            ),
            'target_skills'
        ).order_by('-generated_at')
    
    def get_serializer_class(self):
        if self.action == 'list':
            return PersonalizedLearningPathListSerializer
        return PersonalizedLearningPathSerializer
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.IsAuthenticated()]
        elif self.action in ['create']:
            # Path creation should be done through the generator service,
            # but allow admins to create manually
            return [permissions.IsAuthenticated(), IsAdminOrTenantAdmin()]
        elif self.action in ['update', 'partial_update']:
            # Users can update status of their own paths (e.g., archive)
            return [permissions.IsAuthenticated()]
        elif self.action == 'destroy':
            return [permissions.IsAuthenticated(), IsAdminOrTenantAdmin()]
        elif self.action in ['get_steps', 'archive', 'check_expiry']:
            # Users can access custom actions on their own paths
            return [permissions.IsAuthenticated()]
        elif self.action in ['generate_skill_gap_path', 'generate_remedial_path', 'preview_path_generation']:
            # Any authenticated user can generate paths for themselves
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]
    
    def perform_create(self, serializer):
        """Create a personalized path, setting user and tenant from request."""
        tenant = self.request.tenant
        if not tenant and not self.request.user.is_superuser:
            raise serializers.ValidationError("Tenant context required for non-superusers.")
        
        req_tenant = serializer.validated_data.get('tenant', tenant)
        req_user = serializer.validated_data.get('user', self.request.user)
        
        if not req_tenant:
            raise serializers.ValidationError({"tenant": "Tenant must be specified."})
        
        serializer.save(user=req_user, tenant=req_tenant)
    
    def perform_update(self, serializer):
        """Ensure users can only update their own paths (or admins can update any)."""
        instance = self.get_object()
        user = self.request.user
        
        if instance.user != user and not user.is_staff and not user.is_superuser:
            raise serializers.ValidationError("You can only update your own personalized paths.")
        
        serializer.save()
    
    @extend_schema(
        summary="Get Path Steps",
        description="Get all steps in a personalized learning path.",
        responses={200: PersonalizedPathStepSerializer(many=True)}
    )
    @action(detail=True, methods=['get'], url_path='steps')
    def get_steps(self, request, pk=None):
        """Get all steps in the personalized path."""
        path = self.get_object()
        steps = path.steps.select_related('module').prefetch_related('target_skills').order_by('order')
        serializer = PersonalizedPathStepSerializer(steps, many=True, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Archive Path",
        description="Archive a personalized learning path. Archived paths are no longer active but preserved for history.",
        responses={200: PersonalizedLearningPathSerializer}
    )
    @action(detail=True, methods=['post'], url_path='archive')
    def archive(self, request, pk=None):
        """Archive a personalized path."""
        path = self.get_object()
        user = request.user
        
        # Users can archive their own paths, admins can archive any
        if path.user != user and not user.is_staff and not user.is_superuser:
            return Response(
                {"detail": "You can only archive your own personalized paths."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if path.status == PersonalizedLearningPath.Status.ARCHIVED:
            return Response(
                {"detail": "Path is already archived."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        path.status = PersonalizedLearningPath.Status.ARCHIVED
        path.save()
        
        serializer = self.get_serializer(path)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Check Expiry",
        description="Check if a path has expired and update status if needed.",
        responses={200: PersonalizedLearningPathSerializer}
    )
    @action(detail=True, methods=['get'], url_path='check-expiry')
    def check_expiry(self, request, pk=None):
        """Check and update path expiry status."""
        path = self.get_object()
        
        if path.is_expired and path.status == PersonalizedLearningPath.Status.ACTIVE:
            path.status = PersonalizedLearningPath.Status.EXPIRED
            path.save()
        
        serializer = self.get_serializer(path)
        return Response(serializer.data)
    
    # =========================================================================
    # Path Generation Endpoints
    # =========================================================================
    
    @extend_schema(
        summary="Generate Skill-Gap Path",
        description="Generate a personalized learning path based on skill gaps. "
                    "The system analyzes the user's current skill levels against "
                    "target skills and creates an optimal learning path.",
        request=GenerateSkillGapPathSerializer,
        responses={201: PersonalizedLearningPathSerializer}
    )
    @action(detail=False, methods=['post'], url_path='generate')
    def generate_skill_gap_path(self, request):
        """
        Generate a personalized learning path based on skill gaps.
        
        POST /api/v1/personalized-paths/generate/
        {
            "target_skills": ["uuid1", "uuid2"],
            "max_duration_hours": 40,
            "max_modules": 20,
            "difficulty_preference": "INTERMEDIATE",
            "include_completed": false
        }
        """
        serializer = GenerateSkillGapPathSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        tenant = request.tenant
        
        if not tenant:
            return Response(
                {"detail": "Tenant context required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get validated data
        target_skill_ids = serializer.validated_data['target_skills']
        max_modules = serializer.validated_data.get('max_modules', 20)
        include_completed = serializer.validated_data.get('include_completed', False)
        difficulty_preference = serializer.validated_data.get('difficulty_preference', 'ANY')
        
        # Fetch target skills
        from apps.skills.models import Skill
        target_skills = list(Skill.objects.filter(id__in=target_skill_ids, is_active=True))
        
        if not target_skills:
            return Response(
                {"detail": "No valid target skills provided."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Initialize generator and generate path
        from .services import PersonalizedPathGenerator
        
        generator = PersonalizedPathGenerator(
            user=user,
            tenant=tenant,
            target_skills=target_skills,
            max_modules=max_modules,
            include_completed_modules=include_completed,
            difficulty_preference=difficulty_preference
        )
        
        try:
            path = generator.generate()
            
            if path is None:
                return Response(
                    {"detail": "Could not generate a learning path. No suitable modules found for the target skills."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Note: generation_params are already set by the generator in _create_path()
            # Update with any additional request params
            existing_params = path.generation_params or {}
            existing_params.update({
                'max_duration_hours': serializer.validated_data.get('max_duration_hours', 40),
            })
            path.generation_params = existing_params
            path.save(update_fields=['generation_params', 'updated_at'])
            
            # Return the created path
            response_serializer = PersonalizedLearningPathSerializer(
                path, context={'request': request}
            )
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
            
        except ValueError as e:
            # ValueError indicates a known error case (e.g., no suitable modules)
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {"detail": f"Error generating path: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @extend_schema(
        summary="Generate Remedial Path",
        description="Generate a remedial learning path based on a failed or low-scoring "
                    "assessment attempt. The path focuses on areas where the user needs improvement.",
        request=GenerateRemedialPathSerializer,
        responses={201: PersonalizedLearningPathSerializer}
    )
    @action(detail=False, methods=['post'], url_path='generate/remedial')
    def generate_remedial_path(self, request):
        """
        Generate a remedial learning path based on a failed assessment.
        
        POST /api/v1/personalized-paths/generate/remedial/
        {
            "assessment_attempt_id": "uuid",
            "focus_weak_areas": true,
            "max_modules": 10
        }
        """
        serializer = GenerateRemedialPathSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        tenant = request.tenant
        
        if not tenant:
            return Response(
                {"detail": "Tenant context required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get the assessment attempt
        from apps.assessments.models import AssessmentAttempt
        
        attempt_id = serializer.validated_data['assessment_attempt_id']
        max_modules = serializer.validated_data.get('max_modules', 10)
        focus_weak_areas = serializer.validated_data.get('focus_weak_areas', True)
        
        try:
            attempt = AssessmentAttempt.objects.select_related(
                'assessment', 'assessment__course'
            ).get(id=attempt_id)
        except AssessmentAttempt.DoesNotExist:
            return Response(
                {"detail": "Assessment attempt not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Verify user owns this attempt or is admin
        if attempt.user != user and not user.is_staff and not user.is_superuser:
            return Response(
                {"detail": "You can only generate remedial paths for your own assessments."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Analyze weak areas from the assessment
        # For now, we'll use skills associated with the assessment's questions
        # where the user got wrong answers
        weak_skill_ids = self._analyze_assessment_weaknesses(attempt, focus_weak_areas)
        
        if not weak_skill_ids:
            return Response(
                {"detail": "Could not identify weak areas from the assessment. "
                          "The assessment may not have skill mappings configured."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Fetch weak skills
        from apps.skills.models import Skill
        target_skills = list(Skill.objects.filter(id__in=weak_skill_ids, is_active=True))
        
        if not target_skills:
            return Response(
                {"detail": "No skills found for remediation."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Generate remedial path
        from .services import PersonalizedPathGenerator
        
        generator = PersonalizedPathGenerator(
            user=user,
            tenant=tenant,
            target_skills=target_skills,
            max_modules=max_modules,
            include_completed_modules=False  # Don't repeat completed modules
        )
        
        try:
            path = generator.generate()
            
            if path is None:
                return Response(
                    {"detail": "Could not generate a remedial path. No suitable modules found."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Update path to be remedial type
            path.generation_type = PersonalizedLearningPath.GenerationType.REMEDIAL
            path.title = f"Remedial Path - {attempt.assessment.title}"
            path.description = (
                f"A personalized remedial path to address weak areas identified in "
                f"your assessment attempt on {attempt.assessment.title}."
            )
            path.generation_params = {
                'assessment_attempt_id': str(attempt_id),
                'assessment_title': attempt.assessment.title,
                'attempt_score': float(attempt.score) if attempt.score else None,
                'focus_weak_areas': focus_weak_areas,
                'max_modules': max_modules,
                'weak_skill_ids': [str(s) for s in weak_skill_ids]
            }
            path.save()
            
            response_serializer = PersonalizedLearningPathSerializer(
                path, context={'request': request}
            )
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response(
                {"detail": f"Error generating remedial path: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _analyze_assessment_weaknesses(self, attempt, focus_weak_areas=True):
        """
        Analyze an assessment attempt to identify weak skill areas.
        
        Analyzes the attempt's JSON answers field against question data to determine
        which questions were answered incorrectly, then finds associated skills.
        
        Returns a list of skill IDs where the user performed poorly.
        """
        from apps.skills.models import AssessmentSkillMapping, ModuleSkill
        from apps.assessments.models import Question
        
        weak_skill_ids = set()
        
        # Get all questions for this assessment
        questions = Question.objects.filter(
            assessment=attempt.assessment
        ).prefetch_related('skill_mappings')
        
        # Parse the attempt's answers (stored as JSON: {question_id: answer_data})
        user_answers = attempt.answers or {}
        
        # Identify incorrectly answered questions
        incorrect_question_ids = []
        all_question_ids = []
        
        for question in questions:
            question_id_str = str(question.id)
            all_question_ids.append(question.id)
            
            user_answer = user_answers.get(question_id_str)
            
            # Determine if the answer is correct based on question type
            is_correct = self._check_answer_correctness(question, user_answer)
            
            if not is_correct:
                incorrect_question_ids.append(question.id)
        
        # Choose which questions to analyze
        if focus_weak_areas:
            question_ids_to_analyze = incorrect_question_ids
        else:
            question_ids_to_analyze = all_question_ids
        
        # Get skills mapped to these questions via AssessmentSkillMapping
        skill_mappings = AssessmentSkillMapping.objects.filter(
            question_id__in=question_ids_to_analyze
        ).values_list('skill_id', flat=True)
        
        weak_skill_ids.update(skill_mappings)
        
        # Also check skills via the Question.skills M2M (through AssessmentSkillMapping)
        for question in questions:
            if question.id in question_ids_to_analyze:
                # The skills M2M goes through AssessmentSkillMapping
                question_skills = question.skills.values_list('id', flat=True)
                weak_skill_ids.update(question_skills)
        
        # If no skill mappings found, try to get skills from the assessment's module/course
        if not weak_skill_ids:
            assessment = attempt.assessment
            if hasattr(assessment, 'module') and assessment.module:
                module_skills = ModuleSkill.objects.filter(
                    module=assessment.module
                ).values_list('skill_id', flat=True)
                weak_skill_ids.update(module_skills)
            elif hasattr(assessment, 'course') and assessment.course:
                module_skills = ModuleSkill.objects.filter(
                    module__course=assessment.course
                ).values_list('skill_id', flat=True)
                weak_skill_ids.update(module_skills)
        
        return list(weak_skill_ids)
    
    def _check_answer_correctness(self, question, user_answer):
        """
        Check if a user's answer is correct based on question type.
        
        Args:
            question: Question model instance
            user_answer: User's submitted answer (format depends on question type)
            
        Returns:
            bool: True if correct, False otherwise
        """
        if user_answer is None:
            return False
        
        type_data = question.type_specific_data or {}
        q_type = question.question_type
        
        # Multiple Choice / True-False: check selected option IDs against correct ones
        if q_type in ['MC', 'TF']:
            options = type_data.get('options', [])
            correct_ids = {opt['id'] for opt in options if opt.get('is_correct')}
            
            # user_answer should be a list of selected option IDs
            if isinstance(user_answer, list):
                selected_ids = set(user_answer)
            else:
                selected_ids = {user_answer}
            
            return selected_ids == correct_ids
        
        # Short Answer: check against correct answers
        elif q_type == 'SA':
            correct_answers = type_data.get('correct_answers', [])
            case_sensitive = type_data.get('case_sensitive', False)
            
            if isinstance(user_answer, str):
                user_text = user_answer if case_sensitive else user_answer.lower()
                correct_texts = correct_answers if case_sensitive else [a.lower() for a in correct_answers]
                return user_text in correct_texts
            return False
        
        # Fill in the Blanks: check each blank
        elif q_type == 'FB':
            blanks = type_data.get('blanks', {})
            if not isinstance(user_answer, dict):
                return False
            
            for blank_id, blank_data in blanks.items():
                correct_values = blank_data.get('correct', [])
                user_value = user_answer.get(blank_id, '')
                
                # Case-insensitive comparison for blanks
                if user_value.lower() not in [v.lower() for v in correct_values]:
                    return False
            return True
        
        # Matching: check prompt-match pairs
        elif q_type == 'MT':
            correct_pairs = type_data.get('correct_pairs', [])
            if not isinstance(user_answer, list):
                return False
            
            # Convert correct pairs to a set of tuples for comparison
            correct_set = {
                (p['prompt_id'], p['match_id']) 
                for p in correct_pairs
            }
            user_set = {
                (p.get('prompt_id'), p.get('selected_match_id'))
                for p in user_answer
            }
            return correct_set == user_set
        
        # Essay/Code: These are manually graded, assume incorrect for remedial purposes
        # (or we could check if it's been graded and use that score)
        elif q_type in ['ES', 'CODE']:
            # For manually graded questions, we can't determine correctness automatically
            # Return False to include in remedial path (conservative approach)
            return False
        
        # Unknown question type - assume incorrect
        return False
    
    @extend_schema(
        summary="Preview Path Generation",
        description="Preview a path generation without saving. Returns what the path "
                    "would look like, allowing users to review before committing.",
        request=GeneratePathPreviewSerializer,
        responses={200: PathPreviewResponseSerializer}
    )
    @action(detail=False, methods=['post'], url_path='generate/preview')
    def preview_path_generation(self, request):
        """
        Preview a path generation without saving.
        
        POST /api/v1/personalized-paths/generate/preview/
        {
            "generation_type": "SKILL_GAP",
            "target_skills": ["uuid1", "uuid2"],
            "max_modules": 20
        }
        """
        serializer = GeneratePathPreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        tenant = request.tenant
        
        if not tenant:
            return Response(
                {"detail": "Tenant context required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        gen_type = serializer.validated_data['generation_type']
        max_modules = serializer.validated_data.get('max_modules', 20)
        
        if gen_type == 'SKILL_GAP':
            target_skill_ids = serializer.validated_data.get('target_skills', [])
            max_duration = serializer.validated_data.get('max_duration_hours', 40) * 60
            include_completed = serializer.validated_data.get('include_completed', False)
            
            from apps.skills.models import Skill
            target_skills = list(Skill.objects.filter(id__in=target_skill_ids, is_active=True))
            
            if not target_skills:
                return Response(
                    {"detail": "No valid target skills provided."},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        elif gen_type == 'REMEDIAL':
            attempt_id = serializer.validated_data.get('assessment_attempt_id')
            focus_weak_areas = serializer.validated_data.get('focus_weak_areas', True)
            
            from apps.assessments.models import AssessmentAttempt
            
            try:
                attempt = AssessmentAttempt.objects.get(id=attempt_id)
            except AssessmentAttempt.DoesNotExist:
                return Response(
                    {"detail": "Assessment attempt not found."},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            if attempt.user != user and not user.is_staff:
                return Response(
                    {"detail": "You can only preview remedial paths for your own assessments."},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            weak_skill_ids = self._analyze_assessment_weaknesses(attempt, focus_weak_areas)
            
            from apps.skills.models import Skill
            target_skills = list(Skill.objects.filter(id__in=weak_skill_ids, is_active=True))
            max_duration = max_modules * 60  # Rough estimate
            include_completed = False
        else:
            return Response(
                {"detail": "Invalid generation type."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not target_skills:
            return Response(
                {"detail": "No target skills identified for path generation."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Generate preview (don't save)
        from .services import PersonalizedPathGenerator
        
        generator = PersonalizedPathGenerator(
            user=user,
            tenant=tenant,
            target_skills=target_skills,
            max_modules=max_modules,
            include_completed_modules=include_completed
        )
        
        try:
            # Use internal methods to get module selection without creating path
            skill_gaps = generator._analyze_skill_gaps()
            
            if not skill_gaps:
                return Response({
                    "detail": "No skill gaps found. You may already be proficient in the target skills.",
                    "title": "No path needed",
                    "description": "You are already proficient in all target skills.",
                    "generation_type": gen_type,
                    "estimated_duration": 0,
                    "total_steps": 0,
                    "steps": [],
                    "target_skills": [
                        {'id': str(s.id), 'name': s.name, 'slug': s.slug}
                        for s in target_skills
                    ],
                    "generation_params": serializer.validated_data
                }, status=status.HTTP_200_OK)
            
            candidates = generator._find_module_candidates(skill_gaps)
            selected = generator._select_optimal_modules(candidates, skill_gaps)
            
            if not selected:
                return Response({
                    "title": "No modules available",
                    "description": "No suitable modules found for the target skills.",
                    "generation_type": gen_type,
                    "estimated_duration": 0,
                    "total_steps": 0,
                    "steps": [],
                    "target_skills": [
                        {'id': str(s.id), 'name': s.name, 'slug': s.slug}
                        for s in target_skills
                    ],
                    "generation_params": serializer.validated_data
                })
            
            # Build preview response
            steps = []
            total_duration = 0
            
            for i, candidate in enumerate(selected, 1):
                module = candidate.module
                total_duration += candidate.estimated_duration
                
                steps.append({
                    'module_id': str(module.id),
                    'module_title': module.title,
                    'course_title': module.course.title,
                    'order': i,
                    'is_required': True,
                    'reason': f"Addresses skills: {', '.join(s.name for s in candidate.skills_addressed)}",
                    'estimated_duration': candidate.estimated_duration,
                    'skills_addressed': [
                        {'id': str(s.id), 'name': s.name, 'slug': s.slug}
                        for s in candidate.skills_addressed
                    ]
                })
            
            preview_data = {
                'title': f"Preview: {'Skill Gap' if gen_type == 'SKILL_GAP' else 'Remedial'} Learning Path",
                'description': f"A personalized path with {len(steps)} modules targeting {len(target_skills)} skills.",
                'generation_type': gen_type,
                'estimated_duration': total_duration,
                'total_steps': len(steps),
                'steps': steps,
                'target_skills': [
                    {'id': str(s.id), 'name': s.name, 'slug': s.slug}
                    for s in target_skills
                ],
                'generation_params': serializer.validated_data
            }
            
            return Response(preview_data)
            
        except Exception as e:
            return Response(
                {"detail": f"Error generating preview: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@extend_schema(tags=['Personalized Path Progress'])
class PersonalizedPathProgressViewSet(viewsets.ModelViewSet):
    """
    API endpoint for tracking progress through personalized learning paths.
    
    Users can only see and manage progress for their own personalized paths.
    """
    serializer_class = PersonalizedPathProgressSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return PersonalizedPathProgress.objects.none()
        
        user = self.request.user
        if not user.is_authenticated:
            return PersonalizedPathProgress.objects.none()
        
        # Admins can see all progress in their tenant
        if user.is_superuser:
            queryset = PersonalizedPathProgress.objects.all()
        elif user.is_staff:
            tenant = self.request.tenant
            if tenant:
                queryset = PersonalizedPathProgress.objects.filter(path__tenant=tenant)
            else:
                queryset = PersonalizedPathProgress.objects.none()
        else:
            # Regular users only see their own progress
            queryset = PersonalizedPathProgress.objects.filter(user=user)
        
        return queryset.select_related('user', 'path').order_by('-updated_at')
    
    def perform_create(self, serializer):
        """Create progress for the current user."""
        path = serializer.validated_data.get('path')
        user = self.request.user
        
        # Verify the path belongs to this user
        if path.user != user and not user.is_staff and not user.is_superuser:
            raise serializers.ValidationError("You can only track progress on your own personalized paths.")
        
        serializer.save(user=user)
    
    @extend_schema(
        summary="Start Path",
        description="Start tracking progress on a personalized learning path."
    )
    @action(detail=True, methods=['post'], url_path='start')
    def start_path(self, request, pk=None):
        """Start a personalized path."""
        progress = self.get_object()
        user = request.user
        
        # Users can only manage their own progress
        if progress.user != user and not user.is_staff:
            return Response(
                {"detail": "You can only manage your own progress."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if progress.status == PersonalizedPathProgress.Status.NOT_STARTED:
            progress.status = PersonalizedPathProgress.Status.IN_PROGRESS
            progress.started_at = timezone.now()
            progress.last_activity_at = timezone.now()
            progress.current_step_order = 1
            progress.save()
        
        serializer = self.get_serializer(progress)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Update Step",
        description="Update current step in the path progress."
    )
    @action(detail=True, methods=['post'], url_path='update-step')
    def update_step(self, request, pk=None):
        """Update the current step order."""
        progress = self.get_object()
        user = request.user
        
        if progress.user != user and not user.is_staff:
            return Response(
                {"detail": "You can only manage your own progress."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        step_order = request.data.get('step_order')
        if step_order is None:
            return Response(
                {"detail": "step_order is required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            step_order = int(step_order)
        except (TypeError, ValueError):
            return Response(
                {"detail": "step_order must be an integer."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate step exists
        if not progress.path.steps.filter(order=step_order).exists():
            return Response(
                {"detail": f"No step with order {step_order} in this path."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        progress.current_step_order = step_order
        progress.last_activity_at = timezone.now()
        
        if progress.status == PersonalizedPathProgress.Status.NOT_STARTED:
            progress.status = PersonalizedPathProgress.Status.IN_PROGRESS
            progress.started_at = timezone.now()
        
        progress.save()
        
        serializer = self.get_serializer(progress)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Complete Path",
        description="Mark a personalized path as completed."
    )
    @action(detail=True, methods=['post'], url_path='complete')
    def complete_path(self, request, pk=None):
        """Mark the path as completed."""
        progress = self.get_object()
        user = request.user
        
        if progress.user != user and not user.is_staff:
            return Response(
                {"detail": "You can only manage your own progress."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        progress.status = PersonalizedPathProgress.Status.COMPLETED
        progress.completed_at = timezone.now()
        progress.last_activity_at = timezone.now()
        progress.save()
        
        # Also update the path status if it was active
        if progress.path.status == PersonalizedLearningPath.Status.ACTIVE:
            progress.path.status = PersonalizedLearningPath.Status.COMPLETED
            progress.path.save()
        
        serializer = self.get_serializer(progress)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Pause Path",
        description="Pause progress on a personalized path."
    )
    @action(detail=True, methods=['post'], url_path='pause')
    def pause_path(self, request, pk=None):
        """Pause progress on the path."""
        progress = self.get_object()
        user = request.user
        
        if progress.user != user and not user.is_staff:
            return Response(
                {"detail": "You can only manage your own progress."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if progress.status == PersonalizedPathProgress.Status.IN_PROGRESS:
            progress.status = PersonalizedPathProgress.Status.PAUSED
            progress.last_activity_at = timezone.now()
            progress.save()
        
        serializer = self.get_serializer(progress)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Resume Path",
        description="Resume progress on a paused personalized path."
    )
    @action(detail=True, methods=['post'], url_path='resume')
    def resume_path(self, request, pk=None):
        """Resume a paused path."""
        progress = self.get_object()
        user = request.user
        
        if progress.user != user and not user.is_staff:
            return Response(
                {"detail": "You can only manage your own progress."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if progress.status == PersonalizedPathProgress.Status.PAUSED:
            progress.status = PersonalizedPathProgress.Status.IN_PROGRESS
            progress.last_activity_at = timezone.now()
            progress.save()
        
        serializer = self.get_serializer(progress)
        return Response(serializer.data)
