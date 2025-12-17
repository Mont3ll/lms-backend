import logging
import uuid
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets, serializers
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied

from .models import Enrollment, GroupEnrollment, LearnerProgress, Certificate, Course, LearnerGroup, User, ContentItem
from .serializers import (
    EnrollmentSerializer, EnrollmentCreateSerializer,
    GroupEnrollmentSerializer, GroupEnrollmentCreateSerializer,
    LearnerProgressSerializer, LearnerProgressUpdateSerializer,
    CertificateSerializer
)
from .services import EnrollmentService, EnrollmentError, ProgressTrackerService
from apps.users.permissions import IsAdminOrTenantAdmin, IsLearner
from apps.courses.permissions import IsEnrolledOrInstructorOrAdmin
# Import OpenApiExample
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse, OpenApiExample
from drf_spectacular.types import OpenApiTypes


logger = logging.getLogger(__name__)

# --- Enrollment Views ---

@extend_schema(tags=['Enrollments'])
class EnrollmentViewSet(viewsets.ReadOnlyModelViewSet):
    """ Lists enrollments. Filterable by user_id and course_id (requires permissions). """
    serializer_class = EnrollmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(name='user_id', description='Filter by User UUID', required=False, type=OpenApiTypes.UUID),
            OpenApiParameter(name='course_id', description='Filter by Course UUID', required=False, type=OpenApiTypes.UUID),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(parameters=[OpenApiParameter(name='id', description='Enrollment UUID', required=True, type=OpenApiTypes.UUID, location=OpenApiParameter.PATH)])
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)


    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Enrollment.objects.none()
        # ... (rest of get_queryset logic remains the same)
        user = self.request.user
        tenant = self.request.tenant
        user_id_filter = self.request.query_params.get('user_id')
        course_id_filter = self.request.query_params.get('course_id')
        queryset = Enrollment.objects.none()
        if user.is_superuser:
            queryset = Enrollment.objects.all()
        elif user.is_staff and tenant:
             queryset = Enrollment.objects.filter(course__tenant=tenant)
        elif user.role == User.Role.INSTRUCTOR and tenant:
            queryset = Enrollment.objects.filter(course__tenant=tenant, course__instructor=user)
        else:
            queryset = Enrollment.objects.filter(user=user)
        if user_id_filter:
            try:
                user_uuid = uuid.UUID(user_id_filter)
                if user.id != user_uuid and not user.is_staff: return Enrollment.objects.none()
                queryset = queryset.filter(user_id=user_uuid)
            except ValueError: return Enrollment.objects.none()
        if course_id_filter:
            try:
                course_uuid = uuid.UUID(course_id_filter)
                course_q = Q(pk=course_uuid)
                if tenant and not user.is_superuser: course_q &= Q(tenant=tenant)
                if not Course.objects.filter(course_q).exists(): return Enrollment.objects.none()
                queryset = queryset.filter(course_id=course_uuid)
            except ValueError: return Enrollment.objects.none()
        return queryset.select_related('user', 'course', 'course__tenant').order_by('-enrolled_at')


@extend_schema(
    tags=['Enrollments'], summary="Admin Enroll User", request=EnrollmentCreateSerializer,
    responses={201: EnrollmentSerializer, 200: EnrollmentSerializer, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT}
)
class CreateEnrollmentView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminOrTenantAdmin]
    def post(self, request, format=None):
        # ... (logic remains the same)
        serializer = EnrollmentCreateSerializer(data=request.data)
        if serializer.is_valid():
            user_id = serializer.validated_data['user_id']
            course_id = serializer.validated_data['course_id']
            status_req = serializer.validated_data['status']
            tenant = request.tenant
            try:
                 user_q = Q(pk=user_id)
                 if not request.user.is_superuser and tenant: user_q &= Q(tenant=tenant)
                 user_to_enroll = User.objects.get(user_q)
                 course_q = Q(pk=course_id)
                 if not request.user.is_superuser and tenant: course_q &= Q(tenant=tenant)
                 course_to_enroll = Course.objects.get(course_q)
            except User.DoesNotExist: return Response({"detail": f"User {user_id} not found."}, status=status.HTTP_404_NOT_FOUND)
            except Course.DoesNotExist: return Response({"detail": f"Course {course_id} not found."}, status=status.HTTP_404_NOT_FOUND)
            is_course_instructor = course_to_enroll.instructor == request.user
            if not (request.user.is_staff or is_course_instructor): return Response({"detail": "No permission."}, status=status.HTTP_403_FORBIDDEN)
            try:
                 enrollment, created = EnrollmentService.enroll_user(user_to_enroll, course_to_enroll, status_req)
                 response_serializer = EnrollmentSerializer(enrollment, context={'request': request})
                 response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
                 return Response(response_serializer.data, status=response_status)
            except EnrollmentError as e: return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            except IntegrityError: return Response({"detail": "Conflict."}, status=status.HTTP_409_CONFLICT)
        else: return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    tags=['Enrollments'], summary="Admin Enroll Group", request=GroupEnrollmentCreateSerializer,
    responses={201: GroupEnrollmentSerializer, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT}
)
class CreateGroupEnrollmentView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminOrTenantAdmin]
    def post(self, request, format=None):
        # ... (logic remains the same)
        serializer = GroupEnrollmentCreateSerializer(data=request.data)
        if serializer.is_valid():
            group_id = serializer.validated_data['group_id']
            course_id = serializer.validated_data['course_id']
            tenant = request.tenant
            try:
                 group_q = Q(pk=group_id); course_q = Q(pk=course_id)
                 if not request.user.is_superuser and tenant: group_q &= Q(tenant=tenant); course_q &= Q(tenant=tenant)
                 group_to_enroll = LearnerGroup.objects.get(group_q)
                 course_to_enroll = Course.objects.get(course_q)
            except LearnerGroup.DoesNotExist: return Response({"detail": f"Group {group_id} not found."}, status=status.HTTP_404_NOT_FOUND)
            except Course.DoesNotExist: return Response({"detail": f"Course {course_id} not found."}, status=status.HTTP_404_NOT_FOUND)
            is_course_instructor_or_admin = request.user.is_staff or (course_to_enroll.instructor == request.user)
            if not is_course_instructor_or_admin: return Response({"detail": "No permission."}, status=status.HTTP_403_FORBIDDEN)
            try:
                 group_enrollment = EnrollmentService.enroll_group(group_to_enroll, course_to_enroll)
                 response_serializer = GroupEnrollmentSerializer(group_enrollment, context={'request': request})
                 return Response(response_serializer.data, status=status.HTTP_201_CREATED)
            except EnrollmentError as e: return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            except IntegrityError: return Response({"detail": "Conflict."}, status=status.HTTP_409_CONFLICT)
        else: return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    tags=['Learner Progress'], summary="List Learner Progress",
    parameters=[OpenApiParameter(name='enrollment_id', required=True, type=OpenApiTypes.UUID, location=OpenApiParameter.PATH)],
    responses={200: LearnerProgressSerializer(many=True), 403: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT}
)
class LearnerProgressListView(generics.ListAPIView):
    serializer_class = LearnerProgressSerializer
    permission_classes = [permissions.IsAuthenticated]
    def get_queryset(self):
        # ... (logic remains the same)
        if getattr(self, 'swagger_fake_view', False): return LearnerProgress.objects.none()
        enrollment_id = self.kwargs.get('enrollment_id')
        user = self.request.user
        try: enrollment = Enrollment.objects.select_related('user', 'course').get(pk=enrollment_id)
        except Enrollment.DoesNotExist: return LearnerProgress.objects.none()
        is_owner = enrollment.user == user
        is_admin_or_instructor = user.is_staff or (enrollment.course.instructor == user)
        if not (is_owner or is_admin_or_instructor): raise PermissionDenied("Cannot view progress.")
        return LearnerProgress.objects.filter(enrollment_id=enrollment_id).select_related('content_item', 'content_item__module', 'enrollment__user').order_by('content_item__module__order', 'content_item__order')


@extend_schema(
    tags=['Learner Progress'], summary="Update Learner Progress",
    parameters=[
        OpenApiParameter(name='enrollment_id', required=True, type=OpenApiTypes.UUID, location=OpenApiParameter.PATH),
        OpenApiParameter(name='content_item_id', required=True, type=OpenApiTypes.UUID, location=OpenApiParameter.PATH),
    ],
    request=LearnerProgressUpdateSerializer,
    responses={200: LearnerProgressSerializer, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT}
)
class UpdateLearnerProgressView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def post(self, request, enrollment_id: uuid.UUID, content_item_id: uuid.UUID, format=None):
        # ... (logic remains the same)
        enrollment = get_object_or_404(Enrollment, pk=enrollment_id, user=request.user)
        content_item = get_object_or_404(ContentItem, pk=content_item_id, module__course=enrollment.course)
        serializer = LearnerProgressUpdateSerializer(data=request.data)
        if serializer.is_valid():
            status_update = serializer.validated_data.get('status')
            details_update = serializer.validated_data.get('progress_details')
            if not status_update and not details_update: return Response({"detail": "No data provided."}, status=status.HTTP_400_BAD_REQUEST)
            try:
                progress, updated = ProgressTrackerService.update_content_progress(enrollment=enrollment, content_item=content_item, status=status_update, details=details_update)
                response_serializer = LearnerProgressSerializer(progress, context={'request': request})
                return Response(response_serializer.data, status=status.HTTP_200_OK)
            except Exception as e:
                 logger.error(f"Error updating progress E:{enrollment.id} C:{content_item.id}: {e}", exc_info=True)
                 return Response({"detail": "Failed to update progress."}, status=status.HTTP_400_BAD_REQUEST)
        else: return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# --- Certificate Views ---

@extend_schema(tags=['Certificates'])
class CertificateViewSet(viewsets.ReadOnlyModelViewSet):
    """ Lists certificates for the current user. """
    serializer_class = CertificateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Certificate.objects.none()
            
        user = self.request.user
        if not user.is_authenticated:
            return Certificate.objects.none()
            
        # Users can only see their own certificates
        return Certificate.objects.filter(user=user).select_related('course').order_by('-issued_at')

    @extend_schema(
        description="List all certificates for the current user",
        responses={200: CertificateSerializer(many=True)}
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        description="Retrieve a specific certificate",
        responses={200: CertificateSerializer}
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        description="Download a certificate PDF file",
        responses={200: "PDF file download"}
    )
    @action(detail=True, methods=['get'], url_path='download')
    def download(self, request, pk=None):
        """Download certificate PDF with proper Content-Disposition header."""
        certificate = self.get_object()
        
        # Generate PDF on-demand if it doesn't exist
        if not certificate.file_url:
            try:
                from .certificate_service import CertificateService as PDFService
                PDFService.generate_certificate_pdf(certificate)
                certificate.refresh_from_db()  # Reload to get updated file_url
                logger.info(f"Generated PDF on-demand for certificate {certificate.id}")
            except Exception as e:
                logger.error(f"Error generating PDF on-demand for certificate {certificate.id}: {e}")
                return Response(
                    {"error": "Failed to generate certificate PDF"}, 
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        
        if not certificate.file_url:
            return Response(
                {"error": "Certificate PDF not available"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        # For local files, serve with download headers
        try:
            from django.http import FileResponse
            from django.conf import settings
            import os
            
            # Extract filename from file_url and sanitize it
            filename = certificate.file_url.split('/')[-1]
            # Remove any path traversal characters
            filename = os.path.basename(filename)
            
            # Validate filename is not empty and doesn't contain dangerous characters
            if not filename or '..' in filename or filename.startswith('/'):
                logger.warning(f"Invalid certificate filename attempted: {certificate.file_url}")
                return Response(
                    {"error": "Invalid certificate file"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            file_path = os.path.join(settings.MEDIA_ROOT, 'certificates', filename)
            
            # Resolve to absolute path and validate it's within MEDIA_ROOT
            real_file_path = os.path.realpath(file_path)
            media_root = os.path.realpath(settings.MEDIA_ROOT)
            
            if not real_file_path.startswith(media_root + os.sep):
                logger.warning(f"Path traversal attempt detected: {certificate.file_url}")
                return Response(
                    {"error": "Invalid certificate file path"}, 
                    status=status.HTTP_403_FORBIDDEN
                )
            
            if os.path.exists(real_file_path):
                # Create a descriptive filename
                safe_course_title = ''.join(c for c in certificate.course.title if c.isalnum() or c in (' ', '-', '_')).rstrip()
                safe_course_title = safe_course_title.replace(' ', '-').lower()
                download_filename = f"certificate-{safe_course_title}.pdf"
                
                response = FileResponse(
                    open(real_file_path, 'rb'),
                    content_type='application/pdf',
                    as_attachment=True,
                    filename=download_filename
                )
                return response
            else:
                return Response(
                    {"error": "Certificate file not found"}, 
                    status=status.HTTP_404_NOT_FOUND
                )
                
        except Exception as e:
            logger.error(f"Error serving certificate download: {e}")
            return Response(
                {"error": "Error downloading certificate"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        description="Verify a certificate using its verification code",
        parameters=[
            OpenApiParameter(
                name='verification_code',
                description='Certificate verification code (UUID)',
                required=True,
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH
            )
        ],
        responses={
            200: OpenApiResponse(
                description="Certificate is valid",
                examples=[
                    OpenApiExample(
                        'Valid Certificate',
                        value={
                            'valid': True,
                            'learner_name': 'John Doe',
                            'course_title': 'Introduction to Python',
                            'issued_at': '2024-01-15T10:30:00Z',
                            'status': 'ISSUED'
                        }
                    )
                ]
            ),
            404: OpenApiResponse(
                description="Certificate not found",
                examples=[
                    OpenApiExample(
                        'Not Found',
                        value={'valid': False, 'detail': 'Certificate not found'}
                    )
                ]
            )
        }
    )
    @action(
        detail=False, 
        methods=['get'], 
        url_path='verify/(?P<verification_code>[^/.]+)',
        permission_classes=[permissions.AllowAny]  # Anyone can verify a certificate
    )
    def verify(self, request, verification_code=None):
        """
        Verify a certificate using its unique verification code.
        This endpoint is public and does not require authentication.
        """
        try:
            # Try to parse as UUID
            code_uuid = uuid.UUID(str(verification_code))
            
            # Look up the certificate
            certificate = Certificate.objects.select_related('user', 'course').filter(
                verification_code=code_uuid
            ).first()
            
            if not certificate:
                return Response(
                    {'valid': False, 'detail': 'Certificate not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Check if certificate is revoked
            if certificate.status == Certificate.Status.REVOKED:
                return Response({
                    'valid': False,
                    'detail': 'This certificate has been revoked',
                    'learner_name': certificate.user.get_full_name() or certificate.user.email,
                    'course_title': certificate.course.title,
                    'issued_at': certificate.issued_at.isoformat() if certificate.issued_at else None,
                    'status': certificate.status
                })
            
            # Check if certificate is expired
            if certificate.expires_at and certificate.expires_at < timezone.now():
                return Response({
                    'valid': False,
                    'detail': 'This certificate has expired',
                    'learner_name': certificate.user.get_full_name() or certificate.user.email,
                    'course_title': certificate.course.title,
                    'issued_at': certificate.issued_at.isoformat() if certificate.issued_at else None,
                    'expires_at': certificate.expires_at.isoformat(),
                    'status': certificate.status
                })
            
            # Certificate is valid
            return Response({
                'valid': True,
                'learner_name': certificate.user.get_full_name() or certificate.user.email,
                'course_title': certificate.course.title,
                'issued_at': certificate.issued_at.isoformat() if certificate.issued_at else None,
                'expires_at': certificate.expires_at.isoformat() if certificate.expires_at else None,
                'status': certificate.status,
                'description': certificate.description or None
            })
            
        except ValueError:
            return Response(
                {'valid': False, 'detail': 'Invalid verification code format'},
                status=status.HTTP_400_BAD_REQUEST
            )
