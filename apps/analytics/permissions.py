from rest_framework import permissions

# Reuse IsAdminOrTenantAdmin from users app for managing reports/dashboards.
# Permissions for viewing report data checked within the GenerateReportDataView.
