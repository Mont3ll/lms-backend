"""
Tests for analytics app viewsets - Dashboard and Widget CRUD operations.
"""
import uuid

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.analytics.models import Dashboard, DashboardWidget
from apps.core.models import Tenant
from apps.users.models import User


class DashboardDefinitionViewSetTests(TestCase):
    """Tests for DashboardDefinitionViewSet."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            role=User.Role.INSTRUCTOR,
            tenant=self.tenant
        )
        self.other_instructor = User.objects.create_user(
            email="other_instructor@example.com",
            password="testpass123",
            role=User.Role.INSTRUCTOR,
            tenant=self.tenant
        )
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="testpass123",
            role=User.Role.ADMIN,
            is_staff=True,
            tenant=self.tenant
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            role=User.Role.LEARNER,
            tenant=self.tenant
        )

        # Create test dashboards
        self.own_dashboard = Dashboard.objects.create(
            tenant=self.tenant,
            owner=self.instructor,
            name="My Dashboard",
            slug="my-dashboard",
            description="Instructor's private dashboard",
            is_shared=False,
            is_default=False,
        )
        self.other_private_dashboard = Dashboard.objects.create(
            tenant=self.tenant,
            owner=self.other_instructor,
            name="Other's Dashboard",
            slug="others-dashboard",
            description="Other instructor's private dashboard",
            is_shared=False,
            is_default=False,
        )
        self.shared_dashboard = Dashboard.objects.create(
            tenant=self.tenant,
            owner=self.other_instructor,
            name="Shared Dashboard",
            slug="shared-dashboard",
            description="A shared dashboard",
            is_shared=True,
            is_default=False,
        )
        self.default_instructor_dashboard = Dashboard.objects.create(
            tenant=self.tenant,
            owner=self.admin,
            name="Default Instructor Dashboard",
            slug="default-instructor-dashboard",
            description="Default dashboard for instructors",
            is_shared=False,
            is_default=True,
            allowed_roles=[User.Role.INSTRUCTOR],  # Use uppercase constant
        )
        self.default_learner_dashboard = Dashboard.objects.create(
            tenant=self.tenant,
            owner=self.admin,
            name="Default Learner Dashboard",
            slug="default-learner-dashboard",
            description="Default dashboard for learners",
            is_shared=False,
            is_default=True,
            allowed_roles=[User.Role.LEARNER],  # Use uppercase constant
        )

        # Add widgets to own_dashboard for clone tests
        self.widget1 = DashboardWidget.objects.create(
            dashboard=self.own_dashboard,
            widget_type=DashboardWidget.WidgetType.STAT_CARD,
            title="Total Users",
            data_source=DashboardWidget.DataSource.USER_GROWTH,
            position_x=0,
            position_y=0,
            width=4,
            height=2,
        )
        self.widget2 = DashboardWidget.objects.create(
            dashboard=self.own_dashboard,
            widget_type=DashboardWidget.WidgetType.LINE_CHART,
            title="Enrollment Trend",
            data_source=DashboardWidget.DataSource.ENROLLMENT_STATS,
            position_x=4,
            position_y=0,
            width=8,
            height=4,
        )

    def _get_list_url(self):
        """Get URL for dashboard list."""
        return reverse("analytics:dashboard-list")

    def _get_detail_url(self, dashboard_id):
        """Get URL for dashboard detail."""
        return reverse("analytics:dashboard-detail", kwargs={"pk": dashboard_id})

    def _get_clone_url(self, dashboard_id):
        """Get URL for dashboard clone action."""
        return reverse("analytics:dashboard-clone", kwargs={"pk": dashboard_id})

    def _get_share_url(self, dashboard_id):
        """Get URL for dashboard share action."""
        return reverse("analytics:dashboard-share", kwargs={"pk": dashboard_id})

    def _get_set_default_url(self, dashboard_id):
        """Get URL for dashboard set_default action."""
        return reverse("analytics:dashboard-set-default", kwargs={"pk": dashboard_id})

    # --- List Tests ---

    def test_list_dashboards_own(self):
        """Test that user sees their own dashboards."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_list_url(),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        dashboard_ids = [d["id"] for d in results]
        self.assertIn(str(self.own_dashboard.id), dashboard_ids)

    def test_list_dashboards_shared(self):
        """Test that user sees shared dashboards from others in tenant."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_list_url(),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        dashboard_ids = [d["id"] for d in results]
        self.assertIn(str(self.shared_dashboard.id), dashboard_ids)

    def test_list_dashboards_default_for_role(self):
        """Test that user sees default dashboards matching their role."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_list_url(),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        dashboard_ids = [d["id"] for d in results]
        # Instructor should see instructor default dashboard
        self.assertIn(str(self.default_instructor_dashboard.id), dashboard_ids)
        # Instructor should NOT see learner default dashboard
        self.assertNotIn(str(self.default_learner_dashboard.id), dashboard_ids)

    def test_list_dashboards_excludes_others_private(self):
        """Test that user cannot see others' non-shared dashboards."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_list_url(),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        dashboard_ids = [d["id"] for d in results]
        self.assertNotIn(str(self.other_private_dashboard.id), dashboard_ids)

    def test_list_dashboards_learner_sees_correct_default(self):
        """Test that learner sees learner default dashboard, not instructor's."""
        self.client.force_authenticate(user=self.learner)
        response = self.client.get(
            self._get_list_url(),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        dashboard_ids = [d["id"] for d in results]
        # Learner should see learner default dashboard
        self.assertIn(str(self.default_learner_dashboard.id), dashboard_ids)
        # Learner should NOT see instructor default dashboard
        self.assertNotIn(str(self.default_instructor_dashboard.id), dashboard_ids)

    def test_list_dashboards_unauthenticated(self):
        """Test that unauthenticated users cannot list dashboards."""
        response = self.client.get(
            self._get_list_url(),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # --- Create Tests ---

    def test_create_dashboard(self):
        """Test that user can create a dashboard."""
        self.client.force_authenticate(user=self.instructor)
        data = {
            "name": "New Dashboard",
            "slug": "new-dashboard",
            "description": "A brand new dashboard",
            "default_time_range": "30d",
        }
        response = self.client.post(
            self._get_list_url(),
            data,
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "New Dashboard")

    def test_create_dashboard_auto_sets_owner_and_tenant(self):
        """Test that owner and tenant are set automatically on create."""
        self.client.force_authenticate(user=self.instructor)
        data = {
            "name": "Auto Owner Dashboard",
            "slug": "auto-owner-dashboard",
        }
        response = self.client.post(
            self._get_list_url(),
            data,
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        dashboard = Dashboard.objects.get(id=response.data["id"])
        self.assertEqual(dashboard.owner, self.instructor)
        self.assertEqual(dashboard.tenant, self.tenant)

    def test_create_dashboard_with_widgets(self):
        """Test creating a dashboard with widgets in one request."""
        self.client.force_authenticate(user=self.instructor)
        data = {
            "name": "Dashboard with Widgets",
            "slug": "dashboard-with-widgets",
            "widgets": [
                {
                    "widget_type": "stat_card",
                    "title": "Widget 1",
                    "data_source": "user_growth",
                    "position_x": 0,
                    "position_y": 0,
                    "width": 4,
                    "height": 2,
                },
                {
                    "widget_type": "bar_chart",
                    "title": "Widget 2",
                    "data_source": "enrollment_stats",
                    "position_x": 4,
                    "position_y": 0,
                    "width": 8,
                    "height": 4,
                },
            ],
        }
        response = self.client.post(
            self._get_list_url(),
            data,
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        dashboard = Dashboard.objects.get(id=response.data["id"])
        self.assertEqual(dashboard.widgets.count(), 2)

    # --- Retrieve Tests ---

    def test_retrieve_dashboard_detail_own(self):
        """Test that user can retrieve their own dashboard detail."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_detail_url(self.own_dashboard.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "My Dashboard")
        self.assertIn("widgets", response.data)
        self.assertEqual(len(response.data["widgets"]), 2)

    def test_retrieve_dashboard_shared(self):
        """Test that user can retrieve shared dashboard detail."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_detail_url(self.shared_dashboard.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Shared Dashboard")

    def test_retrieve_dashboard_others_private_denied(self):
        """Test that user cannot retrieve others' private dashboard."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_detail_url(self.other_private_dashboard.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --- Update Tests ---

    def test_update_dashboard_own(self):
        """Test that user can update their own dashboard."""
        self.client.force_authenticate(user=self.instructor)
        data = {
            "name": "Updated Dashboard Name",
            "description": "Updated description",
        }
        response = self.client.patch(
            self._get_detail_url(self.own_dashboard.id),
            data,
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.own_dashboard.refresh_from_db()
        self.assertEqual(self.own_dashboard.name, "Updated Dashboard Name")
        self.assertEqual(self.own_dashboard.description, "Updated description")

    def test_update_dashboard_others_denied(self):
        """Test that user cannot update others' dashboards."""
        self.client.force_authenticate(user=self.instructor)
        data = {"name": "Hacked Name"}
        response = self.client.patch(
            self._get_detail_url(self.other_private_dashboard.id),
            data,
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        # Should be 404 because they can't even see it in queryset
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_dashboard_shared_by_non_owner_denied(self):
        """Test that user cannot update shared dashboard they don't own."""
        self.client.force_authenticate(user=self.instructor)
        data = {"name": "Hacked Shared Name"}
        response = self.client.patch(
            self._get_detail_url(self.shared_dashboard.id),
            data,
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_update_dashboard_staff_override(self):
        """Test that staff can update any dashboard."""
        self.client.force_authenticate(user=self.admin)
        data = {"name": "Admin Updated Name"}
        response = self.client.patch(
            self._get_detail_url(self.own_dashboard.id),
            data,
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.own_dashboard.refresh_from_db()
        self.assertEqual(self.own_dashboard.name, "Admin Updated Name")

    # --- Delete Tests ---

    def test_delete_dashboard_own(self):
        """Test that user can delete their own dashboard."""
        self.client.force_authenticate(user=self.instructor)
        dashboard_id = self.own_dashboard.id
        response = self.client.delete(
            self._get_detail_url(dashboard_id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Dashboard.objects.filter(id=dashboard_id).exists())

    def test_delete_dashboard_others_denied(self):
        """Test that user cannot delete others' dashboards."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.delete(
            self._get_detail_url(self.other_private_dashboard.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        # Should be 404 because they can't see it
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_dashboard_shared_by_non_owner_denied(self):
        """Test that user cannot delete shared dashboard they don't own."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.delete(
            self._get_detail_url(self.shared_dashboard.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_dashboard_staff_override(self):
        """Test that staff can delete any dashboard."""
        self.client.force_authenticate(user=self.admin)
        # Create a dashboard to delete (don't delete fixture dashboards)
        dashboard = Dashboard.objects.create(
            tenant=self.tenant,
            owner=self.instructor,
            name="To Delete",
            slug="to-delete",
        )
        response = self.client.delete(
            self._get_detail_url(dashboard.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Dashboard.objects.filter(id=dashboard.id).exists())

    # --- Clone Tests ---

    def test_clone_dashboard(self):
        """Test that user can clone a dashboard."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.post(
            self._get_clone_url(self.own_dashboard.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "My Dashboard (Copy)")
        self.assertNotEqual(response.data["id"], str(self.own_dashboard.id))
        
        # Verify widgets were cloned
        cloned_dashboard = Dashboard.objects.get(id=response.data["id"])
        self.assertEqual(cloned_dashboard.widgets.count(), 2)

    def test_clone_dashboard_creates_copy_with_correct_owner(self):
        """Test that cloned dashboard is owned by the user who cloned it."""
        self.client.force_authenticate(user=self.learner)
        # Clone shared dashboard as learner
        response = self.client.post(
            self._get_clone_url(self.shared_dashboard.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        cloned_dashboard = Dashboard.objects.get(id=response.data["id"])
        self.assertEqual(cloned_dashboard.owner, self.learner)
        # Original owner should be different
        self.assertNotEqual(cloned_dashboard.owner, self.shared_dashboard.owner)

    def test_clone_dashboard_resets_default_and_shared(self):
        """Test that cloned dashboard has is_default=False and is_shared=False."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.post(
            self._get_clone_url(self.default_instructor_dashboard.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        cloned_dashboard = Dashboard.objects.get(id=response.data["id"])
        self.assertFalse(cloned_dashboard.is_default)
        self.assertFalse(cloned_dashboard.is_shared)

    # --- Share Tests ---

    def test_share_dashboard_own(self):
        """Test that user can toggle share on their dashboard."""
        self.client.force_authenticate(user=self.instructor)
        self.assertFalse(self.own_dashboard.is_shared)

        response = self.client.post(
            self._get_share_url(self.own_dashboard.id),
            {"is_shared": True},
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.own_dashboard.refresh_from_db()
        self.assertTrue(self.own_dashboard.is_shared)

    def test_share_dashboard_toggle_off(self):
        """Test that user can unshare their dashboard."""
        self.client.force_authenticate(user=self.other_instructor)
        self.assertTrue(self.shared_dashboard.is_shared)

        response = self.client.post(
            self._get_share_url(self.shared_dashboard.id),
            {"is_shared": False},
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.shared_dashboard.refresh_from_db()
        self.assertFalse(self.shared_dashboard.is_shared)

    def test_share_dashboard_others_denied(self):
        """Test that user cannot share others' dashboards."""
        self.client.force_authenticate(user=self.instructor)
        # Try to share other_instructor's shared dashboard (even though it's visible)
        response = self.client.post(
            self._get_share_url(self.shared_dashboard.id),
            {"is_shared": False},
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_share_dashboard_staff_override(self):
        """Test that staff can share any dashboard."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            self._get_share_url(self.own_dashboard.id),
            {"is_shared": True},
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.own_dashboard.refresh_from_db()
        self.assertTrue(self.own_dashboard.is_shared)

    # --- Set Default Tests ---

    def test_set_default_dashboard_staff_only(self):
        """Test that only staff can set default dashboards."""
        self.client.force_authenticate(user=self.admin)
        # Create a new dashboard to set as default
        dashboard = Dashboard.objects.create(
            tenant=self.tenant,
            owner=self.admin,
            name="New Default",
            slug="new-default",
        )
        response = self.client.post(
            self._get_set_default_url(dashboard.id),
            {"roles": ["instructor", "admin"]},
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        dashboard.refresh_from_db()
        self.assertTrue(dashboard.is_default)
        self.assertEqual(dashboard.allowed_roles, ["instructor", "admin"])

    def test_set_default_dashboard_non_staff_denied(self):
        """Test that non-staff cannot set default dashboards."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.post(
            self._get_set_default_url(self.own_dashboard.id),
            {"roles": ["instructor"]},
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_set_default_removes_other_defaults_for_role(self):
        """Test that setting a new default removes the old default for that role."""
        self.client.force_authenticate(user=self.admin)
        # Create a new dashboard to set as default for instructors
        new_default = Dashboard.objects.create(
            tenant=self.tenant,
            owner=self.admin,
            name="New Instructor Default",
            slug="new-instructor-default",
        )
        
        # Verify old default exists
        self.assertTrue(self.default_instructor_dashboard.is_default)

        response = self.client.post(
            self._get_set_default_url(new_default.id),
            {"roles": [User.Role.INSTRUCTOR]},  # Use uppercase constant
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        new_default.refresh_from_db()
        self.default_instructor_dashboard.refresh_from_db()
        
        # New dashboard should be default
        self.assertTrue(new_default.is_default)
        # Old dashboard should no longer be default
        self.assertFalse(self.default_instructor_dashboard.is_default)


class DashboardWidgetViewSetTests(TestCase):
    """Tests for DashboardWidgetViewSet."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant-widgets"
        )
        self.instructor = User.objects.create_user(
            email="widget_instructor@example.com",
            password="testpass123",
            role=User.Role.INSTRUCTOR,
            tenant=self.tenant
        )
        self.other_instructor = User.objects.create_user(
            email="widget_other_instructor@example.com",
            password="testpass123",
            role=User.Role.INSTRUCTOR,
            tenant=self.tenant
        )
        self.admin = User.objects.create_user(
            email="widget_admin@example.com",
            password="testpass123",
            role=User.Role.ADMIN,
            is_staff=True,
            tenant=self.tenant
        )

        # Create dashboards
        self.own_dashboard = Dashboard.objects.create(
            tenant=self.tenant,
            owner=self.instructor,
            name="My Widget Dashboard",
            slug="my-widget-dashboard",
        )
        self.other_dashboard = Dashboard.objects.create(
            tenant=self.tenant,
            owner=self.other_instructor,
            name="Other Widget Dashboard",
            slug="other-widget-dashboard",
            is_shared=True,
        )

        # Create widgets
        self.widget1 = DashboardWidget.objects.create(
            dashboard=self.own_dashboard,
            widget_type=DashboardWidget.WidgetType.STAT_CARD,
            title="Widget 1",
            data_source=DashboardWidget.DataSource.USER_GROWTH,
            position_x=0,
            position_y=0,
            width=4,
            height=2,
            order=0,
        )
        self.widget2 = DashboardWidget.objects.create(
            dashboard=self.own_dashboard,
            widget_type=DashboardWidget.WidgetType.LINE_CHART,
            title="Widget 2",
            data_source=DashboardWidget.DataSource.ENROLLMENT_STATS,
            position_x=4,
            position_y=0,
            width=8,
            height=4,
            order=1,
        )
        self.other_widget = DashboardWidget.objects.create(
            dashboard=self.other_dashboard,
            widget_type=DashboardWidget.WidgetType.BAR_CHART,
            title="Other Widget",
            data_source=DashboardWidget.DataSource.COURSE_METRICS,
            position_x=0,
            position_y=0,
            width=6,
            height=3,
        )

    def _get_list_url(self, dashboard_id):
        """Get URL for widget list within a dashboard."""
        return reverse(
            "analytics:dashboard-widget-list",
            kwargs={"dashboard_pk": dashboard_id}
        )

    def _get_detail_url(self, dashboard_id, widget_id):
        """Get URL for widget detail."""
        return reverse(
            "analytics:dashboard-widget-detail",
            kwargs={"dashboard_pk": dashboard_id, "pk": widget_id}
        )

    def _get_bulk_update_url(self, dashboard_id):
        """Get URL for bulk position update."""
        return reverse(
            "analytics:dashboard-widget-bulk-update-positions",
            kwargs={"dashboard_pk": dashboard_id}
        )

    # --- List Tests ---

    def test_list_widgets_in_dashboard(self):
        """Test listing widgets for a specific dashboard."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_list_url(self.own_dashboard.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 2)

    def test_list_widgets_ordered_correctly(self):
        """Test that widgets are ordered by order, then position."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_list_url(self.own_dashboard.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(results[0]["title"], "Widget 1")
        self.assertEqual(results[1]["title"], "Widget 2")

    # --- Create Tests ---

    def test_create_widget_own_dashboard(self):
        """Test that user can add widget to own dashboard."""
        self.client.force_authenticate(user=self.instructor)
        data = {
            "widget_type": "pie_chart",
            "title": "New Widget",
            "data_source": "device_usage",
            "position_x": 0,
            "position_y": 4,
            "width": 6,
            "height": 4,
        }
        response = self.client.post(
            self._get_list_url(self.own_dashboard.id),
            data,
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "New Widget")
        self.assertEqual(self.own_dashboard.widgets.count(), 3)

    def test_create_widget_others_dashboard_denied(self):
        """Test that user cannot add widget to others' dashboards."""
        self.client.force_authenticate(user=self.instructor)
        data = {
            "widget_type": "stat_card",
            "title": "Sneaky Widget",
            "data_source": "user_growth",
            "position_x": 0,
            "position_y": 0,
            "width": 4,
            "height": 2,
        }
        response = self.client.post(
            self._get_list_url(self.other_dashboard.id),
            data,
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_widget_staff_override(self):
        """Test that staff can add widget to any dashboard."""
        self.client.force_authenticate(user=self.admin)
        data = {
            "widget_type": "table",
            "title": "Admin Widget",
            "data_source": "recent_activity",
            "position_x": 6,
            "position_y": 0,
            "width": 6,
            "height": 4,
        }
        response = self.client.post(
            self._get_list_url(self.own_dashboard.id),
            data,
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    # --- Retrieve Tests ---

    def test_retrieve_widget_detail(self):
        """Test retrieving a widget's details."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_detail_url(self.own_dashboard.id, self.widget1.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Widget 1")
        self.assertEqual(response.data["widget_type"], "stat_card")

    # --- Update Tests ---

    def test_update_widget_own_dashboard(self):
        """Test that user can update widget in own dashboard."""
        self.client.force_authenticate(user=self.instructor)
        data = {
            "title": "Updated Widget Title",
            "width": 6,
        }
        response = self.client.patch(
            self._get_detail_url(self.own_dashboard.id, self.widget1.id),
            data,
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.widget1.refresh_from_db()
        self.assertEqual(self.widget1.title, "Updated Widget Title")
        self.assertEqual(self.widget1.width, 6)

    def test_update_widget_others_denied(self):
        """Test that user cannot update widget in others' dashboard."""
        self.client.force_authenticate(user=self.instructor)
        data = {"title": "Hacked Title"}
        response = self.client.patch(
            self._get_detail_url(self.other_dashboard.id, self.other_widget.id),
            data,
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_update_widget_staff_override(self):
        """Test that staff can update any widget."""
        self.client.force_authenticate(user=self.admin)
        data = {"title": "Admin Updated Title"}
        response = self.client.patch(
            self._get_detail_url(self.own_dashboard.id, self.widget1.id),
            data,
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.widget1.refresh_from_db()
        self.assertEqual(self.widget1.title, "Admin Updated Title")

    # --- Delete Tests ---

    def test_delete_widget_own_dashboard(self):
        """Test that user can delete widget from own dashboard."""
        self.client.force_authenticate(user=self.instructor)
        widget_id = self.widget1.id
        response = self.client.delete(
            self._get_detail_url(self.own_dashboard.id, widget_id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(DashboardWidget.objects.filter(id=widget_id).exists())

    def test_delete_widget_others_denied(self):
        """Test that user cannot delete widget from others' dashboard."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.delete(
            self._get_detail_url(self.other_dashboard.id, self.other_widget.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_widget_staff_override(self):
        """Test that staff can delete any widget."""
        self.client.force_authenticate(user=self.admin)
        # Create a widget to delete
        widget = DashboardWidget.objects.create(
            dashboard=self.own_dashboard,
            widget_type=DashboardWidget.WidgetType.STAT_CARD,
            title="To Delete",
            data_source=DashboardWidget.DataSource.ACTIVE_USERS,
        )
        response = self.client.delete(
            self._get_detail_url(self.own_dashboard.id, widget.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    # --- Bulk Update Positions Tests ---

    def test_bulk_update_positions(self):
        """Test that user can bulk update widget positions."""
        self.client.force_authenticate(user=self.instructor)
        data = [
            {
                "id": str(self.widget1.id),
                "position_x": 4,
                "position_y": 2,
                "width": 6,
                "height": 3,
            },
            {
                "id": str(self.widget2.id),
                "position_x": 0,
                "position_y": 0,
                "width": 4,
                "height": 2,
            },
        ]
        response = self.client.post(
            self._get_bulk_update_url(self.own_dashboard.id),
            data,
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.widget1.refresh_from_db()
        self.widget2.refresh_from_db()
        
        self.assertEqual(self.widget1.position_x, 4)
        self.assertEqual(self.widget1.position_y, 2)
        self.assertEqual(self.widget1.width, 6)
        self.assertEqual(self.widget1.height, 3)
        
        self.assertEqual(self.widget2.position_x, 0)
        self.assertEqual(self.widget2.position_y, 0)

    def test_bulk_update_positions_others_denied(self):
        """Test that user cannot bulk update others' widgets."""
        self.client.force_authenticate(user=self.instructor)
        data = [
            {"id": str(self.other_widget.id), "position_x": 10, "position_y": 10},
        ]
        response = self.client.post(
            self._get_bulk_update_url(self.other_dashboard.id),
            data,
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_bulk_update_positions_invalid_format(self):
        """Test that invalid format returns 400."""
        self.client.force_authenticate(user=self.instructor)
        # Send an object instead of a list
        data = {"id": str(self.widget1.id), "position_x": 10}
        response = self.client.post(
            self._get_bulk_update_url(self.own_dashboard.id),
            data,
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_update_positions_skips_invalid_ids(self):
        """Test that bulk update skips widgets that don't exist."""
        self.client.force_authenticate(user=self.instructor)
        fake_id = str(uuid.uuid4())
        data = [
            {"id": str(self.widget1.id), "position_x": 5},
            {"id": fake_id, "position_x": 99},  # Non-existent widget
        ]
        response = self.client.post(
            self._get_bulk_update_url(self.own_dashboard.id),
            data,
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should only have updated one widget
        self.assertEqual(len(response.data), 1)
        
        self.widget1.refresh_from_db()
        self.assertEqual(self.widget1.position_x, 5)

    def test_bulk_update_positions_partial_fields(self):
        """Test that bulk update only updates provided fields."""
        self.client.force_authenticate(user=self.instructor)
        original_width = self.widget1.width
        original_height = self.widget1.height
        
        data = [
            {"id": str(self.widget1.id), "position_x": 8, "position_y": 6},
        ]
        response = self.client.post(
            self._get_bulk_update_url(self.own_dashboard.id),
            data,
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.widget1.refresh_from_db()
        self.assertEqual(self.widget1.position_x, 8)
        self.assertEqual(self.widget1.position_y, 6)
        # Width and height should be unchanged
        self.assertEqual(self.widget1.width, original_width)
        self.assertEqual(self.widget1.height, original_height)

    def test_bulk_update_order(self):
        """Test that bulk update can update widget order."""
        self.client.force_authenticate(user=self.instructor)
        data = [
            {"id": str(self.widget1.id), "order": 5},
            {"id": str(self.widget2.id), "order": 1},
        ]
        response = self.client.post(
            self._get_bulk_update_url(self.own_dashboard.id),
            data,
            format="json",
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.widget1.refresh_from_db()
        self.widget2.refresh_from_db()
        
        self.assertEqual(self.widget1.order, 5)
        self.assertEqual(self.widget2.order, 1)
