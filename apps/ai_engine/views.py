import logging
import uuid
from rest_framework import generics, permissions, status, viewsets, serializers
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from .models import GenerationJob, ModelConfig, PromptTemplate, GeneratedContent, Tenant # Import Tenant
from .serializers import (
    GenerationJobSerializer, GenerateContentSerializer, ModelConfigSerializer,
    PromptTemplateSerializer, GeneratedContentSerializer
)
from .services import ContentGeneratorService # Import service
from apps.users.permissions import IsAdminOrTenantAdmin
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes


logger = logging.getLogger(__name__)

@extend_schema(
    tags=['AI Engine'],
    summary="Start Content Generation Job",
    description="Initiates an asynchronous AI content generation job using a template or custom prompt.",
    request=GenerateContentSerializer,
    responses={202: GenerationJobSerializer, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT}
)
class StartGenerationJobView(generics.GenericAPIView):
    """ Endpoint to initiate an AI content generation job. """
    serializer_class = GenerateContentSerializer
    permission_classes = [permissions.IsAuthenticated] # TODO: Refine permission (e.g., check tenant feature flag)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            tenant = request.tenant
            user = request.user
            if not tenant:
                # Allow superuser if tenant_id is part of context? For now, require tenant.
                return Response({"detail": "Tenant context required."}, status=status.HTTP_400_BAD_REQUEST)

            # TODO: Check if AI features are enabled for this tenant via tenant.feature_flags

            template = None
            model_config = None

            template_id = serializer.validated_data.get('prompt_template_id')
            if template_id:
                # Ensure template belongs to the user's tenant
                template = get_object_or_404(PromptTemplate, pk=template_id, tenant=tenant)

            model_config_id = serializer.validated_data.get('model_config_id')
            if model_config_id:
                # Ensure config belongs to the user's tenant
                model_config = get_object_or_404(ModelConfig, pk=model_config_id, tenant=tenant)

            try:
                job = ContentGeneratorService.start_generation_job(
                    tenant=tenant,
                    user=user,
                    prompt_template=template,
                    model_config=model_config, # Service handles default logic
                    input_context=serializer.validated_data['input_context'],
                    generation_params=serializer.validated_data.get('generation_params'),
                    # custom_prompt=serializer.validated_data.get('custom_prompt')
                )
                # Pass context to serializer if it needs request
                job_serializer = GenerationJobSerializer(job, context={'request': request})
                # Return 202 Accepted as job is processed async
                return Response(job_serializer.data, status=status.HTTP_202_ACCEPTED)
            except ValueError as e: # Catch validation errors from service
                 return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                 logger.error(f"Error starting generation job: {e}", exc_info=True)
                 return Response({"detail": "An unexpected error occurred."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=['AI Engine'])
class GenerationJobViewSet(viewsets.ReadOnlyModelViewSet):
    """ API endpoint for viewing AI Generation Jobs. """
    serializer_class = GenerationJobSerializer
    permission_classes = [permissions.IsAuthenticated] # Permissions checked in queryset

    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return GenerationJob.objects.none()

        user = self.request.user
        tenant = self.request.tenant
        if not tenant and not user.is_superuser:
            return GenerationJob.objects.none()

        if user.is_superuser:
             return GenerationJob.objects.all().select_related('tenant', 'user', 'prompt_template', 'model_config_used')
        elif user.is_staff: # Tenant admin sees all jobs in tenant
             return GenerationJob.objects.filter(tenant=tenant).select_related('tenant', 'user', 'prompt_template', 'model_config_used')
        else: # Regular user sees their own jobs
             return GenerationJob.objects.filter(tenant=tenant, user=user).select_related('tenant', 'user', 'prompt_template', 'model_config_used')


@extend_schema(tags=['AI Engine'])
class GeneratedContentViewSet(viewsets.ModelViewSet):
    """ API endpoint for viewing and evaluating AI Generated Content. Update only affects evaluation fields. """
    serializer_class = GeneratedContentSerializer
    permission_classes = [permissions.IsAuthenticated] # Refined below

    # Allow only Read and Partial Update (for evaluation fields)
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return GeneratedContent.objects.none()

        user = self.request.user
        tenant = self.request.tenant
        if not tenant and not user.is_superuser:
            return GeneratedContent.objects.none()

        # Allow filtering by job_id
        job_id = self.request.query_params.get('job_id')
        queryset = GeneratedContent.objects.none() # Default empty

        if user.is_superuser:
             queryset = GeneratedContent.objects.all()
        elif user.is_staff: # Tenant admin sees all generated content in tenant
             queryset = GeneratedContent.objects.filter(tenant=tenant)
        else: # Regular user sees content from their jobs
             queryset = GeneratedContent.objects.filter(tenant=tenant, user=user)

        if job_id:
            try:
                queryset = queryset.filter(job_id=uuid.UUID(job_id))
            except ValueError:
                 return GeneratedContent.objects.none() # Invalid job ID format

        return queryset.select_related('tenant', 'user', 'job')

    def get_permissions(self):
        # Check if user owns the job associated with the content or is admin
        if self.action in ['partial_update']:
            # Need object-level permission check (e.g., IsOwnerOrAdmin of the Job/Content)
            # Simplified: Allow owner or tenant admin to update evaluation
            return [permissions.IsAuthenticated()] # TODO: Add IsOwnerOrAdmin check
        return [permissions.IsAuthenticated()]

    def perform_update(self, serializer):
        # Ensure only evaluation fields are updated
        allowed_fields = {'is_accepted', 'rating', 'evaluation_feedback'}
        update_data = {}
        has_allowed_update = False
        for field in allowed_fields:
            if field in serializer.validated_data:
                update_data[field] = serializer.validated_data[field]
                has_allowed_update = True

        if not has_allowed_update:
             raise serializers.ValidationError("Only evaluation fields (is_accepted, rating, evaluation_feedback) can be updated.")

        # Perform permission check before saving (e.g., is request.user owner or admin?)
        instance = self.get_object() # Get instance before save
        # if not (instance.user == self.request.user or self.request.user.is_staff):
        #      raise PermissionDenied("You do not have permission to evaluate this content.")

        # Save only the allowed fields
        serializer.save(**update_data)


@extend_schema(tags=['Admin - AI Engine'])
class ModelConfigViewSet(viewsets.ModelViewSet):
    """ API endpoint for managing AI Model Configurations (Admin only). """
    serializer_class = ModelConfigSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrTenantAdmin]

    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return ModelConfig.objects.none()

        user = self.request.user
        tenant = self.request.tenant
        if user.is_superuser:
            return ModelConfig.objects.all().select_related('tenant')
        elif user.is_staff and tenant:
             return ModelConfig.objects.filter(tenant=tenant).select_related('tenant')
        return ModelConfig.objects.none()

    def perform_create(self, serializer):
        tenant = self.request.tenant
        save_tenant = None
        if self.request.user.is_superuser:
            tenant_id = self.request.data.get('tenant')
            if not tenant_id: raise serializers.ValidationError({"tenant": "Tenant required for superuser."})
            save_tenant = get_object_or_404(Tenant, pk=tenant_id)
        elif tenant:
             save_tenant = tenant
        else:
            # Should not happen due to permissions
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Tenant context required.")
        serializer.save(tenant=save_tenant)


@extend_schema(tags=['Admin - AI Engine'])
class PromptTemplateViewSet(viewsets.ModelViewSet):
    """ API endpoint for managing Prompt Templates (Admin only). """
    serializer_class = PromptTemplateSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrTenantAdmin]

    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return PromptTemplate.objects.none()

        user = self.request.user
        tenant = self.request.tenant
        if user.is_superuser:
            return PromptTemplate.objects.all().select_related('tenant', 'default_model_config')
        elif user.is_staff and tenant:
             return PromptTemplate.objects.filter(tenant=tenant).select_related('tenant', 'default_model_config')
        return PromptTemplate.objects.none()

    def get_serializer_context(self):
        # Pass request for tenant validation in serializer if needed
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def perform_create(self, serializer):
        tenant = self.request.tenant
        save_tenant = None
        if self.request.user.is_superuser:
            tenant_id = self.request.data.get('tenant')
            if not tenant_id: raise serializers.ValidationError({"tenant": "Tenant required for superuser."})
            save_tenant = get_object_or_404(Tenant, pk=tenant_id)
        elif tenant:
             save_tenant = tenant
        else:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Tenant context required.")

        # Validate default_model_config belongs to tenant
        model_config = serializer.validated_data.get('default_model_config')
        if model_config and model_config.tenant != save_tenant:
             raise serializers.ValidationError({"default_model_config": "Default model config must belong to the same tenant."})

        serializer.save(tenant=save_tenant)
