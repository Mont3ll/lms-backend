"""
Tests for LTI 1.3 and SSO integration.
"""

from django.test import TestCase, RequestFactory
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import (
    Tenant,
    TenantDomain,
    LTIPlatform,
    LTIDeployment,
    LTIResourceLink,
    SSOConfiguration,
)
from apps.users.models import User


class LTIPlatformModelTests(TestCase):
    """Tests for LTIPlatform model."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")

    def test_create_lti_platform(self):
        """Test creating an LTI platform."""
        platform = LTIPlatform.objects.create(
            tenant=self.tenant,
            name="Canvas LMS",
            issuer="https://canvas.instructure.com",
            client_id="10000000000001",
            auth_login_url="https://canvas.instructure.com/api/lti/authorize",
            auth_token_url="https://canvas.instructure.com/login/oauth2/token",
            keyset_url="https://canvas.instructure.com/api/lti/security/jwks",
            tool_private_key="-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
            tool_public_key="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
        )
        self.assertEqual(str(platform), "Canvas LMS (Test Tenant)")
        self.assertTrue(platform.is_active)

    def test_lti_platform_unique_together(self):
        """Test unique_together constraint on tenant, issuer, client_id."""
        LTIPlatform.objects.create(
            tenant=self.tenant,
            name="Canvas LMS",
            issuer="https://canvas.instructure.com",
            client_id="10000000000001",
            auth_login_url="https://canvas.instructure.com/api/lti/authorize",
            auth_token_url="https://canvas.instructure.com/login/oauth2/token",
            keyset_url="https://canvas.instructure.com/api/lti/security/jwks",
            tool_private_key="test",
            tool_public_key="test",
        )

        # Duplicate should raise error
        with self.assertRaises(Exception):
            LTIPlatform.objects.create(
                tenant=self.tenant,
                name="Canvas LMS 2",
                issuer="https://canvas.instructure.com",
                client_id="10000000000001",
                auth_login_url="https://canvas.instructure.com/api/lti/authorize",
                auth_token_url="https://canvas.instructure.com/login/oauth2/token",
                keyset_url="https://canvas.instructure.com/api/lti/security/jwks",
                tool_private_key="test",
                tool_public_key="test",
            )


class LTIDeploymentModelTests(TestCase):
    """Tests for LTIDeployment model."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.platform = LTIPlatform.objects.create(
            tenant=self.tenant,
            name="Canvas LMS",
            issuer="https://canvas.instructure.com",
            client_id="10000000000001",
            auth_login_url="https://canvas.instructure.com/api/lti/authorize",
            auth_token_url="https://canvas.instructure.com/login/oauth2/token",
            keyset_url="https://canvas.instructure.com/api/lti/security/jwks",
            tool_private_key="test",
            tool_public_key="test",
        )

    def test_create_deployment(self):
        """Test creating an LTI deployment."""
        deployment = LTIDeployment.objects.create(
            platform=self.platform,
            deployment_id="12345:abcde",
        )
        self.assertEqual(str(deployment), "12345:abcde (Canvas LMS)")
        self.assertTrue(deployment.is_active)

    def test_deployment_unique_together(self):
        """Test unique_together constraint on platform and deployment_id."""
        LTIDeployment.objects.create(
            platform=self.platform,
            deployment_id="12345:abcde",
        )

        with self.assertRaises(Exception):
            LTIDeployment.objects.create(
                platform=self.platform,
                deployment_id="12345:abcde",
            )


class SSOConfigurationModelTests(TestCase):
    """Tests for SSOConfiguration model."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")

    def test_create_saml_configuration(self):
        """Test creating a SAML SSO configuration."""
        config = SSOConfiguration.objects.create(
            tenant=self.tenant,
            name="Corporate SAML",
            provider_type=SSOConfiguration.ProviderType.SAML,
            idp_entity_id="https://idp.example.com",
            idp_sso_url="https://idp.example.com/sso",
            idp_x509_cert="-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----",
        )
        self.assertEqual(
            str(config), "Corporate SAML (SAML 2.0) - Test Tenant"
        )
        self.assertTrue(config.is_active)

    def test_create_oauth_configuration(self):
        """Test creating an OAuth SSO configuration."""
        config = SSOConfiguration.objects.create(
            tenant=self.tenant,
            name="Google SSO",
            provider_type=SSOConfiguration.ProviderType.OAUTH_GOOGLE,
            oauth_client_id="google-client-id",
            oauth_client_secret="google-client-secret",
        )
        self.assertEqual(config.provider_type, "OAUTH_GOOGLE")

    def test_only_one_default_per_tenant(self):
        """Test that only one SSO config can be default per tenant."""
        config1 = SSOConfiguration.objects.create(
            tenant=self.tenant,
            name="SAML 1",
            provider_type=SSOConfiguration.ProviderType.SAML,
            is_default=True,
        )

        config2 = SSOConfiguration.objects.create(
            tenant=self.tenant,
            name="SAML 2",
            provider_type=SSOConfiguration.ProviderType.SAML,
            is_default=True,
        )

        # First config should no longer be default
        config1.refresh_from_db()
        self.assertFalse(config1.is_default)
        self.assertTrue(config2.is_default)


class LTIViewTests(APITestCase):
    """Tests for LTI views."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        TenantDomain.objects.create(
            tenant=self.tenant, domain="test.example.com", is_primary=True
        )
        self.platform = LTIPlatform.objects.create(
            tenant=self.tenant,
            name="Canvas LMS",
            issuer="https://canvas.instructure.com",
            client_id="10000000000001",
            auth_login_url="https://canvas.instructure.com/api/lti/authorize",
            auth_token_url="https://canvas.instructure.com/login/oauth2/token",
            keyset_url="https://canvas.instructure.com/api/lti/security/jwks",
            tool_private_key="test",
            tool_public_key="test",
        )

    def test_oidc_login_missing_iss(self):
        """Test OIDC login without issuer parameter."""
        url = reverse("core:lti-oidc-login")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_oidc_login_unknown_platform(self):
        """Test OIDC login with unknown platform."""
        url = reverse("core:lti-oidc-login")
        response = self.client.get(url, {"iss": "https://unknown.example.com"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_jwks_endpoint(self):
        """Test JWKS endpoint returns JSON."""
        url = reverse("core:lti-jwks")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("keys", response.data)


class SSOViewTests(APITestCase):
    """Tests for SSO views."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        TenantDomain.objects.create(
            tenant=self.tenant, domain="test.example.com", is_primary=True
        )

    def test_sso_providers_empty(self):
        """Test SSO providers endpoint with no configurations."""
        url = reverse("core:sso-providers")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["providers"], [])

    def test_sso_providers_with_config(self):
        """Test SSO providers endpoint with configuration."""
        SSOConfiguration.objects.create(
            tenant=self.tenant,
            name="Corporate SSO",
            provider_type=SSOConfiguration.ProviderType.SAML,
            is_active=True,
        )

        url = reverse("core:sso-providers")
        # We need to simulate tenant middleware setting the tenant
        factory = RequestFactory()
        request = factory.get(url)
        request.tenant = self.tenant

        from apps.core.views import SSOProvidersView

        view = SSOProvidersView.as_view()
        response = view(request)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["providers"]), 1)
        self.assertEqual(response.data["providers"][0]["name"], "Corporate SSO")


class LTIServiceTests(TestCase):
    """Tests for LTI service layer."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.platform = LTIPlatform.objects.create(
            tenant=self.tenant,
            name="Canvas LMS",
            issuer="https://canvas.instructure.com",
            client_id="10000000000001",
            auth_login_url="https://canvas.instructure.com/api/lti/authorize",
            auth_token_url="https://canvas.instructure.com/login/oauth2/token",
            keyset_url="https://canvas.instructure.com/api/lti/security/jwks",
            tool_private_key="test",
            tool_public_key="test",
        )

    def test_lti_service_initialization(self):
        """Test LTI service can be initialized."""
        from apps.core.services import LTIService

        # Create mock request
        factory = RequestFactory()
        request = factory.get(
            "/api/core/lti/login/",
            {
                "iss": "https://canvas.instructure.com",
                "login_hint": "user123",
                "target_link_uri": "https://lms.example.com/lti/launch",
            },
        )
        request.tenant = self.tenant

        # Test that the service can be instantiated
        service = LTIService(request, platform=self.platform)
        self.assertIsNotNone(service)
        self.assertEqual(service.platform, self.platform)

    def test_map_lti_role_learner(self):
        """Test mapping LTI learner roles."""
        from apps.core.services import LTIService

        factory = RequestFactory()
        request = factory.get("/")
        request.tenant = self.tenant

        service = LTIService(request, platform=self.platform)

        learner_roles = [
            "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner",
        ]
        role = service._map_lti_role_to_lms_role(learner_roles)
        self.assertEqual(role, "LEARNER")

    def test_map_lti_role_instructor(self):
        """Test mapping LTI instructor roles."""
        from apps.core.services import LTIService

        factory = RequestFactory()
        request = factory.get("/")
        request.tenant = self.tenant

        service = LTIService(request, platform=self.platform)

        instructor_roles = [
            "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor",
        ]
        role = service._map_lti_role_to_lms_role(instructor_roles)
        self.assertEqual(role, "INSTRUCTOR")

    def test_map_lti_role_admin(self):
        """Test mapping LTI admin roles."""
        from apps.core.services import LTIService

        factory = RequestFactory()
        request = factory.get("/")
        request.tenant = self.tenant

        service = LTIService(request, platform=self.platform)

        admin_roles = [
            "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator",
        ]
        role = service._map_lti_role_to_lms_role(admin_roles)
        self.assertEqual(role, "ADMIN")


class SSOServiceTests(TestCase):
    """Tests for SSO service layer."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.saml_config = SSOConfiguration.objects.create(
            tenant=self.tenant,
            name="Corporate SAML",
            provider_type=SSOConfiguration.ProviderType.SAML,
            idp_entity_id="https://idp.example.com",
            idp_sso_url="https://idp.example.com/sso",
            idp_x509_cert="-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----",
            attribute_mapping={
                "email": "mail",
                "first_name": "givenName",
                "last_name": "sn",
            },
            role_mapping={
                "admins": "ADMIN",
                "teachers": "INSTRUCTOR",
                "students": "LEARNER",
            },
        )

    def test_sso_service_initialization(self):
        """Test SSO service can be initialized."""
        from apps.core.services import SSOService

        factory = RequestFactory()
        request = factory.get("/")
        request.tenant = self.tenant

        service = SSOService(request, sso_config=self.saml_config)
        self.assertIsNotNone(service)

    def test_map_sso_attributes(self):
        """Test mapping SSO attributes to user fields."""
        from apps.core.services import SSOService

        factory = RequestFactory()
        request = factory.get("/")
        request.tenant = self.tenant

        service = SSOService(request, sso_config=self.saml_config)

        idp_attributes = {
            "mail": ["user@example.com"],
            "givenName": ["John"],
            "sn": ["Doe"],
        }

        mapped = service._map_saml_attributes(idp_attributes, "user@example.com")
        self.assertEqual(mapped.get("email"), "user@example.com")
        self.assertEqual(mapped.get("first_name"), "John")
        self.assertEqual(mapped.get("last_name"), "Doe")

    def test_map_sso_role(self):
        """Test mapping SSO groups to LMS roles."""
        from apps.core.services import SSOService

        factory = RequestFactory()
        request = factory.get("/")
        request.tenant = self.tenant

        service = SSOService(request, sso_config=self.saml_config)

        # Test admin group
        role = service._map_sso_role(["admins", "users"])
        self.assertEqual(role, "ADMIN")

        # Test instructor group
        role = service._map_sso_role(["teachers"])
        self.assertEqual(role, "INSTRUCTOR")

        # Test learner group
        role = service._map_sso_role(["students"])
        self.assertEqual(role, "LEARNER")

        # Test default when no match
        role = service._map_sso_role(["unknown_group"])
        self.assertEqual(role, "LEARNER")


class LTIResourceLinkModelTests(TestCase):
    """Tests for LTIResourceLink model."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.platform = LTIPlatform.objects.create(
            tenant=self.tenant,
            name="Canvas LMS",
            issuer="https://canvas.instructure.com",
            client_id="10000000000001",
            auth_login_url="https://canvas.instructure.com/api/lti/authorize",
            auth_token_url="https://canvas.instructure.com/login/oauth2/token",
            keyset_url="https://canvas.instructure.com/api/lti/security/jwks",
            tool_private_key="test",
            tool_public_key="test",
        )

    def test_create_resource_link(self):
        """Test creating a resource link."""
        link = LTIResourceLink.objects.create(
            platform=self.platform,
            resource_link_id="abc123",
            lti_context_id="course-456",
            lti_context_title="Introduction to Python",
        )
        self.assertEqual(str(link), "Introduction to Python")

    def test_resource_link_without_title(self):
        """Test resource link string without title uses ID."""
        link = LTIResourceLink.objects.create(
            platform=self.platform,
            resource_link_id="abc123",
        )
        self.assertEqual(str(link), "abc123")
