import logging
import uuid
from rest_framework import generics, permissions, status, viewsets, serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404

from .models import GenerationJob, ModelConfig, PromptTemplate, GeneratedContent, Tenant # Import Tenant
from .serializers import (
    GenerationJobSerializer, GenerateContentSerializer, ModelConfigSerializer,
    PromptTemplateSerializer, GeneratedContentSerializer
)
from .services import ContentGeneratorService, PersonalizationService # Import services
from apps.users.permissions import IsAdminOrTenantAdmin
from apps.common.permissions import IsOwnerOrAdmin
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse, OpenApiExample
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
    permission_classes = [permissions.IsAuthenticated]  # Tenant feature flag checked in post()

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            tenant = request.tenant
            user = request.user
            if not tenant:
                # Allow superuser if tenant_id is part of context? For now, require tenant.
                return Response({"detail": "Tenant context required."}, status=status.HTTP_400_BAD_REQUEST)

            # Check if AI features are enabled for this tenant
            if not tenant.feature_flags.get('ai_enabled', False):
                return Response(
                    {"detail": "AI features are not enabled for this tenant."},
                    status=status.HTTP_403_FORBIDDEN
                )

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
            # Require owner or admin permission for updates
            return [permissions.IsAuthenticated(), IsOwnerOrAdmin()]
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

        # Perform permission check before saving (already checked by IsOwnerOrAdmin but double-check)
        instance = self.get_object()
        # Permission check is handled by IsOwnerOrAdmin in get_permissions()

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


# ============================================================================
# Module Recommendation Views
# ============================================================================

@extend_schema(
    tags=['AI Recommendations'],
    summary="Get Module Recommendations",
    description="""
    Get personalized module recommendations for the authenticated user.
    
    The recommender considers:
    - User's current skill proficiencies and gaps
    - Module prerequisites (ensuring readiness)
    - What similar learners have completed successfully
    - Target skills the user wants to develop
    
    Query parameters allow customization of the recommendation algorithm weights
    and filtering options.
    """,
    parameters=[
        OpenApiParameter(
            name='limit',
            type=OpenApiTypes.INT,
            location=OpenApiParameter.QUERY,
            description='Number of recommendations to return (default: 10)',
            required=False
        ),
        OpenApiParameter(
            name='course_id',
            type=OpenApiTypes.UUID,
            location=OpenApiParameter.QUERY,
            description='Filter recommendations to a specific course',
            required=False
        ),
        OpenApiParameter(
            name='target_skills',
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            description='Comma-separated skill IDs to focus recommendations on',
            required=False
        ),
        OpenApiParameter(
            name='exclude_completed',
            type=OpenApiTypes.BOOL,
            location=OpenApiParameter.QUERY,
            description='Whether to exclude completed modules (default: true)',
            required=False
        ),
        OpenApiParameter(
            name='check_prerequisites',
            type=OpenApiTypes.BOOL,
            location=OpenApiParameter.QUERY,
            description='Whether to filter by prerequisites (default: true)',
            required=False
        ),
        OpenApiParameter(
            name='skill_weight',
            type=OpenApiTypes.FLOAT,
            location=OpenApiParameter.QUERY,
            description='Weight for skill-based scoring 0-1 (default: 0.5)',
            required=False
        ),
        OpenApiParameter(
            name='collaborative_weight',
            type=OpenApiTypes.FLOAT,
            location=OpenApiParameter.QUERY,
            description='Weight for collaborative filtering 0-1 (default: 0.3)',
            required=False
        ),
        OpenApiParameter(
            name='popularity_weight',
            type=OpenApiTypes.FLOAT,
            location=OpenApiParameter.QUERY,
            description='Weight for popularity scoring 0-1 (default: 0.2)',
            required=False
        ),
    ],
    responses={
        200: OpenApiResponse(
            description='List of recommended modules',
            examples=[
                OpenApiExample(
                    'Success',
                    value={
                        'count': 3,
                        'recommendations': [
                            {
                                'type': 'module',
                                'id': '123e4567-e89b-12d3-a456-426614174000',
                                'title': 'Introduction to Python',
                                'score': 0.85,
                                'reason': 'Addresses Python skill gap',
                                'course_id': '123e4567-e89b-12d3-a456-426614174001',
                                'course_title': 'Programming Fundamentals',
                                'skills': ['Python', 'Programming Basics']
                            }
                        ]
                    }
                )
            ]
        ),
        403: OpenApiTypes.OBJECT,
    }
)
class ModuleRecommendationsView(APIView):
    """
    API endpoint for getting personalized module recommendations.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        
        # Parse query parameters
        try:
            limit = int(request.query_params.get('limit', 10))
            limit = min(max(limit, 1), 50)  # Clamp between 1 and 50
        except ValueError:
            limit = 10
        
        course_id = request.query_params.get('course_id')
        target_skills_param = request.query_params.get('target_skills', '')
        target_skills = [s.strip() for s in target_skills_param.split(',') if s.strip()] if target_skills_param else []
        
        exclude_completed = request.query_params.get('exclude_completed', 'true').lower() != 'false'
        check_prerequisites = request.query_params.get('check_prerequisites', 'true').lower() != 'false'
        
        try:
            skill_weight = float(request.query_params.get('skill_weight', 0.5))
            skill_weight = min(max(skill_weight, 0), 1)
        except ValueError:
            skill_weight = 0.5
        
        try:
            collaborative_weight = float(request.query_params.get('collaborative_weight', 0.3))
            collaborative_weight = min(max(collaborative_weight, 0), 1)
        except ValueError:
            collaborative_weight = 0.3
        
        try:
            popularity_weight = float(request.query_params.get('popularity_weight', 0.2))
            popularity_weight = min(max(popularity_weight, 0), 1)
        except ValueError:
            popularity_weight = 0.2
        
        # Build context for the service
        context = {
            'limit': limit,
            'course_id': course_id,
            'target_skills': target_skills,
            'exclude_completed': exclude_completed,
            'check_prerequisites': check_prerequisites,
            'skill_weight': skill_weight,
            'collaborative_weight': collaborative_weight,
            'popularity_weight': popularity_weight,
        }
        
        # Get recommendations
        recommendations = PersonalizationService.recommend_modules(user, context)
        
        return Response({
            'count': len(recommendations),
            'recommendations': recommendations
        }, status=status.HTTP_200_OK)


@extend_schema(
    tags=['AI Recommendations'],
    summary="Get Learning Sequence",
    description="""
    Generate an optimal learning sequence of modules for the authenticated user.
    
    Creates a structured learning path that:
    - Respects module prerequisites (topological ordering)
    - Prioritizes addressing the biggest skill gaps first
    - Builds progressively from foundational to advanced content
    
    The response includes estimated skill gains from completing the sequence.
    """,
    parameters=[
        OpenApiParameter(
            name='course_id',
            type=OpenApiTypes.UUID,
            location=OpenApiParameter.QUERY,
            description='Limit modules to a specific course',
            required=False
        ),
        OpenApiParameter(
            name='target_skills',
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            description='Comma-separated skill IDs to optimize the sequence for',
            required=False
        ),
        OpenApiParameter(
            name='max_modules',
            type=OpenApiTypes.INT,
            location=OpenApiParameter.QUERY,
            description='Maximum modules in sequence (default: 10, max: 25)',
            required=False
        ),
    ],
    responses={
        200: OpenApiResponse(
            description='Ordered learning sequence',
            examples=[
                OpenApiExample(
                    'Success',
                    value={
                        'sequence': [
                            {
                                'position': 1,
                                'module_id': '123e4567-e89b-12d3-a456-426614174000',
                                'module_title': 'Introduction to Python',
                                'course_id': '123e4567-e89b-12d3-a456-426614174001',
                                'course_title': 'Programming Fundamentals',
                                'score': 0.85,
                                'reason': 'Foundation for later modules',
                                'skills_developed': [
                                    {'skill_name': 'Python', 'proficiency_gained': 15}
                                ]
                            }
                        ],
                        'total_modules': 5,
                        'estimated_skill_gains': {'Python': 45, 'Data Analysis': 30},
                        'skill_gap_analysis': [],
                        'message': 'Learning sequence generated successfully'
                    }
                )
            ]
        ),
        403: OpenApiTypes.OBJECT,
    }
)
class ModuleSequenceView(APIView):
    """
    API endpoint for generating an optimal learning sequence of modules.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        
        # Parse query parameters
        course_id = request.query_params.get('course_id')
        target_skills_param = request.query_params.get('target_skills', '')
        target_skills = [s.strip() for s in target_skills_param.split(',') if s.strip()] if target_skills_param else None
        
        try:
            max_modules = int(request.query_params.get('max_modules', 10))
            max_modules = min(max(max_modules, 1), 25)  # Clamp between 1 and 25
        except ValueError:
            max_modules = 10
        
        # Generate the sequence
        result = PersonalizationService.get_module_sequence(
            user=user,
            course_id=course_id,
            target_skills=target_skills,
            max_modules=max_modules
        )
        
        return Response(result, status=status.HTTP_200_OK)


@extend_schema(
    tags=['AI Recommendations'],
    summary="Get Skill Gap Analysis",
    description="""
    Analyze the user's skill gaps and get module recommendations to address them.
    
    Returns a detailed breakdown of:
    - Current skill proficiency levels
    - Target or expected proficiency levels
    - Gap percentage for each skill
    - Recommended modules to close each gap
    
    This is useful for understanding where the learner needs improvement and
    building targeted learning plans.
    """,
    parameters=[
        OpenApiParameter(
            name='target_skills',
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            description='Comma-separated skill IDs to focus analysis on (optional - analyzes all gaps if not provided)',
            required=False
        ),
    ],
    responses={
        200: OpenApiResponse(
            description='Skill gap analysis with recommended modules',
            examples=[
                OpenApiExample(
                    'Success',
                    value={
                        'count': 3,
                        'skill_gaps': [
                            {
                                'skill_id': '123e4567-e89b-12d3-a456-426614174000',
                                'skill_name': 'Python',
                                'current_proficiency': 25.0,
                                'target_proficiency': 80.0,
                                'gap_percentage': 55.0,
                                'recommended_modules': [
                                    {
                                        'module_id': '123e4567-e89b-12d3-a456-426614174001',
                                        'module_title': 'Advanced Python',
                                        'proficiency_gain': 20.0
                                    }
                                ]
                            }
                        ]
                    }
                )
            ]
        ),
        403: OpenApiTypes.OBJECT,
    }
)
class SkillGapAnalysisView(APIView):
    """
    API endpoint for analyzing skill gaps and recommending modules to address them.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        
        # Parse query parameters
        target_skills_param = request.query_params.get('target_skills', '')
        target_skills = [s.strip() for s in target_skills_param.split(',') if s.strip()] if target_skills_param else None
        
        # Get skill gap analysis
        skill_gaps = PersonalizationService.get_module_skill_gap_analysis(
            user=user,
            target_skills=target_skills
        )
        
        return Response({
            'count': len(skill_gaps),
            'skill_gaps': skill_gaps
        }, status=status.HTTP_200_OK)
