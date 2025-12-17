import hashlib
import logging
import secrets
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import login as django_login
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction

from .models import (
    LTIDeployment,
    LTIPlatform,
    LTIResourceLink,
    SSOConfiguration,
    Tenant,
    TenantDomain,
)

logger = logging.getLogger(__name__)


class AGSServiceError(Exception):
    """Exception raised for AGS (Assignment and Grade Services) errors."""

    pass


class AGSService:
    """
    Handles LTI Assignment and Grade Services (AGS) for grade passback.
    Supports LTI 1.3 AGS 2.0 specification.
    
    See: https://www.imsglobal.org/spec/lti-ags/v2p0
    """

    # AGS claim namespace
    AGS_CLAIM = "https://purl.imsglobal.org/spec/lti-ags/claim/endpoint"
    
    # AGS scopes
    SCOPE_LINEITEM = "https://purl.imsglobal.org/spec/lti-ags/scope/lineitem"
    SCOPE_LINEITEM_READONLY = "https://purl.imsglobal.org/spec/lti-ags/scope/lineitem.readonly"
    SCOPE_RESULT_READONLY = "https://purl.imsglobal.org/spec/lti-ags/scope/result.readonly"
    SCOPE_SCORE = "https://purl.imsglobal.org/spec/lti-ags/scope/score"

    def __init__(self, platform: "LTIPlatform"):
        self.platform = platform
        self._access_token = None
        self._token_expires_at = None

    def _get_access_token(self, scopes: list[str]) -> str:
        """
        Obtains an OAuth2 access token from the platform for AGS operations.
        Uses client credentials grant with JWT bearer assertion.
        """
        import time
        import jwt
        import requests as http_requests

        # Check if we have a valid cached token
        if self._access_token and self._token_expires_at:
            if time.time() < self._token_expires_at - 60:  # 60 second buffer
                return self._access_token

        logger.info(f"Requesting AGS access token for platform: {self.platform.name}")

        try:
            # Create JWT assertion
            now = int(time.time())
            payload = {
                "iss": self.platform.client_id,
                "sub": self.platform.client_id,
                "aud": self.platform.auth_token_url,
                "iat": now,
                "exp": now + 300,  # 5 minute expiry
                "jti": f"{self.platform.id}-{now}",
            }

            # Sign with our private key
            assertion = jwt.encode(
                payload,
                self.platform.tool_private_key,
                algorithm="RS256",
                headers={"kid": str(self.platform.id)},
            )

            # Request token
            token_data = {
                "grant_type": "client_credentials",
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                "client_assertion": assertion,
                "scope": " ".join(scopes),
            }

            response = http_requests.post(
                self.platform.auth_token_url,
                data=token_data,
                timeout=30,
            )
            response.raise_for_status()

            token_response = response.json()
            self._access_token = token_response.get("access_token")
            
            # Calculate expiry
            expires_in = token_response.get("expires_in", 3600)
            self._token_expires_at = time.time() + expires_in

            logger.info(f"Successfully obtained AGS access token for platform: {self.platform.name}")
            return self._access_token

        except http_requests.RequestException as e:
            logger.error(f"Failed to obtain AGS access token: {e}", exc_info=True)
            raise AGSServiceError(f"Failed to obtain access token: {str(e)}") from e
        except Exception as e:
            logger.error(f"Unexpected error obtaining AGS access token: {e}", exc_info=True)
            raise AGSServiceError(f"Access token error: {str(e)}") from e

    def extract_ags_claim(self, launch_data: dict) -> dict | None:
        """
        Extracts the AGS claim from LTI launch data.
        Returns None if AGS is not available for this launch.
        """
        return launch_data.get(self.AGS_CLAIM)

    def is_ags_available(self, launch_data: dict) -> bool:
        """Check if AGS is available for this launch."""
        ags_claim = self.extract_ags_claim(launch_data)
        if not ags_claim:
            return False
        
        # Check if required scopes are available
        scopes = ags_claim.get("scope", [])
        return self.SCOPE_SCORE in scopes or self.SCOPE_LINEITEM in scopes

    @transaction.atomic
    def create_or_get_line_item(
        self,
        resource_link: "LTIResourceLink",
        launch_data: dict,
        label: str,
        score_maximum: float = 100.0,
        tag: str = "",
        resource_id: str = "",
        assessment: "Assessment" = None,
    ) -> "LTILineItem":
        """
        Creates or retrieves a line item for grade passback.
        
        If the platform provided a line item URL in the launch, use that.
        Otherwise, create a new line item on the platform if we have permissions.
        """
        from .models import LTILineItem

        ags_claim = self.extract_ags_claim(launch_data)
        if not ags_claim:
            raise AGSServiceError("AGS not available for this launch")

        line_items_url = ags_claim.get("lineitems")
        line_item_url = ags_claim.get("lineitem")
        scopes = ags_claim.get("scope", [])

        # If a specific line item was provided, use it
        if line_item_url:
            line_item, created = LTILineItem.objects.get_or_create(
                resource_link=resource_link,
                line_item_id=line_item_url,
                defaults={
                    "label": label,
                    "score_maximum": score_maximum,
                    "tag": tag,
                    "resource_id": resource_id,
                    "ags_endpoint": line_item_url,
                    "assessment": assessment,
                },
            )
            if not created and assessment and not line_item.assessment:
                line_item.assessment = assessment
                line_item.save(update_fields=["assessment", "updated_at"])
            return line_item

        # Check if we can create line items
        if self.SCOPE_LINEITEM not in scopes:
            raise AGSServiceError("Platform does not allow creating line items")

        if not line_items_url:
            raise AGSServiceError("No line items URL provided by platform")

        # Check if we already have a line item for this assessment
        if assessment:
            existing = LTILineItem.objects.filter(
                resource_link=resource_link,
                assessment=assessment,
            ).first()
            if existing:
                return existing

        # Create a new line item on the platform
        line_item_url = self._create_platform_line_item(
            line_items_url=line_items_url,
            label=label,
            score_maximum=score_maximum,
            tag=tag,
            resource_id=resource_id,
        )

        # Store locally
        line_item = LTILineItem.objects.create(
            resource_link=resource_link,
            line_item_id=line_item_url,
            label=label,
            score_maximum=score_maximum,
            tag=tag,
            resource_id=resource_id,
            ags_endpoint=line_item_url,
            assessment=assessment,
        )

        logger.info(f"Created new line item: {line_item}")
        return line_item

    def _create_platform_line_item(
        self,
        line_items_url: str,
        label: str,
        score_maximum: float,
        tag: str = "",
        resource_id: str = "",
    ) -> str:
        """
        Creates a new line item on the LTI platform.
        Returns the line item URL.
        """
        import requests as http_requests

        access_token = self._get_access_token([self.SCOPE_LINEITEM])

        line_item_data = {
            "label": label,
            "scoreMaximum": score_maximum,
        }
        if tag:
            line_item_data["tag"] = tag
        if resource_id:
            line_item_data["resourceId"] = resource_id

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/vnd.ims.lis.v2.lineitem+json",
            "Accept": "application/vnd.ims.lis.v2.lineitem+json",
        }

        try:
            response = http_requests.post(
                line_items_url,
                json=line_item_data,
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()

            created_item = response.json()
            line_item_id = created_item.get("id")
            
            if not line_item_id:
                raise AGSServiceError("Platform did not return line item ID")

            logger.info(f"Created line item on platform: {line_item_id}")
            return line_item_id

        except http_requests.RequestException as e:
            logger.error(f"Failed to create line item on platform: {e}", exc_info=True)
            raise AGSServiceError(f"Failed to create line item: {str(e)}") from e

    def get_line_items(self, line_items_url: str) -> list[dict]:
        """
        Retrieves all line items from the platform.
        """
        import requests as http_requests

        access_token = self._get_access_token([self.SCOPE_LINEITEM_READONLY])

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.ims.lis.v2.lineitemcontainer+json",
        }

        try:
            response = http_requests.get(
                line_items_url,
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()

        except http_requests.RequestException as e:
            logger.error(f"Failed to get line items from platform: {e}", exc_info=True)
            raise AGSServiceError(f"Failed to get line items: {str(e)}") from e

    @transaction.atomic
    def submit_score(
        self,
        line_item: "LTILineItem",
        user: "User",
        lti_user_id: str,
        score: float,
        score_maximum: float,
        comment: str = "",
        activity_progress: str = "Completed",
        grading_progress: str = "FullyGraded",
    ) -> "LTIGradeSubmission":
        """
        Submits a score to the LTI platform for a specific user.
        
        Args:
            line_item: The LTI line item to submit the score for
            user: The LMS user
            lti_user_id: The LTI user identifier (sub claim)
            score: The score achieved
            score_maximum: The maximum possible score
            comment: Optional feedback comment
            activity_progress: One of Initialized, Started, InProgress, Submitted, Completed
            grading_progress: One of FullyGraded, Pending, PendingManual, Failed, NotReady
        
        Returns:
            LTIGradeSubmission record
        """
        from django.utils import timezone
        from .models import LTIGradeSubmission

        # Create submission record
        submission = LTIGradeSubmission.objects.create(
            line_item=line_item,
            user=user,
            lti_user_id=lti_user_id,
            score=score,
            score_maximum=score_maximum,
            comment=comment,
            activity_progress=activity_progress,
            grading_progress=grading_progress,
            status=LTIGradeSubmission.SubmissionStatus.PENDING,
        )

        # Attempt to submit to platform
        try:
            self._post_score_to_platform(
                line_item=line_item,
                lti_user_id=lti_user_id,
                score=score,
                score_maximum=score_maximum,
                comment=comment,
                activity_progress=activity_progress,
                grading_progress=grading_progress,
            )

            submission.status = LTIGradeSubmission.SubmissionStatus.SUBMITTED
            submission.submitted_at = timezone.now()
            submission.save(update_fields=["status", "submitted_at", "updated_at"])

            logger.info(
                f"Successfully submitted score for user {lti_user_id} on line item {line_item.id}"
            )

        except AGSServiceError as e:
            submission.status = LTIGradeSubmission.SubmissionStatus.FAILED
            submission.error_message = str(e)
            submission.save(update_fields=["status", "error_message", "updated_at"])
            logger.error(f"Failed to submit score: {e}")
            # Re-raise so caller knows it failed
            raise

        return submission

    def _post_score_to_platform(
        self,
        line_item: "LTILineItem",
        lti_user_id: str,
        score: float,
        score_maximum: float,
        comment: str = "",
        activity_progress: str = "Completed",
        grading_progress: str = "FullyGraded",
    ) -> None:
        """
        Posts a score to the LTI platform's score endpoint.
        """
        import requests as http_requests
        from django.utils import timezone

        access_token = self._get_access_token([self.SCOPE_SCORE])

        # Build the scores endpoint URL
        # AGS specifies the scores endpoint is at {lineItemUrl}/scores
        scores_url = line_item.ags_endpoint
        if not scores_url.endswith("/"):
            scores_url += "/"
        scores_url += "scores"

        # Build score payload per AGS spec
        score_data = {
            "userId": lti_user_id,
            "scoreGiven": float(score),
            "scoreMaximum": float(score_maximum),
            "activityProgress": activity_progress,
            "gradingProgress": grading_progress,
            "timestamp": timezone.now().isoformat(),
        }
        if comment:
            score_data["comment"] = comment

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/vnd.ims.lis.v1.score+json",
        }

        try:
            response = http_requests.post(
                scores_url,
                json=score_data,
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            logger.info(f"Score posted successfully to {scores_url}")

        except http_requests.RequestException as e:
            logger.error(f"Failed to post score to platform: {e}", exc_info=True)
            raise AGSServiceError(f"Failed to post score: {str(e)}") from e

    def get_results(self, line_item: "LTILineItem", user_id: str = None) -> list[dict]:
        """
        Retrieves results/scores from the platform for a line item.
        Optionally filter by user ID.
        """
        import requests as http_requests

        access_token = self._get_access_token([self.SCOPE_RESULT_READONLY])

        # Build the results endpoint URL
        results_url = line_item.ags_endpoint
        if not results_url.endswith("/"):
            results_url += "/"
        results_url += "results"

        if user_id:
            results_url += f"?user_id={user_id}"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.ims.lis.v2.resultcontainer+json",
        }

        try:
            response = http_requests.get(
                results_url,
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()

        except http_requests.RequestException as e:
            logger.error(f"Failed to get results from platform: {e}", exc_info=True)
            raise AGSServiceError(f"Failed to get results: {str(e)}") from e

    def retry_failed_submissions(self, max_retries: int = 3) -> int:
        """
        Retries failed grade submissions.
        Returns the number of successfully retried submissions.
        """
        from django.utils import timezone
        from .models import LTIGradeSubmission

        # Get failed submissions that haven't exceeded max retries
        failed_submissions = LTIGradeSubmission.objects.filter(
            line_item__resource_link__platform=self.platform,
            status=LTIGradeSubmission.SubmissionStatus.FAILED,
            retry_count__lt=max_retries,
        ).select_related("line_item", "user")

        success_count = 0

        for submission in failed_submissions:
            submission.status = LTIGradeSubmission.SubmissionStatus.RETRYING
            submission.retry_count += 1
            submission.save(update_fields=["status", "retry_count", "updated_at"])

            try:
                self._post_score_to_platform(
                    line_item=submission.line_item,
                    lti_user_id=submission.lti_user_id,
                    score=float(submission.score),
                    score_maximum=float(submission.score_maximum),
                    comment=submission.comment,
                    activity_progress=submission.activity_progress,
                    grading_progress=submission.grading_progress,
                )

                submission.status = LTIGradeSubmission.SubmissionStatus.SUBMITTED
                submission.submitted_at = timezone.now()
                submission.error_message = ""
                submission.save(
                    update_fields=["status", "submitted_at", "error_message", "updated_at"]
                )
                success_count += 1

                logger.info(f"Successfully retried submission {submission.id}")

            except AGSServiceError as e:
                submission.status = LTIGradeSubmission.SubmissionStatus.FAILED
                submission.error_message = str(e)
                submission.save(update_fields=["status", "error_message", "updated_at"])
                logger.warning(
                    f"Retry failed for submission {submission.id}: {e}"
                )

        return success_count


class TenantService:
    """
    Service layer for handling tenant-related logic.
    """

    CACHE_TIMEOUT = 3600  # Cache tenant lookups for 1 hour
    CACHE_KEY_PREFIX = "tenant_lookup_"

    @classmethod
    def get_tenant_by_hostname(cls, hostname: str) -> Tenant | None:
        """
        Retrieves the active tenant associated with a given hostname.
        Caches the result for performance.
        """
        if not hostname:
            return None

        cache_key = f"{cls.CACHE_KEY_PREFIX}{hostname}"
        cached_tenant_id = cache.get(cache_key)

        if cached_tenant_id is not None:
            # Check if cached value is placeholder for 'not found'
            if cached_tenant_id == "NOT_FOUND":
                return None
            try:
                # Fetch tenant by cached ID
                return Tenant.objects.get(pk=cached_tenant_id, is_active=True)
            except Tenant.DoesNotExist:
                # Cached ID is stale, force lookup
                cache.delete(cache_key)
                pass  # Fall through to database lookup

        # Cache miss or stale cache, query the database
        try:
            domain_entry = TenantDomain.objects.select_related("tenant").get(
                domain=hostname, tenant__is_active=True
            )
            tenant = domain_entry.tenant
            # Cache the tenant's ID
            cache.set(cache_key, tenant.id, timeout=cls.CACHE_TIMEOUT)
            logger.info(
                f"Tenant cache set for {hostname} -> {tenant.name} ({tenant.id})"
            )
            return tenant
        except ObjectDoesNotExist:
            logger.debug(f"No active tenant domain found for hostname: {hostname}")
            # Cache the negative result briefly
            cache.set(cache_key, "NOT_FOUND", timeout=60)
            return None
        except Exception as e:
            logger.error(
                f"Error retrieving tenant for hostname {hostname}: {e}", exc_info=True
            )
            return None

    @staticmethod
    def get_tenant_settings(tenant: Tenant) -> dict:
        """
        Retrieves settings specific to a tenant (e.g., theme, features).
        Merges tenant settings with potential defaults.
        """
        if not tenant:
            return {}  # Or return default public settings

        default_settings = {
            "theme": "default",
            "logo_url": None,
            "features": {
                "assessments": True,
                "learning_paths": False,
                "ai_generation": False,
            },
        }
        # Deep merge tenant settings over defaults (simplified example)
        settings = default_settings.copy()
        settings.update(
            tenant.theme_config or {}
        )  # Assuming theme settings are in theme_config
        settings["features"].update(tenant.feature_flags or {})
        return settings


# --- LTI / SSO Service Classes ---


class LTIServiceError(Exception):
    """Exception raised for LTI-related errors."""

    pass


class SSOServiceError(Exception):
    """Exception raised for SSO-related errors."""

    pass


class LTIService:
    """
    Handles LTI 1.3 launch requests and user/course provisioning.
    Uses the PyLTI1p3 library for LTI message validation.
    """

    def __init__(self, request, platform: LTIPlatform = None):
        self.request = request
        self.platform = platform
        self._message_launch = None
        self._launch_data = None

    def _get_tool_config(self, platform: LTIPlatform) -> dict:
        """
        Build PyLTI1p3 tool configuration from the LTIPlatform model.
        """
        return {
            platform.issuer: [
                {
                    "default": True,
                    "client_id": platform.client_id,
                    "auth_login_url": platform.auth_login_url,
                    "auth_token_url": platform.auth_token_url,
                    "key_set_url": platform.keyset_url,
                    "deployment_ids": list(
                        platform.deployments.filter(is_active=True).values_list(
                            "deployment_id", flat=True
                        )
                    )
                    or [platform.deployment_id]
                    if platform.deployment_id
                    else [],
                    "private_key_file": None,  # We use key content instead
                    "public_key_file": None,
                }
            ]
        }

    def _get_launch_data_storage(self):
        """
        Returns a cache-based launch data storage for PyLTI1p3.
        """
        from pylti1p3.launch_data_storage.cache import CacheDataStorage

        return CacheDataStorage(cache_prefix="lti1p3_")

    def _prepare_request_for_pylti(self) -> dict:
        """
        Converts Django request to the format expected by PyLTI1p3.
        """
        return {
            "request": self.request,
            "target_link_uri": self.request.build_absolute_uri(),
        }

    def validate_oidc_login(self, platform: LTIPlatform = None) -> str:
        """
        Handles the OIDC login initiation (step 1 of LTI 1.3 launch).
        Returns the redirect URL to the platform's authorization endpoint.
        """
        from pylti1p3.contrib.django import (
            DjangoOIDCLogin,
        )
        from pylti1p3.tool_config import ToolConfDict

        if platform:
            self.platform = platform
        if not self.platform:
            raise LTIServiceError("No LTI platform specified for OIDC login.")

        logger.info(f"Initiating OIDC login for platform: {self.platform.name}")

        try:
            tool_conf = ToolConfDict(self._get_tool_config(self.platform))
            # Set the private key
            tool_conf.set_private_key(
                self.platform.issuer,
                self.platform.tool_private_key,
                client_id=self.platform.client_id,
            )
            tool_conf.set_public_key(
                self.platform.issuer,
                self.platform.tool_public_key,
                client_id=self.platform.client_id,
            )

            oidc_login = DjangoOIDCLogin(
                self.request,
                tool_conf,
                launch_data_storage=self._get_launch_data_storage(),
            )

            # Get the launch URL (where the platform should redirect after auth)
            launch_url = self.request.build_absolute_uri("/api/lti/launch/")

            redirect = oidc_login.enable_check_cookies().redirect(launch_url)
            return redirect.get_redirect_url()

        except Exception as e:
            logger.error(f"OIDC login initiation failed: {e}", exc_info=True)
            raise LTIServiceError(f"OIDC login initiation failed: {str(e)}") from e

    def validate_launch(self, platform: LTIPlatform = None) -> dict:
        """
        Validates the LTI 1.3 launch request (step 2 - after OIDC redirect).
        Returns the validated launch data.
        """
        from pylti1p3.contrib.django import DjangoMessageLaunch
        from pylti1p3.tool_config import ToolConfDict

        if platform:
            self.platform = platform

        # Try to determine platform from the JWT if not provided
        if not self.platform:
            self.platform = self._detect_platform_from_request()

        if not self.platform:
            raise LTIServiceError("Could not determine LTI platform for launch.")

        logger.info(f"Validating LTI launch for platform: {self.platform.name}")

        try:
            tool_conf = ToolConfDict(self._get_tool_config(self.platform))
            tool_conf.set_private_key(
                self.platform.issuer,
                self.platform.tool_private_key,
                client_id=self.platform.client_id,
            )
            tool_conf.set_public_key(
                self.platform.issuer,
                self.platform.tool_public_key,
                client_id=self.platform.client_id,
            )

            self._message_launch = DjangoMessageLaunch(
                self.request,
                tool_conf,
                launch_data_storage=self._get_launch_data_storage(),
            )

            # Validate the launch
            self._message_launch.validate()
            self._launch_data = self._message_launch.get_launch_data()

            logger.info(
                f"LTI launch validated successfully. User sub: {self._launch_data.get('sub')}"
            )
            return self._launch_data

        except Exception as e:
            logger.error(f"LTI launch validation failed: {e}", exc_info=True)
            raise LTIServiceError(f"LTI launch validation failed: {str(e)}") from e

    def _detect_platform_from_request(self) -> LTIPlatform | None:
        """
        Attempts to detect the LTI platform from the request.
        Looks at the iss (issuer) claim in the JWT.
        """
        try:
            import jwt

            id_token = self.request.POST.get("id_token") or self.request.GET.get(
                "id_token"
            )
            if not id_token:
                return None

            # Decode without verification to get the issuer
            unverified = jwt.decode(id_token, options={"verify_signature": False})
            issuer = unverified.get("iss")
            client_id = unverified.get("aud")

            if isinstance(client_id, list):
                client_id = client_id[0]

            if issuer:
                tenant = getattr(self.request, "tenant", None)
                query = LTIPlatform.objects.filter(issuer=issuer, is_active=True)
                if tenant:
                    query = query.filter(tenant=tenant)
                if client_id:
                    query = query.filter(client_id=client_id)
                return query.first()

        except Exception as e:
            logger.warning(f"Could not detect platform from request: {e}")

        return None

    @transaction.atomic
    def provision_user_and_enrollment(
        self, launch_data: dict = None
    ) -> tuple[Any, Any, Any]:
        """
        Provisions a user and enrollment based on LTI launch data.
        Creates or updates the user, finds/creates the course link, and enrolls the user.

        Returns: (user, course, enrollment)
        """
        from apps.enrollments.services import EnrollmentService
        from apps.users.models import User, UserProfile

        if launch_data is None:
            launch_data = self._launch_data
        if not launch_data:
            raise LTIServiceError(
                "No launch data available. Call validate_launch() first."
            )

        # Extract LTI claims
        lti_user_id = launch_data.get("sub")
        email = launch_data.get("email")
        given_name = launch_data.get("given_name", "")
        family_name = launch_data.get("family_name", "")
        name = launch_data.get("name", "")

        # Handle case where only 'name' is provided
        if not given_name and not family_name and name:
            name_parts = name.split(" ", 1)
            given_name = name_parts[0]
            family_name = name_parts[1] if len(name_parts) > 1 else ""

        # Get LTI roles
        lti_roles = launch_data.get(
            "https://purl.imsglobal.org/spec/lti/claim/roles", []
        )

        # Get context (course) information
        lti_context = launch_data.get(
            "https://purl.imsglobal.org/spec/lti/claim/context", {}
        )
        lti_context_id = lti_context.get("id")
        lti_context_title = lti_context.get("title", "")

        # Get resource link information
        resource_link_claim = launch_data.get(
            "https://purl.imsglobal.org/spec/lti/claim/resource_link", {}
        )
        resource_link_id = resource_link_claim.get("id")

        if not lti_user_id:
            raise LTIServiceError("LTI launch missing required 'sub' claim.")

        # Generate email if not provided
        if not email:
            email = f"lti_{lti_user_id}@{self.platform.tenant.slug}.local"

        tenant = self.platform.tenant
        lms_role = self._map_lti_role_to_lms_role(lti_roles)

        logger.info(
            f"Provisioning LTI user: {email}, role: {lms_role}, context: {lti_context_id}"
        )

        # Find or create user
        user = None
        created = False

        # First, try to find by LTI user ID
        try:
            user = User.objects.get(lti_user_id=lti_user_id, tenant=tenant)
        except User.DoesNotExist:
            # Try to find by email within the tenant
            try:
                user = User.objects.get(email=email, tenant=tenant)
                # Link existing user to LTI
                user.lti_user_id = lti_user_id
                user.save(update_fields=["lti_user_id", "updated_at"])
            except User.DoesNotExist:
                # Create new user
                user = User.objects.create(
                    email=email,
                    first_name=given_name,
                    last_name=family_name,
                    role=lms_role,
                    tenant=tenant,
                    lti_user_id=lti_user_id,
                    status=User.Status.ACTIVE,
                    is_active=True,
                )
                created = True
                # Create user profile
                UserProfile.objects.get_or_create(user=user)
                logger.info(f"Created new LTI user: {user.email}")

        # Update user info if needed (name might have changed)
        if not created:
            update_fields = []
            if given_name and user.first_name != given_name:
                user.first_name = given_name
                update_fields.append("first_name")
            if family_name and user.last_name != family_name:
                user.last_name = family_name
                update_fields.append("last_name")
            # Optionally upgrade role if LTI indicates higher privilege
            if lms_role == User.Role.INSTRUCTOR and user.role == User.Role.LEARNER:
                user.role = lms_role
                update_fields.append("role")
            if update_fields:
                update_fields.append("updated_at")
                user.save(update_fields=update_fields)

        # Find or create resource link (and optionally course)
        course = None
        enrollment = None

        if resource_link_id:
            resource_link, _ = LTIResourceLink.objects.get_or_create(
                platform=self.platform,
                resource_link_id=resource_link_id,
                defaults={
                    "lti_context_id": lti_context_id or "",
                    "lti_context_title": lti_context_title,
                },
            )

            # Update context info if it changed
            if lti_context_id and resource_link.lti_context_id != lti_context_id:
                resource_link.lti_context_id = lti_context_id
                resource_link.lti_context_title = lti_context_title
                resource_link.save(
                    update_fields=["lti_context_id", "lti_context_title", "updated_at"]
                )

            course = resource_link.course

        # Enroll user if course is linked and user is a learner
        if course and lms_role in [User.Role.LEARNER, User.Role.INSTRUCTOR]:
            enrollment, _ = EnrollmentService.enroll_user(user, course)
            logger.info(f"Enrolled LTI user {user.email} in course {course.title}")

        return user, course, enrollment

    def _map_lti_role_to_lms_role(self, lti_roles: list) -> str:
        """
        Maps LTI roles to LMS roles.
        See: https://www.imsglobal.org/spec/lti/v1p3#role-vocabularies
        """
        from apps.users.models import User

        # Check for instructor/admin roles
        instructor_patterns = [
            "Instructor",
            "Teacher",
            "TeachingAssistant",
            "ContentDeveloper",
            "Faculty",
        ]
        admin_patterns = ["Administrator", "Manager", "SysAdmin"]

        for role in lti_roles:
            role_str = str(role)
            if any(pattern in role_str for pattern in admin_patterns):
                return User.Role.ADMIN
            if any(pattern in role_str for pattern in instructor_patterns):
                return User.Role.INSTRUCTOR

        # Default to learner
        return User.Role.LEARNER

    def is_deep_linking_request(self) -> bool:
        """Check if this is a deep linking request."""
        if not self._message_launch:
            return False
        return self._message_launch.is_deep_link_launch()

    def get_deep_linking_response_jwt(self, content_items: list) -> str:
        """
        Generate a deep linking response JWT with the selected content items.
        """
        if not self._message_launch:
            raise LTIServiceError(
                "No message launch available. Call validate_launch() first."
            )

        try:
            deep_link = self._message_launch.get_deep_link()
            return deep_link.output_response_form().get_launch_data()
        except Exception as e:
            logger.error(f"Deep linking response generation failed: {e}", exc_info=True)
            raise LTIServiceError(
                f"Deep linking response failed: {str(e)}"
            ) from e


class SSOService:
    """
    Manages SAML and OAuth SSO login processes.
    Supports multiple providers per tenant.
    """

    # Cache keys for SSO state
    STATE_CACHE_PREFIX = "sso_state_"
    STATE_CACHE_TIMEOUT = 600  # 10 minutes

    def __init__(self, request, sso_config: SSOConfiguration = None):
        self.request = request
        self.sso_config = sso_config
        self.tenant = getattr(request, "tenant", None)

    def _get_saml_settings(self, config: SSOConfiguration) -> dict:
        """
        Build python3-saml settings dictionary from SSOConfiguration.
        """
        # Get the base URL for this tenant
        base_url = self.request.build_absolute_uri("/").rstrip("/")

        return {
            "strict": True,
            "debug": settings.DEBUG,
            "sp": {
                "entityId": f"{base_url}/api/sso/saml/metadata/",
                "assertionConsumerService": {
                    "url": f"{base_url}/api/sso/saml/acs/",
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
                },
                "singleLogoutService": {
                    "url": f"{base_url}/api/sso/saml/sls/",
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
                },
                "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
            },
            "idp": {
                "entityId": config.idp_entity_id,
                "singleSignOnService": {
                    "url": config.idp_sso_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
                },
                "singleLogoutService": {
                    "url": config.idp_slo_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
                }
                if config.idp_slo_url
                else {},
                "x509cert": config.idp_x509_cert,
            },
            "security": {
                "authnRequestsSigned": False,
                "wantAssertionsSigned": True,
                "wantMessagesSigned": False,
                "wantNameIdEncrypted": False,
            },
        }

    def _prepare_saml_request(self) -> dict:
        """
        Prepare request data in the format expected by python3-saml.
        """
        return {
            "https": "on" if self.request.is_secure() else "off",
            "http_host": self.request.get_host(),
            "script_name": self.request.path,
            "server_port": self.request.get_port() if hasattr(self.request, 'get_port') else (
                "443" if self.request.is_secure() else "80"
            ),
            "get_data": self.request.GET.copy(),
            "post_data": self.request.POST.copy(),
        }

    def initiate_saml_login(self, config: SSOConfiguration = None, relay_state: str = None) -> str:
        """
        Initiates SAML authentication by redirecting to the IdP.
        Returns the redirect URL to the IdP's SSO endpoint.
        """
        from onelogin.saml2.auth import OneLogin_Saml2_Auth

        if config:
            self.sso_config = config
        if not self.sso_config or self.sso_config.provider_type != SSOConfiguration.ProviderType.SAML:
            raise SSOServiceError("Invalid or missing SAML configuration.")

        logger.info(f"Initiating SAML login for config: {self.sso_config.name}")

        try:
            saml_settings = self._get_saml_settings(self.sso_config)
            req = self._prepare_saml_request()
            auth = OneLogin_Saml2_Auth(req, saml_settings)

            # Generate the SAML AuthN request
            redirect_url = auth.login(return_to=relay_state)

            logger.info(f"SAML redirect URL generated: {redirect_url[:100]}...")
            return redirect_url

        except Exception as e:
            logger.error(f"SAML login initiation failed: {e}", exc_info=True)
            raise SSOServiceError(f"SAML login initiation failed: {str(e)}") from e

    @transaction.atomic
    def process_saml_response(self, config: SSOConfiguration = None) -> tuple[Any, str]:
        """
        Processes the SAML response from the IdP.
        Returns: (user, relay_state)
        """
        from onelogin.saml2.auth import OneLogin_Saml2_Auth

        if config:
            self.sso_config = config
        if not self.sso_config:
            raise SSOServiceError("No SAML configuration provided.")

        logger.info(f"Processing SAML response for config: {self.sso_config.name}")

        try:
            saml_settings = self._get_saml_settings(self.sso_config)
            req = self._prepare_saml_request()
            auth = OneLogin_Saml2_Auth(req, saml_settings)

            # Process the response
            auth.process_response()
            errors = auth.get_errors()

            if errors:
                error_reason = auth.get_last_error_reason()
                logger.error(f"SAML response errors: {errors}. Reason: {error_reason}")
                raise SSOServiceError(f"SAML response error: {error_reason or errors}")

            if not auth.is_authenticated():
                raise SSOServiceError("SAML authentication failed - user not authenticated.")

            # Extract user attributes
            attributes = auth.get_attributes()
            name_id = auth.get_nameid()
            relay_state = self.request.POST.get("RelayState", "/")

            # Map attributes to user fields
            user_data = self._map_saml_attributes(attributes, name_id)

            # Create or update user
            user = self._provision_sso_user(
                user_data,
                provider=f"saml_{self.sso_config.id}",
                subject_id=name_id,
            )

            logger.info(f"SAML authentication successful for user: {user.email}")
            return user, relay_state

        except SSOServiceError:
            raise
        except Exception as e:
            logger.error(f"SAML response processing failed: {e}", exc_info=True)
            raise SSOServiceError(f"SAML response processing failed: {str(e)}") from e

    def _map_saml_attributes(self, attributes: dict, name_id: str) -> dict:
        """
        Maps SAML attributes to user data using the configured attribute mapping.
        """
        mapping = self.sso_config.attribute_mapping or {}

        # Default mappings (common SAML attribute names)
        default_mapping = {
            "email": ["email", "mail", "emailAddress", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"],
            "first_name": ["firstName", "givenName", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname"],
            "last_name": ["lastName", "surname", "sn", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/surname"],
            "groups": ["groups", "memberOf", "http://schemas.microsoft.com/ws/2008/06/identity/claims/groups"],
        }

        user_data = {}

        for field, attr_names in default_mapping.items():
            # Check custom mapping first
            custom_attr = mapping.get(field)
            if custom_attr and custom_attr in attributes:
                value = attributes[custom_attr]
                user_data[field] = value[0] if isinstance(value, list) else value
                continue

            # Try default mappings
            for attr_name in attr_names:
                if attr_name in attributes:
                    value = attributes[attr_name]
                    user_data[field] = value[0] if isinstance(value, list) else value
                    break

        # Use name_id as email if not found in attributes
        if "email" not in user_data:
            user_data["email"] = name_id

        return user_data

    def get_oauth_redirect_url(self, config: SSOConfiguration = None) -> str:
        """
        Generates the OAuth authorization redirect URL.
        """
        if config:
            self.sso_config = config
        if not self.sso_config:
            raise SSOServiceError("No OAuth configuration provided.")

        logger.info(f"Generating OAuth redirect URL for config: {self.sso_config.name}")

        try:
            # Generate and store state for CSRF protection
            state = secrets.token_urlsafe(32)
            cache_key = f"{self.STATE_CACHE_PREFIX}{state}"
            cache.set(
                cache_key,
                {
                    "config_id": str(self.sso_config.id),
                    "tenant_id": str(self.tenant.id) if self.tenant else None,
                },
                timeout=self.STATE_CACHE_TIMEOUT,
            )

            # Build callback URL
            callback_url = self.request.build_absolute_uri("/api/sso/oauth/callback/")

            # Build authorization URL based on provider type
            params = {
                "client_id": self.sso_config.oauth_client_id,
                "redirect_uri": callback_url,
                "response_type": "code",
                "state": state,
                "scope": self.sso_config.oauth_scopes or "openid email profile",
            }

            # Provider-specific adjustments
            if self.sso_config.provider_type == SSOConfiguration.ProviderType.OAUTH_GOOGLE:
                auth_url = self.sso_config.oauth_authorization_url or "https://accounts.google.com/o/oauth2/v2/auth"
                params["access_type"] = "offline"
            elif self.sso_config.provider_type == SSOConfiguration.ProviderType.OAUTH_MICROSOFT:
                auth_url = self.sso_config.oauth_authorization_url or "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
            else:
                auth_url = self.sso_config.oauth_authorization_url

            if not auth_url:
                raise SSOServiceError("OAuth authorization URL not configured.")

            redirect_url = f"{auth_url}?{urlencode(params)}"
            logger.info(f"OAuth redirect URL generated: {redirect_url[:100]}...")
            return redirect_url

        except SSOServiceError:
            raise
        except Exception as e:
            logger.error(f"OAuth redirect URL generation failed: {e}", exc_info=True)
            raise SSOServiceError(f"OAuth redirect URL generation failed: {str(e)}") from e

    @transaction.atomic
    def process_oauth_callback(self) -> tuple[Any, str]:
        """
        Processes the OAuth callback after user authorization.
        Returns: (user, redirect_url)
        """
        import requests as http_requests

        logger.info("Processing OAuth callback...")

        # Get authorization code and state
        code = self.request.GET.get("code")
        state = self.request.GET.get("state")
        error = self.request.GET.get("error")

        if error:
            error_description = self.request.GET.get("error_description", error)
            raise SSOServiceError(f"OAuth error: {error_description}")

        if not code or not state:
            raise SSOServiceError("Missing authorization code or state.")

        # Validate state and get config
        cache_key = f"{self.STATE_CACHE_PREFIX}{state}"
        state_data = cache.get(cache_key)

        if not state_data:
            raise SSOServiceError("Invalid or expired OAuth state.")

        cache.delete(cache_key)  # State is single-use

        # Load the SSO configuration
        try:
            self.sso_config = SSOConfiguration.objects.get(
                id=state_data["config_id"], is_active=True
            )
        except SSOConfiguration.DoesNotExist:
            raise SSOServiceError("SSO configuration not found.")

        try:
            # Exchange code for tokens
            callback_url = self.request.build_absolute_uri("/api/sso/oauth/callback/")

            token_params = {
                "client_id": self.sso_config.oauth_client_id,
                "client_secret": self.sso_config.oauth_client_secret,
                "code": code,
                "redirect_uri": callback_url,
                "grant_type": "authorization_code",
            }

            # Get token URL
            if self.sso_config.provider_type == SSOConfiguration.ProviderType.OAUTH_GOOGLE:
                token_url = self.sso_config.oauth_token_url or "https://oauth2.googleapis.com/token"
            elif self.sso_config.provider_type == SSOConfiguration.ProviderType.OAUTH_MICROSOFT:
                token_url = self.sso_config.oauth_token_url or "https://login.microsoftonline.com/common/oauth2/v2.0/token"
            else:
                token_url = self.sso_config.oauth_token_url

            if not token_url:
                raise SSOServiceError("OAuth token URL not configured.")

            # Request tokens
            token_response = http_requests.post(token_url, data=token_params, timeout=30)
            token_response.raise_for_status()
            tokens = token_response.json()

            access_token = tokens.get("access_token")
            if not access_token:
                raise SSOServiceError("No access token in OAuth response.")

            # Fetch user info
            user_info = self._fetch_oauth_user_info(access_token)

            # Create or update user
            user = self._provision_sso_user(
                user_info,
                provider=f"oauth_{self.sso_config.provider_type.lower()}",
                subject_id=user_info.get("sub") or user_info.get("id"),
            )

            logger.info(f"OAuth authentication successful for user: {user.email}")
            return user, "/"  # Return default redirect

        except http_requests.RequestException as e:
            logger.error(f"OAuth token exchange failed: {e}", exc_info=True)
            raise SSOServiceError(f"OAuth token exchange failed: {str(e)}") from e
        except SSOServiceError:
            raise
        except Exception as e:
            logger.error(f"OAuth callback processing failed: {e}", exc_info=True)
            raise SSOServiceError(f"OAuth callback processing failed: {str(e)}") from e

    def _fetch_oauth_user_info(self, access_token: str) -> dict:
        """
        Fetches user information from the OAuth provider.
        """
        import requests as http_requests

        # Determine userinfo URL
        if self.sso_config.provider_type == SSOConfiguration.ProviderType.OAUTH_GOOGLE:
            userinfo_url = self.sso_config.oauth_userinfo_url or "https://www.googleapis.com/oauth2/v3/userinfo"
        elif self.sso_config.provider_type == SSOConfiguration.ProviderType.OAUTH_MICROSOFT:
            userinfo_url = self.sso_config.oauth_userinfo_url or "https://graph.microsoft.com/v1.0/me"
        else:
            userinfo_url = self.sso_config.oauth_userinfo_url

        if not userinfo_url:
            raise SSOServiceError("OAuth userinfo URL not configured.")

        headers = {"Authorization": f"Bearer {access_token}"}
        response = http_requests.get(userinfo_url, headers=headers, timeout=30)
        response.raise_for_status()

        user_info = response.json()

        # Normalize user info across providers
        normalized = {
            "email": user_info.get("email"),
            "first_name": user_info.get("given_name") or user_info.get("givenName") or "",
            "last_name": user_info.get("family_name") or user_info.get("surname") or "",
            "sub": user_info.get("sub") or user_info.get("id"),
        }

        # Microsoft Graph returns display name differently
        if not normalized["first_name"] and "displayName" in user_info:
            name_parts = user_info["displayName"].split(" ", 1)
            normalized["first_name"] = name_parts[0]
            normalized["last_name"] = name_parts[1] if len(name_parts) > 1 else ""

        return normalized

    def _provision_sso_user(
        self, user_data: dict, provider: str, subject_id: str
    ) -> Any:
        """
        Creates or updates a user based on SSO data.
        """
        from apps.users.models import User, UserProfile

        email = user_data.get("email")
        if not email:
            raise SSOServiceError("SSO response missing email address.")

        tenant = self.sso_config.tenant
        first_name = user_data.get("first_name", "")
        last_name = user_data.get("last_name", "")

        # Determine role from groups if configured
        groups = user_data.get("groups", [])
        role = self._map_sso_role(groups)

        logger.info(f"Provisioning SSO user: {email}, provider: {provider}")

        # Try to find existing user
        user = None

        # First, try by SSO identifiers
        try:
            user = User.objects.get(
                sso_provider=provider, sso_subject_id=subject_id, tenant=tenant
            )
        except User.DoesNotExist:
            # Try by email within tenant
            try:
                user = User.objects.get(email=email, tenant=tenant)
                # Link existing user to SSO
                user.sso_provider = provider
                user.sso_subject_id = subject_id
                user.save(update_fields=["sso_provider", "sso_subject_id", "updated_at"])
            except User.DoesNotExist:
                # Create new user
                user = User.objects.create(
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    role=role,
                    tenant=tenant,
                    sso_provider=provider,
                    sso_subject_id=subject_id,
                    status=User.Status.ACTIVE,
                    is_active=True,
                )
                # Create user profile
                UserProfile.objects.get_or_create(user=user)
                logger.info(f"Created new SSO user: {user.email}")
                return user

        # Update existing user info if needed
        update_fields = []
        if first_name and user.first_name != first_name:
            user.first_name = first_name
            update_fields.append("first_name")
        if last_name and user.last_name != last_name:
            user.last_name = last_name
            update_fields.append("last_name")
        if update_fields:
            update_fields.append("updated_at")
            user.save(update_fields=update_fields)

        return user

    def _map_sso_role(self, groups: list) -> str:
        """
        Maps SSO groups to LMS roles using the configured role mapping.
        """
        from apps.users.models import User

        role_mapping = self.sso_config.role_mapping or {}

        for group in groups:
            group_str = str(group).lower()
            for group_pattern, lms_role in role_mapping.items():
                if group_pattern.lower() in group_str:
                    if lms_role.upper() == "ADMIN":
                        return User.Role.ADMIN
                    elif lms_role.upper() == "INSTRUCTOR":
                        return User.Role.INSTRUCTOR

        # Default to learner
        return User.Role.LEARNER

    def get_saml_metadata(self, config: SSOConfiguration = None) -> str:
        """
        Generates the SP (Service Provider) SAML metadata XML.
        """
        from onelogin.saml2.settings import OneLogin_Saml2_Settings

        if config:
            self.sso_config = config
        if not self.sso_config:
            raise SSOServiceError("No SAML configuration provided.")

        try:
            saml_settings = self._get_saml_settings(self.sso_config)
            settings_obj = OneLogin_Saml2_Settings(saml_settings, sp_validation_only=True)
            metadata = settings_obj.get_sp_metadata()
            errors = settings_obj.validate_metadata(metadata)

            if errors:
                logger.warning(f"SAML metadata validation warnings: {errors}")

            return metadata

        except Exception as e:
            logger.error(f"SAML metadata generation failed: {e}", exc_info=True)
            raise SSOServiceError(f"SAML metadata generation failed: {str(e)}") from e

    def initiate_saml_logout(
        self, config: SSOConfiguration = None, name_id: str = None, session_index: str = None
    ) -> str:
        """
        Initiates SAML Single Logout by redirecting to the IdP's SLO endpoint.
        
        Args:
            config: Optional SSOConfiguration to use
            name_id: The NameID of the user (from the SAML assertion during login)
            session_index: The SessionIndex from the original authentication
            
        Returns:
            The redirect URL to the IdP's SLO endpoint
        """
        from onelogin.saml2.auth import OneLogin_Saml2_Auth

        if config:
            self.sso_config = config
        if not self.sso_config or self.sso_config.provider_type != SSOConfiguration.ProviderType.SAML:
            raise SSOServiceError("Invalid or missing SAML configuration.")

        if not self.sso_config.idp_slo_url:
            raise SSOServiceError("IdP Single Logout URL not configured.")

        logger.info(f"Initiating SAML logout for config: {self.sso_config.name}")

        try:
            saml_settings = self._get_saml_settings(self.sso_config)
            req = self._prepare_saml_request()
            auth = OneLogin_Saml2_Auth(req, saml_settings)

            # Generate the SAML LogoutRequest
            redirect_url = auth.logout(
                name_id=name_id,
                session_index=session_index,
                return_to=self.request.build_absolute_uri("/"),
            )

            logger.info(f"SAML logout redirect URL generated: {redirect_url[:100]}...")
            return redirect_url

        except Exception as e:
            logger.error(f"SAML logout initiation failed: {e}", exc_info=True)
            raise SSOServiceError(f"SAML logout initiation failed: {str(e)}") from e

    def process_saml_logout(self, config: SSOConfiguration = None) -> str | None:
        """
        Processes the SAML Single Logout response/request from the IdP.
        
        This handles both:
        - LogoutResponse: When the IdP responds to our LogoutRequest (SP-initiated logout)
        - LogoutRequest: When the IdP initiates the logout (IdP-initiated logout)
        
        Returns:
            The redirect URL after processing, or None if local logout only needed
        """
        from onelogin.saml2.auth import OneLogin_Saml2_Auth

        if config:
            self.sso_config = config
        if not self.sso_config:
            raise SSOServiceError("No SAML configuration provided.")

        logger.info(f"Processing SAML logout for config: {self.sso_config.name}")

        try:
            saml_settings = self._get_saml_settings(self.sso_config)
            req = self._prepare_saml_request()
            auth = OneLogin_Saml2_Auth(req, saml_settings)

            # Define a callback to delete the local session
            def delete_session():
                logger.info("SAML SLS: Local session deletion callback invoked")
                # The actual session invalidation will be done in the view

            # Process the SLO message
            redirect_url = auth.process_slo(
                delete_session_cb=delete_session,
                keep_local_session=False,
            )

            errors = auth.get_errors()
            if errors:
                error_reason = auth.get_last_error_reason()
                logger.error(f"SAML SLO errors: {errors}. Reason: {error_reason}")
                raise SSOServiceError(f"SAML SLO error: {error_reason or errors}")

            logger.info(f"SAML logout processed successfully, redirect_url: {redirect_url}")
            return redirect_url

        except SSOServiceError:
            raise
        except Exception as e:
            logger.error(f"SAML logout processing failed: {e}", exc_info=True)
            raise SSOServiceError(f"SAML logout processing failed: {str(e)}") from e
