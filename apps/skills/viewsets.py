"""
ViewSets for the Skills app.

Provides API endpoints for:
- Skill: CRUD operations for skills/competencies
- ModuleSkill: Module-skill mapping management
- LearnerSkillProgress: Learner skill progress tracking
- AssessmentSkillMapping: Assessment question to skill mappings
"""

from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.courses.models import Module
from apps.users.models import User
from apps.users.permissions import IsAdminOrTenantAdmin, IsInstructorOrAdmin

from .models import (
    AssessmentSkillMapping,
    LearnerSkillProgress,
    ModuleSkill,
    Skill,
)
from .serializers import (
    AssessmentSkillMappingBulkCreateSerializer,
    AssessmentSkillMappingSerializer,
    LearnerSkillProgressDetailSerializer,
    LearnerSkillProgressSerializer,
    LearnerSkillSummarySerializer,
    ModuleSkillBulkCreateSerializer,
    ModuleSkillSerializer,
    SkillCreateUpdateSerializer,
    SkillDetailSerializer,
    SkillListSerializer,
)


@extend_schema(tags=['Skills'])
@extend_schema_view(
    list=extend_schema(
        summary="List skills",
        description="Get a list of all skills in the tenant. Supports filtering by category, parent, and active status.",
        parameters=[
            OpenApiParameter(name='category', type=str, description='Filter by category'),
            OpenApiParameter(name='parent', type=str, description='Filter by parent skill ID (use "root" for top-level skills)'),
            OpenApiParameter(name='is_active', type=bool, description='Filter by active status'),
            OpenApiParameter(name='search', type=str, description='Search by name or description'),
        ]
    ),
    retrieve=extend_schema(summary="Get skill details"),
    create=extend_schema(summary="Create a new skill"),
    update=extend_schema(summary="Update a skill"),
    partial_update=extend_schema(summary="Partially update a skill"),
    destroy=extend_schema(summary="Delete a skill"),
)
class SkillViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Skills.
    
    - Instructors/Admins can create, edit, and delete skills
    - All authenticated users can list and view skills
    """
    lookup_field = 'slug'
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Filter skills by tenant and apply query filters."""
        if getattr(self, 'swagger_fake_view', False):
            return Skill.objects.none()

        user = self.request.user
        tenant = self.request.tenant

        if not user.is_authenticated:
            return Skill.objects.none()

        # Base queryset
        if user.is_superuser:
            queryset = Skill.objects.all()
        elif tenant:
            queryset = Skill.objects.filter(tenant=tenant)
        else:
            return Skill.objects.none()

        # Apply filters
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category=category)

        parent = self.request.query_params.get('parent')
        if parent == 'root':
            queryset = queryset.filter(parent__isnull=True)
        elif parent:
            queryset = queryset.filter(parent_id=parent)

        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')

        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(description__icontains=search)
            )

        return queryset.select_related('parent', 'tenant').prefetch_related('children')

    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return SkillListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return SkillCreateUpdateSerializer
        return SkillDetailSerializer

    def get_permissions(self):
        """Assign permissions based on action."""
        if self.action in ['list', 'retrieve']:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), IsInstructorOrAdmin()]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def perform_create(self, serializer):
        """Set tenant from request context."""
        tenant = self.request.tenant
        if not tenant and not self.request.user.is_superuser:
            raise serializers.ValidationError("Tenant context required.")
        serializer.save(tenant=tenant)

    @extend_schema(
        summary="Get skill hierarchy",
        description="Get the full skill hierarchy starting from root skills",
        responses={200: SkillListSerializer(many=True)}
    )
    @action(detail=False, methods=['get'], url_path='hierarchy')
    def hierarchy(self, request):
        """Get skill hierarchy (tree structure)."""
        queryset = self.get_queryset().filter(parent__isnull=True, is_active=True)
        serializer = SkillDetailSerializer(queryset, many=True, context=self.get_serializer_context())
        return Response(serializer.data)

    @extend_schema(
        summary="Get skill categories",
        description="Get all available skill categories with counts",
        responses={200: {'type': 'array', 'items': {'type': 'object'}}}
    )
    @action(detail=False, methods=['get'], url_path='categories')
    def categories(self, request):
        """Get skill categories with counts."""
        queryset = self.get_queryset().filter(is_active=True)
        categories = queryset.values('category').annotate(count=Count('id')).order_by('category')
        
        result = []
        for cat in categories:
            display_name = dict(Skill.Category.choices).get(cat['category'], cat['category'])
            result.append({
                'value': cat['category'],
                'label': display_name,
                'count': cat['count']
            })
        return Response(result)

    @extend_schema(
        summary="Get modules teaching this skill",
        description="Get all modules that teach or develop this skill",
        responses={200: ModuleSkillSerializer(many=True)}
    )
    @action(detail=True, methods=['get'], url_path='modules')
    def modules(self, request, slug=None):
        """Get modules associated with this skill."""
        skill = self.get_object()
        mappings = ModuleSkill.objects.filter(skill=skill).select_related('module')
        serializer = ModuleSkillSerializer(mappings, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="Get learner progress for this skill",
        description="Get aggregated learner progress statistics for this skill",
        responses={200: {'type': 'object'}}
    )
    @action(detail=True, methods=['get'], url_path='progress-stats')
    def progress_stats(self, request, slug=None):
        """Get aggregated progress statistics for a skill."""
        skill = self.get_object()
        progress = LearnerSkillProgress.objects.filter(skill=skill)
        
        stats = progress.aggregate(
            total_learners=Count('id'),
            avg_proficiency=Avg('proficiency_score'),
        )
        
        # Count by proficiency level
        level_counts = progress.values('proficiency_level').annotate(count=Count('id'))
        levels = {item['proficiency_level']: item['count'] for item in level_counts}
        
        return Response({
            'skill_id': str(skill.id),
            'skill_name': skill.name,
            'total_learners': stats['total_learners'] or 0,
            'average_proficiency': round(stats['avg_proficiency'] or 0, 1),
            'learners_by_level': levels
        })


@extend_schema(tags=['Skills'])
@extend_schema_view(
    list=extend_schema(summary="List module-skill mappings"),
    retrieve=extend_schema(summary="Get module-skill mapping details"),
    create=extend_schema(summary="Create a module-skill mapping"),
    update=extend_schema(summary="Update a module-skill mapping"),
    partial_update=extend_schema(summary="Partially update a module-skill mapping"),
    destroy=extend_schema(summary="Delete a module-skill mapping"),
)
class ModuleSkillViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Module-Skill mappings.
    
    These mappings define which skills are taught by each module.
    """
    serializer_class = ModuleSkillSerializer
    permission_classes = [permissions.IsAuthenticated, IsInstructorOrAdmin]

    def get_queryset(self):
        """Filter by tenant through module's course."""
        if getattr(self, 'swagger_fake_view', False):
            return ModuleSkill.objects.none()

        user = self.request.user
        tenant = self.request.tenant

        if not user.is_authenticated:
            return ModuleSkill.objects.none()

        if user.is_superuser:
            queryset = ModuleSkill.objects.all()
        elif tenant:
            queryset = ModuleSkill.objects.filter(module__course__tenant=tenant)
        else:
            return ModuleSkill.objects.none()

        # Filter by module if provided
        module_id = self.request.query_params.get('module')
        if module_id:
            queryset = queryset.filter(module_id=module_id)

        # Filter by skill if provided
        skill_id = self.request.query_params.get('skill')
        if skill_id:
            queryset = queryset.filter(skill_id=skill_id)

        return queryset.select_related('module', 'skill')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    @extend_schema(
        summary="Bulk create module-skill mappings",
        description="Add multiple skills to a module at once",
        request=ModuleSkillBulkCreateSerializer,
        responses={201: ModuleSkillSerializer(many=True)}
    )
    @action(detail=False, methods=['post'], url_path='bulk-create')
    def bulk_create(self, request):
        """Bulk create module-skill mappings."""
        serializer = ModuleSkillBulkCreateSerializer(
            data=request.data,
            context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)

        module_id = request.data.get('module_id')
        module = get_object_or_404(Module, id=module_id)

        # Verify tenant access
        tenant = self.request.tenant
        if tenant and module.course.tenant_id != tenant.id:
            return Response(
                {'error': 'Module not found in tenant'},
                status=status.HTTP_404_NOT_FOUND
            )

        skill_ids = serializer.validated_data['skill_ids']
        contribution_level = serializer.validated_data['contribution_level']
        proficiency_gained = serializer.validated_data['proficiency_gained']

        created = []
        for skill_id in skill_ids:
            obj, was_created = ModuleSkill.objects.get_or_create(
                module=module,
                skill_id=skill_id,
                defaults={
                    'contribution_level': contribution_level,
                    'proficiency_gained': proficiency_gained
                }
            )
            if was_created:
                created.append(obj)

        result_serializer = ModuleSkillSerializer(created, many=True)
        return Response(result_serializer.data, status=status.HTTP_201_CREATED)


@extend_schema(tags=['Skills'])
@extend_schema_view(
    list=extend_schema(
        summary="List learner skill progress",
        description="Get skill progress records. Learners see their own progress; instructors/admins can see all.",
        parameters=[
            OpenApiParameter(name='user', type=str, description='Filter by user ID (admin only)'),
            OpenApiParameter(name='skill', type=str, description='Filter by skill ID'),
            OpenApiParameter(name='min_proficiency', type=int, description='Filter by minimum proficiency score'),
        ]
    ),
    retrieve=extend_schema(summary="Get detailed skill progress"),
)
class LearnerSkillProgressViewSet(viewsets.ModelViewSet):
    """
    API endpoint for tracking Learner Skill Progress.
    
    - Learners can view their own progress
    - Instructors/Admins can view all progress within tenant
    """
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ['get', 'head', 'options']  # Read-only; updates happen via services

    def get_queryset(self):
        """Filter progress by user permissions."""
        if getattr(self, 'swagger_fake_view', False):
            return LearnerSkillProgress.objects.none()

        user = self.request.user
        tenant = self.request.tenant

        if not user.is_authenticated:
            return LearnerSkillProgress.objects.none()

        # Base queryset based on role
        if user.is_superuser:
            queryset = LearnerSkillProgress.objects.all()
        elif user.role in [User.Role.ADMIN, User.Role.INSTRUCTOR] or user.is_staff:
            # Admins/instructors can see progress for users in their tenant
            if tenant:
                queryset = LearnerSkillProgress.objects.filter(
                    skill__tenant=tenant
                )
            else:
                queryset = LearnerSkillProgress.objects.none()
        else:
            # Learners only see their own progress
            queryset = LearnerSkillProgress.objects.filter(user=user)

        # Apply filters
        user_filter = self.request.query_params.get('user')
        if user_filter and (user.is_superuser or user.role in [User.Role.ADMIN, User.Role.INSTRUCTOR]):
            queryset = queryset.filter(user_id=user_filter)

        skill_filter = self.request.query_params.get('skill')
        if skill_filter:
            queryset = queryset.filter(skill_id=skill_filter)

        min_proficiency = self.request.query_params.get('min_proficiency')
        if min_proficiency:
            try:
                queryset = queryset.filter(proficiency_score__gte=int(min_proficiency))
            except ValueError:
                pass

        return queryset.select_related('user', 'skill')

    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'retrieve':
            return LearnerSkillProgressDetailSerializer
        return LearnerSkillProgressSerializer

    @extend_schema(
        summary="Get my skill progress",
        description="Get the current user's skill progress summary",
        responses={200: LearnerSkillSummarySerializer}
    )
    @action(detail=False, methods=['get'], url_path='my-progress')
    def my_progress(self, request):
        """Get current user's skill progress summary."""
        user = request.user
        progress = LearnerSkillProgress.objects.filter(user=user).select_related('skill')

        total_skills = progress.count()
        skills_in_progress = progress.filter(proficiency_score__gt=0, proficiency_score__lt=90).count()
        skills_mastered = progress.filter(proficiency_score__gte=90).count()
        
        avg_proficiency = progress.aggregate(avg=Avg('proficiency_score'))['avg'] or 0

        # Find strongest and weakest categories
        category_stats = progress.values('skill__category').annotate(
            avg_score=Avg('proficiency_score'),
            count=Count('id')
        ).order_by('-avg_score')

        strongest_category = None
        weakest_category = None
        skills_by_category = {}

        for stat in category_stats:
            cat = stat['skill__category']
            skills_by_category[cat] = {
                'average_score': round(stat['avg_score'], 1),
                'count': stat['count']
            }
            if strongest_category is None:
                strongest_category = cat
            weakest_category = cat

        # Get recent improvements (skills with positive trend)
        recent_improvements = []
        for p in progress.order_by('-updated_at')[:10]:
            trend = p.get_progress_trend(days=30)
            if trend['direction'] == 'improving':
                recent_improvements.append({
                    'skill_name': p.skill.name,
                    'skill_id': str(p.skill.id),
                    'total_change': trend['total_change']
                })

        data = {
            'total_skills': total_skills,
            'skills_in_progress': skills_in_progress,
            'skills_mastered': skills_mastered,
            'average_proficiency': round(avg_proficiency, 1),
            'strongest_category': strongest_category,
            'weakest_category': weakest_category,
            'recent_improvements': recent_improvements[:5],
            'skills_by_category': skills_by_category
        }

        serializer = LearnerSkillSummarySerializer(data)
        return Response(serializer.data)

    @extend_schema(
        summary="Get skill gaps",
        description="Identify skills where the user has low proficiency compared to required levels",
        responses={200: {'type': 'array', 'items': {'type': 'object'}}}
    )
    @action(detail=False, methods=['get'], url_path='skill-gaps')
    def skill_gaps(self, request):
        """Identify skills where user needs improvement."""
        user = request.user
        tenant = request.tenant

        # Get all skills in tenant
        all_skills = Skill.objects.filter(tenant=tenant, is_active=True)
        
        # Get user's current progress
        user_progress = {
            str(p.skill_id): p.proficiency_score
            for p in LearnerSkillProgress.objects.filter(user=user)
        }

        gaps = []
        for skill in all_skills:
            current_score = user_progress.get(str(skill.id), 0)
            
            # Consider a gap if score is below intermediate level (50)
            if current_score < 50:
                # Check if this skill is relevant (has module mappings)
                module_count = skill.module_mappings.count()
                if module_count > 0:
                    gaps.append({
                        'skill_id': str(skill.id),
                        'skill_name': skill.name,
                        'skill_slug': skill.slug,
                        'category': skill.category,
                        'current_score': current_score,
                        'target_score': 50,
                        'gap': 50 - current_score,
                        'modules_available': module_count
                    })

        # Sort by gap size (largest gaps first)
        gaps.sort(key=lambda x: x['gap'], reverse=True)
        return Response(gaps[:20])  # Return top 20 gaps


@extend_schema(tags=['Skills'])
@extend_schema_view(
    list=extend_schema(summary="List assessment-skill mappings"),
    retrieve=extend_schema(summary="Get assessment-skill mapping details"),
    create=extend_schema(summary="Create an assessment-skill mapping"),
    update=extend_schema(summary="Update an assessment-skill mapping"),
    partial_update=extend_schema(summary="Partially update an assessment-skill mapping"),
    destroy=extend_schema(summary="Delete an assessment-skill mapping"),
)
class AssessmentSkillMappingViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Assessment-Skill mappings.
    
    These mappings define which skills are evaluated by each assessment question.
    """
    serializer_class = AssessmentSkillMappingSerializer
    permission_classes = [permissions.IsAuthenticated, IsInstructorOrAdmin]

    def get_queryset(self):
        """Filter by tenant through assessment's course."""
        if getattr(self, 'swagger_fake_view', False):
            return AssessmentSkillMapping.objects.none()

        user = self.request.user
        tenant = self.request.tenant

        if not user.is_authenticated:
            return AssessmentSkillMapping.objects.none()

        if user.is_superuser:
            queryset = AssessmentSkillMapping.objects.all()
        elif tenant:
            queryset = AssessmentSkillMapping.objects.filter(
                question__assessment__course__tenant=tenant
            )
        else:
            return AssessmentSkillMapping.objects.none()

        # Filter by question if provided
        question_id = self.request.query_params.get('question')
        if question_id:
            queryset = queryset.filter(question_id=question_id)

        # Filter by assessment if provided
        assessment_id = self.request.query_params.get('assessment')
        if assessment_id:
            queryset = queryset.filter(question__assessment_id=assessment_id)

        # Filter by skill if provided
        skill_id = self.request.query_params.get('skill')
        if skill_id:
            queryset = queryset.filter(skill_id=skill_id)

        return queryset.select_related('question', 'question__assessment', 'skill')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    @extend_schema(
        summary="Bulk create assessment-skill mappings",
        description="Add multiple skill mappings to assessment questions at once",
        request=AssessmentSkillMappingBulkCreateSerializer,
        responses={201: AssessmentSkillMappingSerializer(many=True)}
    )
    @action(detail=False, methods=['post'], url_path='bulk-create')
    def bulk_create(self, request):
        """Bulk create assessment-skill mappings."""
        serializer = AssessmentSkillMappingBulkCreateSerializer(
            data=request.data,
            context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)

        mappings_data = serializer.validated_data['mappings']
        created = []

        for mapping in mappings_data:
            obj, was_created = AssessmentSkillMapping.objects.get_or_create(
                question_id=mapping['question_id'],
                skill_id=mapping['skill_id'],
                defaults={
                    'weight': mapping.get('weight', 1),
                    'proficiency_required': mapping.get(
                        'proficiency_required', 
                        Skill.ProficiencyLevel.BEGINNER
                    ),
                    'proficiency_demonstrated': mapping.get(
                        'proficiency_demonstrated',
                        Skill.ProficiencyLevel.BEGINNER
                    )
                }
            )
            if was_created:
                created.append(obj)

        result_serializer = AssessmentSkillMappingSerializer(created, many=True)
        return Response(result_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Get skills coverage for an assessment",
        description="Get summary of skills covered by an assessment",
        parameters=[
            OpenApiParameter(name='assessment_id', type=str, required=True, description='Assessment ID'),
        ],
        responses={200: {'type': 'object'}}
    )
    @action(detail=False, methods=['get'], url_path='coverage')
    def coverage(self, request):
        """Get skill coverage summary for an assessment."""
        assessment_id = request.query_params.get('assessment_id')
        if not assessment_id:
            return Response(
                {'error': 'assessment_id parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        mappings = self.get_queryset().filter(question__assessment_id=assessment_id)
        
        # Group by skill
        skills_data = {}
        for mapping in mappings:
            skill_id = str(mapping.skill_id)
            if skill_id not in skills_data:
                skills_data[skill_id] = {
                    'skill_id': skill_id,
                    'skill_name': mapping.skill.name,
                    'skill_category': mapping.skill.category,
                    'question_count': 0,
                    'total_weight': 0,
                    'proficiency_levels': set()
                }
            skills_data[skill_id]['question_count'] += 1
            skills_data[skill_id]['total_weight'] += mapping.weight
            skills_data[skill_id]['proficiency_levels'].add(mapping.proficiency_required)

        # Convert sets to lists for JSON serialization
        for skill_id in skills_data:
            skills_data[skill_id]['proficiency_levels'] = list(
                skills_data[skill_id]['proficiency_levels']
            )

        return Response({
            'assessment_id': assessment_id,
            'total_mappings': mappings.count(),
            'skills_covered': len(skills_data),
            'skills': list(skills_data.values())
        })
