from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.core.mail import send_mail, EmailMessage
from django.conf import settings as django_settings
from .models import Tenant, TenantDomain, PlatformSettings, LTIPlatform, SSOConfiguration
from .serializers import (
    TenantSerializer,
    TenantCreateSerializer, 
    TenantUpdateSerializer,
    TenantDomainManagementSerializer,
    PlatformSettingsSerializer,
    GeneralSettingsSerializer,
    StorageSettingsSerializer,
    EmailSettingsSerializer,
    TestEmailSerializer,
    LTIPlatformSerializer,
    LTIPlatformListSerializer,
    LTIPlatformCreateSerializer,
    SSOConfigurationSerializer,
    SSOConfigurationListSerializer,
    SSOProviderTypeSerializer,
)
from apps.users.permissions import IsAdminOrTenantAdmin, IsAdmin
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from rest_framework.pagination import PageNumberPagination
import smtplib
import socket


class TenantPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


@extend_schema(tags=['Admin - Tenants'])
class TenantViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Tenants (Superuser only).
    Provides CRUD operations and additional actions for tenant management.
    """
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    pagination_class = TenantPagination
    
    def get_serializer_class(self):
        if self.action == 'create':
            return TenantCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return TenantUpdateSerializer
        return TenantSerializer
    
    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return Tenant.objects.none()

        user = self.request.user

        if not user.is_authenticated:
            return Tenant.objects.none()

        # Superusers can access all tenants
        if user.is_superuser:
            queryset = Tenant.objects.all()
        else:
            # Tenant admins can only see their own tenant
            tenant = getattr(user, 'tenant', None)
            if tenant:
                queryset = Tenant.objects.filter(pk=tenant.pk)
            else:
                queryset = Tenant.objects.none()

        # Apply filters
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | 
                Q(slug__icontains=search) |
                Q(domains__domain__icontains=search)
            ).distinct()

        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')

        return queryset.order_by('name')
    
    @extend_schema(
        summary="Toggle tenant active status",
        request=None,
        responses={200: TenantSerializer}
    )
    @action(detail=True, methods=['post'], url_path='toggle-status')
    def toggle_status(self, request, pk=None):
        """Toggle the active status of a tenant."""
        tenant = self.get_object()
        tenant.is_active = not tenant.is_active
        tenant.save(update_fields=['is_active'])
        
        serializer = self.get_serializer(tenant)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Manage tenant domains",
        request=TenantDomainManagementSerializer,
        responses={200: {'message': 'string', 'domains_added': 'int', 'domains_removed': 'int'}}
    )
    @action(detail=True, methods=['post'], url_path='manage-domains')
    def manage_domains(self, request, pk=None):
        """Add or remove domains for a tenant."""
        tenant = self.get_object()
        serializer = TenantDomainManagementSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
        domains = serializer.validated_data['domains']
        action_type = serializer.validated_data['action']
        
        domains_added = 0
        domains_removed = 0
        
        if action_type == 'add':
            for domain in domains:
                # Check if domain already exists for any tenant
                if TenantDomain.objects.filter(domain=domain).exists():
                    continue  # Skip existing domains
                    
                TenantDomain.objects.create(
                    tenant=tenant,
                    domain=domain,
                    is_primary=not tenant.domains.exists()  # First domain is primary
                )
                domains_added += 1
                
        elif action_type == 'remove':
            domains_removed = TenantDomain.objects.filter(
                tenant=tenant,
                domain__in=domains
            ).delete()[0]
            
        return Response({
            'message': f'Successfully {action_type}ed domains',
            'domains_added': domains_added,
            'domains_removed': domains_removed
        })
    
    @extend_schema(
        summary="List tenant statistics",
        responses={200: {
            'total_users': 'int',
            'total_courses': 'int', 
            'total_enrollments': 'int',
            'active_users_30d': 'int'
        }}
    )
    @action(detail=True, methods=['get'], url_path='stats')
    def stats(self, request, pk=None):
        """Get statistics for a specific tenant."""
        tenant = self.get_object()
        
        # Import here to avoid circular imports
        from apps.users.models import User
        from apps.courses.models import Course
        from apps.enrollments.models import Enrollment
        from django.utils import timezone
        from datetime import timedelta
        
        thirty_days_ago = timezone.now() - timedelta(days=30)
        
        stats = {
            'total_users': User.objects.filter(tenant=tenant).count(),
            'total_courses': Course.objects.filter(tenant=tenant).count(),
            'total_enrollments': Enrollment.objects.filter(course__tenant=tenant).count(),
            'active_users_30d': User.objects.filter(
                tenant=tenant,
                last_login__gte=thirty_days_ago
            ).count()
        }
        
        return Response(stats)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "results": serializer.data,
            "count": queryset.count(),
            "next": None,
            "previous": None
        })


@extend_schema(tags=['Admin - Platform Settings'])
class PlatformSettingsViewSet(viewsets.ViewSet):
    """
    API endpoint for managing platform settings.
    Uses singleton pattern - get/update operations on a single settings instance.
    """
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    def _get_settings(self, request):
        """Get settings for the current tenant or global settings."""
        tenant = getattr(request.user, 'tenant', None)
        return PlatformSettings.get_settings(tenant)

    @extend_schema(
        summary="Get all platform settings",
        responses={200: PlatformSettingsSerializer}
    )
    def list(self, request):
        """Retrieve all platform settings."""
        settings = self._get_settings(request)
        serializer = PlatformSettingsSerializer(settings)
        return Response(serializer.data)

    @extend_schema(
        summary="Update platform settings",
        request=PlatformSettingsSerializer,
        responses={200: PlatformSettingsSerializer}
    )
    def partial_update(self, request, pk=None):
        """Update platform settings (partial update)."""
        settings = self._get_settings(request)
        serializer = PlatformSettingsSerializer(settings, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Get general settings",
        responses={200: GeneralSettingsSerializer}
    )
    @action(detail=False, methods=['get'], url_path='general')
    def general(self, request):
        """Retrieve general platform settings."""
        settings = self._get_settings(request)
        serializer = GeneralSettingsSerializer(settings)
        return Response(serializer.data)

    @extend_schema(
        summary="Update general settings",
        request=GeneralSettingsSerializer,
        responses={200: GeneralSettingsSerializer}
    )
    @action(detail=False, methods=['patch'], url_path='general')
    def update_general(self, request):
        """Update general platform settings."""
        settings = self._get_settings(request)
        serializer = GeneralSettingsSerializer(settings, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Get storage settings",
        responses={200: StorageSettingsSerializer}
    )
    @action(detail=False, methods=['get'], url_path='storage')
    def storage(self, request):
        """Retrieve storage settings."""
        settings = self._get_settings(request)
        serializer = StorageSettingsSerializer(settings)
        return Response(serializer.data)

    @extend_schema(
        summary="Update storage settings",
        request=StorageSettingsSerializer,
        responses={200: StorageSettingsSerializer}
    )
    @action(detail=False, methods=['patch'], url_path='storage')
    def update_storage(self, request):
        """Update storage settings."""
        settings = self._get_settings(request)
        serializer = StorageSettingsSerializer(settings, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Test storage connection",
        responses={
            200: {'type': 'object', 'properties': {'success': {'type': 'boolean'}, 'message': {'type': 'string'}}},
            400: {'type': 'object', 'properties': {'success': {'type': 'boolean'}, 'message': {'type': 'string'}}}
        }
    )
    @action(detail=False, methods=['post'], url_path='storage/test')
    def test_storage(self, request):
        """Test storage connection with current settings."""
        settings = self._get_settings(request)
        
        try:
            if settings.storage_backend == PlatformSettings.StorageBackend.LOCAL:
                return Response({
                    'success': True,
                    'message': 'Local storage is configured and ready.'
                })
            
            elif settings.storage_backend == PlatformSettings.StorageBackend.S3:
                if not settings.s3_bucket_name or not settings.s3_access_key_id:
                    return Response({
                        'success': False,
                        'message': 'S3 bucket name and access key are required.'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # Test S3 connection
                try:
                    import boto3
                    from botocore.exceptions import ClientError, NoCredentialsError
                    
                    client_kwargs = {
                        'aws_access_key_id': settings.s3_access_key_id,
                        'aws_secret_access_key': settings.s3_secret_access_key,
                        'region_name': settings.s3_region or 'us-east-1',
                    }
                    if settings.s3_endpoint_url:
                        client_kwargs['endpoint_url'] = settings.s3_endpoint_url
                    
                    s3 = boto3.client('s3', **client_kwargs)
                    s3.head_bucket(Bucket=settings.s3_bucket_name)
                    
                    return Response({
                        'success': True,
                        'message': f'Successfully connected to S3 bucket: {settings.s3_bucket_name}'
                    })
                except ImportError:
                    return Response({
                        'success': False,
                        'message': 'boto3 library is not installed. Please install it to use S3 storage.'
                    }, status=status.HTTP_400_BAD_REQUEST)
                except (ClientError, NoCredentialsError) as e:
                    return Response({
                        'success': False,
                        'message': f'S3 connection failed: {str(e)}'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            elif settings.storage_backend == PlatformSettings.StorageBackend.GCS:
                if not settings.gcs_bucket_name:
                    return Response({
                        'success': False,
                        'message': 'GCS bucket name is required.'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                try:
                    from google.cloud import storage as gcs_storage
                    from google.cloud.exceptions import NotFound
                    
                    client = gcs_storage.Client(project=settings.gcs_project_id)
                    bucket = client.get_bucket(settings.gcs_bucket_name)
                    
                    return Response({
                        'success': True,
                        'message': f'Successfully connected to GCS bucket: {settings.gcs_bucket_name}'
                    })
                except ImportError:
                    return Response({
                        'success': False,
                        'message': 'google-cloud-storage library is not installed.'
                    }, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    return Response({
                        'success': False,
                        'message': f'GCS connection failed: {str(e)}'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            elif settings.storage_backend == PlatformSettings.StorageBackend.AZURE:
                if not settings.azure_container_name or not settings.azure_account_name:
                    return Response({
                        'success': False,
                        'message': 'Azure container name and account name are required.'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                try:
                    from azure.storage.blob import BlobServiceClient
                    
                    connection_string = (
                        f"DefaultEndpointsProtocol=https;"
                        f"AccountName={settings.azure_account_name};"
                        f"AccountKey={settings.azure_account_key};"
                        f"EndpointSuffix=core.windows.net"
                    )
                    blob_service = BlobServiceClient.from_connection_string(connection_string)
                    container = blob_service.get_container_client(settings.azure_container_name)
                    container.get_container_properties()
                    
                    return Response({
                        'success': True,
                        'message': f'Successfully connected to Azure container: {settings.azure_container_name}'
                    })
                except ImportError:
                    return Response({
                        'success': False,
                        'message': 'azure-storage-blob library is not installed.'
                    }, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    return Response({
                        'success': False,
                        'message': f'Azure connection failed: {str(e)}'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            return Response({
                'success': False,
                'message': f'Unknown storage backend: {settings.storage_backend}'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Storage test failed: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @extend_schema(
        summary="Get email settings",
        responses={200: EmailSettingsSerializer}
    )
    @action(detail=False, methods=['get'], url_path='email')
    def email(self, request):
        """Retrieve email/SMTP settings."""
        settings = self._get_settings(request)
        serializer = EmailSettingsSerializer(settings)
        return Response(serializer.data)

    @extend_schema(
        summary="Update email settings",
        request=EmailSettingsSerializer,
        responses={200: EmailSettingsSerializer}
    )
    @action(detail=False, methods=['patch'], url_path='email')
    def update_email(self, request):
        """Update email/SMTP settings."""
        settings = self._get_settings(request)
        serializer = EmailSettingsSerializer(settings, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Send test email",
        request=TestEmailSerializer,
        responses={
            200: {'type': 'object', 'properties': {'success': {'type': 'boolean'}, 'message': {'type': 'string'}}},
            400: {'type': 'object', 'properties': {'success': {'type': 'boolean'}, 'message': {'type': 'string'}}}
        }
    )
    @action(detail=False, methods=['post'], url_path='email/test')
    def test_email(self, request):
        """Send a test email using current SMTP settings."""
        serializer = TestEmailSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        settings = self._get_settings(request)
        recipient = serializer.validated_data['recipient_email']
        
        if not settings.smtp_host:
            return Response({
                'success': False,
                'message': 'SMTP host is not configured.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Create SMTP connection with custom settings
            if settings.smtp_use_ssl:
                server = smtplib.SMTP_SSL(
                    settings.smtp_host,
                    settings.smtp_port,
                    timeout=settings.email_timeout
                )
            else:
                server = smtplib.SMTP(
                    settings.smtp_host,
                    settings.smtp_port,
                    timeout=settings.email_timeout
                )
                if settings.smtp_use_tls:
                    server.starttls()
            
            if settings.smtp_username and settings.smtp_password:
                server.login(settings.smtp_username, settings.smtp_password)
            
            from_email = settings.default_from_email or f"noreply@{settings.smtp_host}"
            from_name = settings.default_from_name or settings.site_name or "LMS Platform"
            
            # Construct email
            subject = f"Test Email from {from_name}"
            body = (
                f"This is a test email from {from_name}.\n\n"
                f"If you received this email, your SMTP settings are configured correctly.\n\n"
                f"SMTP Server: {settings.smtp_host}:{settings.smtp_port}\n"
                f"TLS: {'Yes' if settings.smtp_use_tls else 'No'}\n"
                f"SSL: {'Yes' if settings.smtp_use_ssl else 'No'}"
            )
            
            msg = f"Subject: {subject}\nFrom: {from_name} <{from_email}>\nTo: {recipient}\n\n{body}"
            
            server.sendmail(from_email, [recipient], msg)
            server.quit()
            
            return Response({
                'success': True,
                'message': f'Test email sent successfully to {recipient}'
            })
            
        except socket.timeout:
            return Response({
                'success': False,
                'message': f'Connection timed out after {settings.email_timeout} seconds.'
            }, status=status.HTTP_400_BAD_REQUEST)
        except smtplib.SMTPAuthenticationError:
            return Response({
                'success': False,
                'message': 'SMTP authentication failed. Please check your username and password.'
            }, status=status.HTTP_400_BAD_REQUEST)
        except smtplib.SMTPConnectError as e:
            return Response({
                'success': False,
                'message': f'Could not connect to SMTP server: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Failed to send test email: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class LTIPlatformPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50


@extend_schema(tags=['Admin - LTI Integration'])
class LTIPlatformViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing LTI Platform configurations.
    Provides CRUD operations for LTI 1.3 platform registrations.
    """
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    pagination_class = LTIPlatformPagination

    def get_serializer_class(self):
        if self.action == 'create':
            return LTIPlatformCreateSerializer
        elif self.action == 'list':
            return LTIPlatformListSerializer
        return LTIPlatformSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return LTIPlatform.objects.none()

        user = self.request.user
        if not user.is_authenticated:
            return LTIPlatform.objects.none()

        # Superusers can access all LTI platforms
        if user.is_superuser:
            queryset = LTIPlatform.objects.all()
        else:
            # Tenant admins can only see their own tenant's LTI platforms
            tenant = getattr(user, 'tenant', None)
            if tenant:
                queryset = LTIPlatform.objects.filter(tenant=tenant)
            else:
                return LTIPlatform.objects.none()

        # Search filter
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(issuer__icontains=search) |
                Q(client_id__icontains=search)
            )

        # Active filter
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')

        return queryset.select_related('tenant').order_by('-created_at')

    @extend_schema(
        summary="Toggle LTI platform active status",
        request=None,
        responses={200: LTIPlatformSerializer}
    )
    @action(detail=True, methods=['post'], url_path='toggle-status')
    def toggle_status(self, request, pk=None):
        """Toggle the active status of an LTI platform."""
        platform = self.get_object()
        platform.is_active = not platform.is_active
        platform.save(update_fields=['is_active'])
        serializer = LTIPlatformSerializer(platform)
        return Response(serializer.data)

    @extend_schema(
        summary="Regenerate RSA key pair",
        request=None,
        responses={200: {'message': 'string', 'public_key': 'string'}}
    )
    @action(detail=True, methods=['post'], url_path='regenerate-keys')
    def regenerate_keys(self, request, pk=None):
        """Regenerate RSA key pair for an LTI platform."""
        platform = self.get_object()

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.backends import default_backend

        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )

        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode('utf-8')

        public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')

        platform.tool_private_key = private_pem
        platform.tool_public_key = public_pem
        platform.save(update_fields=['tool_private_key', 'tool_public_key'])

        return Response({
            'message': 'RSA key pair regenerated successfully.',
            'public_key': public_pem
        })

    @extend_schema(
        summary="Get LTI platform public key (JWKS format)",
        responses={200: {'keys': 'array'}}
    )
    @action(detail=True, methods=['get'], url_path='jwks')
    def jwks(self, request, pk=None):
        """Get the public key in JWKS format for tool configuration."""
        platform = self.get_object()

        if not platform.tool_public_key:
            return Response({
                'error': 'No public key configured for this platform.'
            }, status=status.HTTP_400_BAD_REQUEST)

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.backends import default_backend
        import base64

        try:
            public_key = serialization.load_pem_public_key(
                platform.tool_public_key.encode('utf-8'),
                backend=default_backend()
            )

            # Get RSA numbers
            numbers = public_key.public_numbers()

            # Convert to Base64URL encoding
            def int_to_base64url(n, length=None):
                data = n.to_bytes((n.bit_length() + 7) // 8, byteorder='big')
                if length and len(data) < length:
                    data = b'\x00' * (length - len(data)) + data
                return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')

            jwk = {
                'kty': 'RSA',
                'alg': 'RS256',
                'use': 'sig',
                'kid': str(platform.id),
                'n': int_to_base64url(numbers.n),
                'e': int_to_base64url(numbers.e),
            }

            return Response({'keys': [jwk]})

        except Exception as e:
            return Response({
                'error': f'Failed to generate JWKS: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SSOConfigurationPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50


@extend_schema(tags=['Admin - SSO Integration'])
class SSOConfigurationViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing SSO configurations.
    Provides CRUD operations for SAML and OAuth/OIDC configurations.
    """
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    pagination_class = SSOConfigurationPagination

    def get_serializer_class(self):
        if self.action == 'list':
            return SSOConfigurationListSerializer
        elif self.action == 'provider_types':
            return SSOProviderTypeSerializer
        return SSOConfigurationSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return SSOConfiguration.objects.none()

        user = self.request.user
        if not user.is_authenticated:
            return SSOConfiguration.objects.none()

        # Superusers can access all SSO configurations
        if user.is_superuser:
            queryset = SSOConfiguration.objects.all()
        else:
            # Tenant admins can only see their own tenant's SSO configurations
            tenant = getattr(user, 'tenant', None)
            if tenant:
                queryset = SSOConfiguration.objects.filter(tenant=tenant)
            else:
                return SSOConfiguration.objects.none()

        # Search filter
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(name__icontains=search)

        # Provider type filter
        provider_type = self.request.query_params.get('provider_type')
        if provider_type:
            queryset = queryset.filter(provider_type=provider_type)

        # Active filter
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')

        return queryset.select_related('tenant').order_by('-created_at')

    @extend_schema(
        summary="List available SSO provider types",
        responses={200: SSOProviderTypeSerializer(many=True)}
    )
    @action(detail=False, methods=['get'], url_path='provider-types')
    def provider_types(self, request):
        """List available SSO provider types."""
        types = [
            {'value': choice.value, 'label': choice.label}
            for choice in SSOConfiguration.ProviderType
        ]
        return Response(types)

    @extend_schema(
        summary="Toggle SSO configuration active status",
        request=None,
        responses={200: SSOConfigurationSerializer}
    )
    @action(detail=True, methods=['post'], url_path='toggle-status')
    def toggle_status(self, request, pk=None):
        """Toggle the active status of an SSO configuration."""
        config = self.get_object()
        config.is_active = not config.is_active
        config.save(update_fields=['is_active'])
        serializer = SSOConfigurationSerializer(config)
        return Response(serializer.data)

    @extend_schema(
        summary="Set as default SSO configuration",
        request=None,
        responses={200: SSOConfigurationSerializer}
    )
    @action(detail=True, methods=['post'], url_path='set-default')
    def set_default(self, request, pk=None):
        """Set this configuration as the default for its tenant."""
        config = self.get_object()

        # Unset other defaults for this tenant
        SSOConfiguration.objects.filter(
            tenant=config.tenant, is_default=True
        ).exclude(pk=config.pk).update(is_default=False)

        config.is_default = True
        config.save(update_fields=['is_default'])
        serializer = SSOConfigurationSerializer(config)
        return Response(serializer.data)

    @extend_schema(
        summary="Test SSO configuration",
        responses={
            200: {'type': 'object', 'properties': {'success': 'boolean', 'message': 'string', 'details': 'object'}},
            400: {'type': 'object', 'properties': {'success': 'boolean', 'message': 'string'}}
        }
    )
    @action(detail=True, methods=['post'], url_path='test')
    def test_connection(self, request, pk=None):
        """Test SSO configuration by validating endpoints and certificates."""
        config = self.get_object()

        import requests

        try:
            if config.provider_type == SSOConfiguration.ProviderType.SAML:
                # Test SAML IdP SSO URL accessibility
                if config.idp_sso_url:
                    response = requests.head(config.idp_sso_url, timeout=10, allow_redirects=True)
                    return Response({
                        'success': True,
                        'message': 'SAML IdP SSO URL is accessible.',
                        'details': {
                            'idp_sso_url_status': response.status_code,
                            'idp_entity_id_set': bool(config.idp_entity_id),
                            'idp_x509_cert_set': bool(config.idp_x509_cert),
                        }
                    })

            else:
                # Test OAuth endpoints
                details = {}

                if config.oauth_authorization_url:
                    try:
                        response = requests.head(config.oauth_authorization_url, timeout=10, allow_redirects=True)
                        details['authorization_url_status'] = response.status_code
                    except requests.RequestException:
                        details['authorization_url_status'] = 'unreachable'

                if config.oauth_token_url:
                    try:
                        response = requests.head(config.oauth_token_url, timeout=10, allow_redirects=True)
                        details['token_url_status'] = response.status_code
                    except requests.RequestException:
                        details['token_url_status'] = 'unreachable'

                details['client_id_set'] = bool(config.oauth_client_id)
                details['client_secret_set'] = bool(config.oauth_client_secret)

                return Response({
                    'success': True,
                    'message': 'OAuth configuration validated.',
                    'details': details
                })

        except requests.Timeout:
            return Response({
                'success': False,
                'message': 'Connection timed out while testing SSO endpoint.'
            }, status=status.HTTP_400_BAD_REQUEST)
        except requests.RequestException as e:
            return Response({
                'success': False,
                'message': f'Failed to connect to SSO endpoint: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Configuration test failed: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)