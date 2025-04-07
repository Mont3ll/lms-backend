#!/bin/bash

# Create apps directory and common app structure
mkdir -p apps/common/tests apps/common/migrations
touch apps/__init__.py
touch apps/common/__init__.py
touch apps/common/apps.py
touch apps/common/models.py
touch apps/common/admin.py
touch apps/common/exceptions.py
touch apps/common/pagination.py
touch apps/common/permissions.py
touch apps/common/serializers.py
touch apps/common/utils.py
touch apps/common/tests/__init__.py
touch apps/common/migrations/__init__.py

# Create other app structures
APPS=("core" "users" "courses" "assessments" "files" "learning_paths" "enrollments" "ai_engine" "notifications" "analytics")
for APP in "${APPS[@]}"; do
  mkdir -p apps/$APP/tests apps/$APP/migrations apps/$APP/management/commands apps/$APP/services apps/$APP/tasks apps/$APP/adapters apps/$APP/content_types apps/$APP/question_types
  touch apps/$APP/__init__.py
  touch apps/$APP/apps.py
  touch apps/$APP/models.py
  touch apps/$APP/admin.py
  touch apps/$APP/serializers.py
  touch apps/$APP/views.py
  touch apps/$APP/viewsets.py
  touch apps/$APP/urls.py
  touch apps/$APP/permissions.py
  # Clean up potentially unused subdirs for some apps if desired, or leave for consistency
  # Example cleanup (optional): rm -rf apps/core/management apps/core/tasks etc.
  touch apps/$APP/tests/__init__.py
  touch apps/$APP/migrations/__init__.py
  touch apps/$APP/management/__init__.py
  touch apps/$APP/management/commands/__init__.py
done

# Create settings structure
mkdir lms_backend/settings
mv lms_backend/settings.py lms_backend/settings/base.py
touch lms_backend/settings/__init__.py
touch lms_backend/settings/development.py
touch lms_backend/settings/production.py

# Create other root files
touch .env .gitignore Containerfile README.md
mkdir scripts
touch scripts/seed_demo_data.py

echo "Backend structure created."
