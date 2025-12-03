from rest_framework import serializers
from django.utils.text import slugify
from .models import Tenant, TenantDomain


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