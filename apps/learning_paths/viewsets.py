from rest_framework import viewsets, permissions, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction, models
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from django.utils import timezone
from .models import LearningPath, LearningPathStep, LearningPathProgress, LearningPathStepProgress
from .serializers import (
    LearningPathSerializer,
    LearningPathStepSerializer,
    LearningPathStepOrderSerializer,
    LearningPathProgressSerializer,
    LearningPathStepProgressSerializer,
)
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
        elif self.action in ['update', 'partial_update', 'destroy', 'manage_steps', 'manage_single_step', 'reorder_steps']:
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

            for index, step_id in enumerate(step_ids_in_order):
                 LearningPathStep.objects.filter(id=step_id, learning_path=learning_path).update(order=index + 1)
            return Response({"detail": "Steps reordered successfully."}, status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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
                return LearningPathProgress.objects.filter(
                    learning_path__tenant=tenant
                ).select_related('user', 'learning_path').prefetch_related(
                    'step_progress__step'
                ).order_by('-updated_at')
            else:
                return LearningPathProgress.objects.all().select_related(
                    'user', 'learning_path'
                ).prefetch_related('step_progress__step').order_by('-updated_at')
        else:
            # Regular users see only their own progress
            return LearningPathProgress.objects.filter(user=user).select_related(
                'learning_path'
            ).prefetch_related('step_progress__step').order_by('-updated_at')
    
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
                return LearningPathStepProgress.objects.filter(
                    learning_path_progress__learning_path__tenant=tenant
                ).select_related(
                    'user', 'learning_path_progress', 'step'
                ).order_by('step__order')
            else:
                return LearningPathStepProgress.objects.all().select_related(
                    'user', 'learning_path_progress', 'step'
                ).order_by('step__order')
        else:
            return LearningPathStepProgress.objects.filter(user=user).select_related(
                'learning_path_progress', 'step'
            ).order_by('step__order')
