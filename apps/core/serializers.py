from rest_framework import serializers
from django.utils.text import slugify
from .models import (
    Tenant, TenantDomain, PlatformSettings, LTIPlatform, SSOConfiguration,
    LTILineItem, LTIGradeSubmission, LTIResourceLink
)


class TenantDomainSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantDomain
        fields = ['id', 'domain', 'is_primary', 'created_at']
        read_only_fields = ['id', 'created_at']


class TenantSerializer(serializers.ModelSerializer):
    domains = TenantDomainSerializer(many=True, read_only=True)
    domain_list = serializers.CharField(read_only=True)
    
    class Meta:
        model = Tenant
        fields = [
            'id', 'name', 'slug', 'is_active', 'theme_config', 
            'feature_flags', 'domains', 'domain_list', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'slug', 'domains', 'domain_list', 'created_at', 'updated_at']

    def validate_name(self, value):
        """Ensure name is unique and generate slug."""
        if self.instance:
            # Update case - exclude current instance
            if Tenant.objects.exclude(id=self.instance.id).filter(name=value).exists():
                raise serializers.ValidationError("A tenant with this name already exists.")
        else:
            # Create case
            if Tenant.objects.filter(name=value).exists():
                raise serializers.ValidationError("A tenant with this name already exists.")
        return value

    def create(self, validated_data):
        # Generate slug from name
        name = validated_data['name']
        base_slug = slugify(name)
        slug = base_slug
        counter = 1
        
        # Ensure slug is unique
        while Tenant.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
            
        validated_data['slug'] = slug
        return super().create(validated_data)


class TenantCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating tenants with domains."""
    domains = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        allow_empty=True,
        help_text="List of domain names to associate with this tenant"
    )
    
    class Meta:
        model = Tenant
        fields = ['name', 'is_active', 'theme_config', 'feature_flags', 'domains']

    def create(self, validated_data):
        domains = validated_data.pop('domains', [])
        
        # Create tenant
        tenant = super().create(validated_data)
        
        # Create domain associations
        for i, domain in enumerate(domains):
            TenantDomain.objects.create(
                tenant=tenant,
                domain=domain,
                is_primary=(i == 0)  # First domain is primary
            )
        
        return tenant


class TenantUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating tenant details (excluding domains)."""
    
    class Meta:
        model = Tenant
        fields = ['name', 'is_active', 'theme_config', 'feature_flags']

    def validate_name(self, value):
        """Ensure name is unique."""
        if self.instance and Tenant.objects.exclude(id=self.instance.id).filter(name=value).exists():
            raise serializers.ValidationError("A tenant with this name already exists.")
        return value


class TenantDomainManagementSerializer(serializers.Serializer):
    """Serializer for managing tenant domains."""
    domains = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=True,
        help_text="List of domain names"
    )
    action = serializers.ChoiceField(
        choices=['add', 'remove'],
        required=True,
        help_text="Action to perform: add or remove domains"
    )

    def validate_domains(self, value):
        """Validate domain format."""
        if not value:
            raise serializers.ValidationError("At least one domain must be provided.")
        
        for domain in value:
            if not domain or len(domain.strip()) == 0:
                raise serializers.ValidationError("Domain names cannot be empty.")
                
        return [domain.strip().lower() for domain in value]


class GeneralSettingsSerializer(serializers.ModelSerializer):
    """Serializer for general platform settings."""
    
    class Meta:
        model = PlatformSettings
        fields = [
            'site_name',
            'site_description',
            'default_language',
            'timezone',
            'support_email',
            'terms_url',
            'privacy_url',
            'logo_url',
            'favicon_url',
        ]


class StorageSettingsSerializer(serializers.ModelSerializer):
    """Serializer for storage settings."""
    
    class Meta:
        model = PlatformSettings
        fields = [
            'storage_backend',
            's3_bucket_name',
            's3_region',
            's3_access_key_id',
            's3_secret_access_key',
            's3_endpoint_url',
            's3_custom_domain',
            'gcs_bucket_name',
            'gcs_project_id',
            'azure_container_name',
            'azure_account_name',
            'azure_account_key',
            'max_file_size_mb',
            'allowed_extensions',
        ]
        extra_kwargs = {
            # Mark sensitive fields as write-only
            's3_secret_access_key': {'write_only': True},
            'azure_account_key': {'write_only': True},
        }

    def to_representation(self, instance):
        """Mask sensitive fields in response."""
        data = super().to_representation(instance)
        # Indicate if secrets are set without exposing them
        if instance.s3_secret_access_key:
            data['s3_secret_access_key_set'] = True
        if instance.azure_account_key:
            data['azure_account_key_set'] = True
        return data


class EmailSettingsSerializer(serializers.ModelSerializer):
    """Serializer for email/SMTP settings."""
    
    class Meta:
        model = PlatformSettings
        fields = [
            'smtp_host',
            'smtp_port',
            'smtp_username',
            'smtp_password',
            'smtp_use_tls',
            'smtp_use_ssl',
            'default_from_email',
            'default_from_name',
            'email_timeout',
        ]
        extra_kwargs = {
            'smtp_password': {'write_only': True},
        }

    def to_representation(self, instance):
        """Mask sensitive fields in response."""
        data = super().to_representation(instance)
        if instance.smtp_password:
            data['smtp_password_set'] = True
        return data

    def validate(self, data):
        """Validate SMTP settings consistency."""
        smtp_use_tls = data.get('smtp_use_tls', self.instance.smtp_use_tls if self.instance else True)
        smtp_use_ssl = data.get('smtp_use_ssl', self.instance.smtp_use_ssl if self.instance else False)
        
        if smtp_use_tls and smtp_use_ssl:
            raise serializers.ValidationError({
                'smtp_use_ssl': 'Cannot use both TLS and SSL. Choose one or the other.'
            })
        return data


class PlatformSettingsSerializer(serializers.ModelSerializer):
    """Full serializer for all platform settings."""
    
    class Meta:
        model = PlatformSettings
        fields = [
            'id',
            'tenant',
            # General
            'site_name',
            'site_description',
            'default_language',
            'timezone',
            'support_email',
            'terms_url',
            'privacy_url',
            'logo_url',
            'favicon_url',
            # Storage
            'storage_backend',
            's3_bucket_name',
            's3_region',
            's3_access_key_id',
            's3_secret_access_key',
            's3_endpoint_url',
            's3_custom_domain',
            'gcs_bucket_name',
            'gcs_project_id',
            'azure_container_name',
            'azure_account_name',
            'azure_account_key',
            'max_file_size_mb',
            'allowed_extensions',
            # Email
            'smtp_host',
            'smtp_port',
            'smtp_username',
            'smtp_password',
            'smtp_use_tls',
            'smtp_use_ssl',
            'default_from_email',
            'default_from_name',
            'email_timeout',
            # Timestamps
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'tenant', 'created_at', 'updated_at']
        extra_kwargs = {
            's3_secret_access_key': {'write_only': True},
            'azure_account_key': {'write_only': True},
            'smtp_password': {'write_only': True},
        }

    def to_representation(self, instance):
        """Mask sensitive fields in response."""
        data = super().to_representation(instance)
        if instance.s3_secret_access_key:
            data['s3_secret_access_key_set'] = True
        if instance.azure_account_key:
            data['azure_account_key_set'] = True
        if instance.smtp_password:
            data['smtp_password_set'] = True
        return data


class TestEmailSerializer(serializers.Serializer):
    """Serializer for sending test emails."""
    recipient_email = serializers.EmailField(
        required=True,
        help_text="Email address to send the test email to"
    )


class TestStorageSerializer(serializers.Serializer):
    """Serializer for testing storage connection."""
    # No input needed - uses current settings
    pass


# === LTI Platform Serializers ===

class LTIPlatformListSerializer(serializers.ModelSerializer):
    """Serializer for listing LTI platforms (summary view)."""
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)
    deployments_count = serializers.SerializerMethodField()
    
    class Meta:
        model = LTIPlatform
        fields = [
            'id', 'name', 'issuer', 'client_id', 'is_active',
            'tenant', 'tenant_name', 'deployments_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'tenant_name', 'deployments_count', 'created_at', 'updated_at']
    
    def get_deployments_count(self, obj):
        return obj.deployments.count()


class LTIPlatformSerializer(serializers.ModelSerializer):
    """Full serializer for LTI platform CRUD operations."""
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)
    deployments_count = serializers.SerializerMethodField()
    
    class Meta:
        model = LTIPlatform
        fields = [
            'id', 'tenant', 'tenant_name', 'name', 'issuer', 'client_id',
            'deployment_id', 'auth_login_url', 'auth_token_url', 'keyset_url',
            'tool_private_key', 'tool_public_key', 'is_active',
            'deployments_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'tenant_name', 'deployments_count', 'created_at', 'updated_at']
        extra_kwargs = {
            'tool_private_key': {'write_only': True},
        }
    
    def get_deployments_count(self, obj):
        return obj.deployments.count()
    
    def to_representation(self, instance):
        """Mask sensitive fields in response."""
        data = super().to_representation(instance)
        # Indicate if private key is set without exposing it
        if instance.tool_private_key:
            data['tool_private_key_set'] = True
        return data
    
    def validate(self, data):
        """Validate platform configuration."""
        tenant = data.get('tenant', getattr(self.instance, 'tenant', None))
        issuer = data.get('issuer', getattr(self.instance, 'issuer', None))
        client_id = data.get('client_id', getattr(self.instance, 'client_id', None))
        
        # Check for duplicate platform registration
        if tenant and issuer and client_id:
            query = LTIPlatform.objects.filter(
                tenant=tenant, issuer=issuer, client_id=client_id
            )
            if self.instance:
                query = query.exclude(pk=self.instance.pk)
            if query.exists():
                raise serializers.ValidationError({
                    'issuer': 'A platform with this issuer and client_id already exists for this tenant.'
                })
        
        return data


class LTIPlatformCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating LTI platforms with auto-generated keys."""
    generate_keys = serializers.BooleanField(
        required=False, default=True, write_only=True,
        help_text="If true, RSA key pair will be automatically generated"
    )
    
    class Meta:
        model = LTIPlatform
        fields = [
            'tenant', 'name', 'issuer', 'client_id', 'deployment_id',
            'auth_login_url', 'auth_token_url', 'keyset_url',
            'tool_private_key', 'tool_public_key', 'is_active', 'generate_keys'
        ]
        extra_kwargs = {
            'tool_private_key': {'required': False},
            'tool_public_key': {'required': False},
        }
    
    def validate(self, data):
        """Validate and optionally generate RSA keys."""
        generate_keys = data.pop('generate_keys', True)
        
        if generate_keys and not data.get('tool_private_key'):
            # Generate RSA key pair
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.backends import default_backend
            
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            )
            
            # Export private key in PEM format
            private_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            ).decode('utf-8')
            
            # Export public key in PEM format
            public_pem = private_key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            ).decode('utf-8')
            
            data['tool_private_key'] = private_pem
            data['tool_public_key'] = public_pem
        
        elif not generate_keys:
            if not data.get('tool_private_key') or not data.get('tool_public_key'):
                raise serializers.ValidationError({
                    'tool_private_key': 'Private key is required when not auto-generating keys.',
                    'tool_public_key': 'Public key is required when not auto-generating keys.'
                })
        
        return data


# === SSO Configuration Serializers ===

class SSOConfigurationListSerializer(serializers.ModelSerializer):
    """Serializer for listing SSO configurations (summary view)."""
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)
    provider_type_display = serializers.CharField(source='get_provider_type_display', read_only=True)
    
    class Meta:
        model = SSOConfiguration
        fields = [
            'id', 'name', 'provider_type', 'provider_type_display',
            'is_active', 'is_default', 'tenant', 'tenant_name',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'tenant_name', 'provider_type_display', 'created_at', 'updated_at']


class SSOConfigurationSerializer(serializers.ModelSerializer):
    """Full serializer for SSO configuration CRUD operations."""
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)
    provider_type_display = serializers.CharField(source='get_provider_type_display', read_only=True)
    
    class Meta:
        model = SSOConfiguration
        fields = [
            'id', 'tenant', 'tenant_name', 'name', 'provider_type', 'provider_type_display',
            'is_active', 'is_default',
            # SAML fields
            'idp_entity_id', 'idp_sso_url', 'idp_slo_url', 'idp_x509_cert',
            # OAuth fields
            'oauth_client_id', 'oauth_client_secret', 'oauth_authorization_url',
            'oauth_token_url', 'oauth_userinfo_url', 'oauth_scopes',
            # Mappings
            'attribute_mapping', 'role_mapping',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'tenant_name', 'provider_type_display', 'created_at', 'updated_at']
        extra_kwargs = {
            'oauth_client_secret': {'write_only': True},
            'idp_x509_cert': {'write_only': True},
        }
    
    def to_representation(self, instance):
        """Mask sensitive fields in response."""
        data = super().to_representation(instance)
        # Indicate if secrets are set without exposing them
        if instance.oauth_client_secret:
            data['oauth_client_secret_set'] = True
        if instance.idp_x509_cert:
            data['idp_x509_cert_set'] = True
        return data
    
    def validate(self, data):
        """Validate SSO configuration based on provider type."""
        provider_type = data.get('provider_type', getattr(self.instance, 'provider_type', None))
        
        if provider_type == SSOConfiguration.ProviderType.SAML:
            # Validate SAML-specific fields
            if not data.get('idp_entity_id') and not getattr(self.instance, 'idp_entity_id', None):
                raise serializers.ValidationError({
                    'idp_entity_id': 'IdP Entity ID is required for SAML configuration.'
                })
            if not data.get('idp_sso_url') and not getattr(self.instance, 'idp_sso_url', None):
                raise serializers.ValidationError({
                    'idp_sso_url': 'IdP SSO URL is required for SAML configuration.'
                })
        
        elif provider_type in [
            SSOConfiguration.ProviderType.OAUTH_GOOGLE,
            SSOConfiguration.ProviderType.OAUTH_MICROSOFT,
            SSOConfiguration.ProviderType.OAUTH_GENERIC,
            SSOConfiguration.ProviderType.OIDC,
        ]:
            # Validate OAuth-specific fields
            if not data.get('oauth_client_id') and not getattr(self.instance, 'oauth_client_id', None):
                raise serializers.ValidationError({
                    'oauth_client_id': 'Client ID is required for OAuth/OIDC configuration.'
                })
            
            # For generic OAuth/OIDC, require endpoint URLs
            if provider_type in [SSOConfiguration.ProviderType.OAUTH_GENERIC, SSOConfiguration.ProviderType.OIDC]:
                if not data.get('oauth_authorization_url') and not getattr(self.instance, 'oauth_authorization_url', None):
                    raise serializers.ValidationError({
                        'oauth_authorization_url': 'Authorization URL is required for generic OAuth/OIDC.'
                    })
                if not data.get('oauth_token_url') and not getattr(self.instance, 'oauth_token_url', None):
                    raise serializers.ValidationError({
                        'oauth_token_url': 'Token URL is required for generic OAuth/OIDC.'
                    })
        
        return data


class SSOProviderTypeSerializer(serializers.Serializer):
    """Serializer for listing available SSO provider types."""
    value = serializers.CharField()
    label = serializers.CharField()


# === LTI AGS (Assignment & Grade Services) Serializers ===

class LTIResourceLinkSerializer(serializers.ModelSerializer):
    """Serializer for LTI resource links (read-only summary)."""
    platform_name = serializers.CharField(source='platform.name', read_only=True)
    course_title = serializers.CharField(source='course.title', read_only=True)

    class Meta:
        model = LTIResourceLink
        fields = [
            'id', 'platform', 'platform_name', 'resource_link_id',
            'lti_context_id', 'lti_context_title', 'course', 'course_title',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'platform_name', 'course_title', 'created_at', 'updated_at']


class LTILineItemListSerializer(serializers.ModelSerializer):
    """Serializer for listing LTI line items (summary view)."""
    resource_link_title = serializers.CharField(
        source='resource_link.lti_context_title', read_only=True
    )
    assessment_title = serializers.CharField(
        source='assessment.title', read_only=True
    )
    grade_submissions_count = serializers.SerializerMethodField()

    class Meta:
        model = LTILineItem
        fields = [
            'id', 'resource_link', 'resource_link_title', 'assessment',
            'assessment_title', 'label', 'score_maximum', 'tag',
            'grade_submissions_count', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'resource_link_title', 'assessment_title',
            'grade_submissions_count', 'created_at', 'updated_at'
        ]

    def get_grade_submissions_count(self, obj):
        return obj.grade_submissions.count()


class LTILineItemSerializer(serializers.ModelSerializer):
    """Full serializer for LTI line item CRUD operations."""
    resource_link_title = serializers.CharField(
        source='resource_link.lti_context_title', read_only=True
    )
    assessment_title = serializers.CharField(
        source='assessment.title', read_only=True
    )
    grade_submissions_count = serializers.SerializerMethodField()

    class Meta:
        model = LTILineItem
        fields = [
            'id', 'resource_link', 'resource_link_title', 'line_item_id',
            'assessment', 'assessment_title', 'label', 'score_maximum',
            'tag', 'resource_id', 'ags_endpoint', 'grade_submissions_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'resource_link_title', 'assessment_title', 'line_item_id',
            'ags_endpoint', 'grade_submissions_count', 'created_at', 'updated_at'
        ]

    def get_grade_submissions_count(self, obj):
        return obj.grade_submissions.count()

    def validate(self, data):
        """Validate line item configuration."""
        resource_link = data.get('resource_link', getattr(self.instance, 'resource_link', None))
        assessment = data.get('assessment')

        # If linking to an assessment, validate it belongs to the same course
        if assessment and resource_link and resource_link.course:
            if assessment.course != resource_link.course:
                raise serializers.ValidationError({
                    'assessment': 'Assessment must belong to the same course as the resource link.'
                })

        return data


class LTILineItemCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating LTI line items."""

    class Meta:
        model = LTILineItem
        fields = [
            'resource_link', 'assessment', 'label', 'score_maximum',
            'tag', 'resource_id'
        ]

    def validate(self, data):
        """Validate line item creation."""
        resource_link = data.get('resource_link')
        assessment = data.get('assessment')

        # If linking to an assessment, validate it belongs to the same course
        if assessment and resource_link and resource_link.course:
            if assessment.course != resource_link.course:
                raise serializers.ValidationError({
                    'assessment': 'Assessment must belong to the same course as the resource link.'
                })

        return data


class LTIGradeSubmissionListSerializer(serializers.ModelSerializer):
    """Serializer for listing grade submissions (summary view)."""
    line_item_label = serializers.CharField(source='line_item.label', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.SerializerMethodField()
    score_percentage = serializers.SerializerMethodField()

    class Meta:
        model = LTIGradeSubmission
        fields = [
            'id', 'line_item', 'line_item_label', 'user', 'user_email',
            'user_name', 'score', 'score_maximum', 'score_percentage',
            'status', 'submitted_at', 'retry_count', 'created_at'
        ]
        read_only_fields = [
            'id', 'line_item_label', 'user_email', 'user_name',
            'score_percentage', 'created_at'
        ]

    def get_user_name(self, obj):
        return obj.user.get_full_name() or obj.user.email

    def get_score_percentage(self, obj):
        if obj.score_maximum and obj.score_maximum > 0:
            return round((float(obj.score) / float(obj.score_maximum)) * 100, 2)
        return 0


class LTIGradeSubmissionSerializer(serializers.ModelSerializer):
    """Full serializer for LTI grade submission."""
    line_item_label = serializers.CharField(source='line_item.label', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.SerializerMethodField()
    score_percentage = serializers.SerializerMethodField()

    class Meta:
        model = LTIGradeSubmission
        fields = [
            'id', 'line_item', 'line_item_label', 'user', 'user_email',
            'user_name', 'lti_user_id', 'score', 'score_maximum',
            'score_percentage', 'comment', 'activity_progress',
            'grading_progress', 'status', 'submitted_at', 'error_message',
            'retry_count', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'line_item_label', 'user_email', 'user_name',
            'score_percentage', 'status', 'submitted_at', 'error_message',
            'retry_count', 'created_at', 'updated_at'
        ]

    def get_user_name(self, obj):
        return obj.user.get_full_name() or obj.user.email

    def get_score_percentage(self, obj):
        if obj.score_maximum and obj.score_maximum > 0:
            return round((float(obj.score) / float(obj.score_maximum)) * 100, 2)
        return 0


class LTIGradeSubmissionCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating/submitting grades via AGS."""

    class Meta:
        model = LTIGradeSubmission
        fields = [
            'line_item', 'user', 'lti_user_id', 'score', 'score_maximum',
            'comment', 'activity_progress', 'grading_progress'
        ]

    def validate(self, data):
        """Validate grade submission."""
        score = data.get('score')
        score_maximum = data.get('score_maximum')

        if score is not None and score_maximum is not None:
            if score < 0:
                raise serializers.ValidationError({
                    'score': 'Score cannot be negative.'
                })
            if score > score_maximum:
                raise serializers.ValidationError({
                    'score': 'Score cannot exceed the maximum score.'
                })

        # Validate activity_progress values
        valid_activity_progress = ['Initialized', 'Started', 'InProgress', 'Submitted', 'Completed']
        activity_progress = data.get('activity_progress', 'Completed')
        if activity_progress not in valid_activity_progress:
            raise serializers.ValidationError({
                'activity_progress': f'Must be one of: {", ".join(valid_activity_progress)}'
            })

        # Validate grading_progress values
        valid_grading_progress = ['FullyGraded', 'Pending', 'PendingManual', 'Failed', 'NotReady']
        grading_progress = data.get('grading_progress', 'FullyGraded')
        if grading_progress not in valid_grading_progress:
            raise serializers.ValidationError({
                'grading_progress': f'Must be one of: {", ".join(valid_grading_progress)}'
            })

        return data


class RetryFailedSubmissionsSerializer(serializers.Serializer):
    """Serializer for retrying failed grade submissions."""
    line_item_id = serializers.UUIDField(
        required=False,
        help_text="Optional: Only retry submissions for this line item"
    )
    submission_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text="Optional: Specific submission IDs to retry"
    )
    max_retries = serializers.IntegerField(
        default=3,
        min_value=1,
        max_value=10,
        help_text="Maximum number of retries per submission"
    )

    def validate(self, data):
        """Ensure at least one filter is provided."""
        if not data.get('line_item_id') and not data.get('submission_ids'):
            raise serializers.ValidationError(
                "Either 'line_item_id' or 'submission_ids' must be provided."
            )
        return data