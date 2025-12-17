# LMS Platform - Backend

This directory contains the backend application for the Learning Management System (LMS) platform, built with Django and Django REST Framework.

## Features

- Multi-Tenant Architecture (Conceptual - using Tenant model)
- User Management (Custom User Model, JWT Auth, Roles, Groups)
- Course & Content Management (Courses, Modules, Various Content Types)
- Assessment Engine (Quizzes, Questions, Attempts, Basic Auto-Grading)
- File Management (Integration with Cloud Storage - S3 assumed)
- Enrollment & Progress Tracking
- Learning Paths (Sequenced Content)
- **Skills & Competencies** (Skill taxonomy, proficiency tracking, gap analysis)
- **Personalized Learning Paths** (AI-generated paths based on skills, goals, or assessment results)
- AI Engine (Content Generation Job Management - OpenAI adapter example)
- Notification System (Email, In-App - DB record based)
- Analytics & Reporting (Event Tracking, Basic Report Definitions)
- RESTful API with OpenAPI Schema Documentation

## Tech Stack

- **Framework:** Django, Django REST Framework
- **Language:** Python 3.10+
- **Database:** PostgreSQL
- **Cache:** Redis
- **Async Tasks:** Celery (with Redis/RabbitMQ broker)
- **Authentication:** JWT (djangorestframework-simplejwt)
- **API Docs:** drf-spectacular (OpenAPI)
- **Dependencies:** Poetry
- **Storage:** django-storages (configured for AWS S3 by default)
- **Containerization:** Docker / Podman

## Setup and Installation

1.  **Prerequisites:**
    - Python 3.10+
    - Poetry (`pip install poetry`)
    - PostgreSQL Server (Running locally or accessible)
    - Redis Server (Running locally or accessible)

2.  **Clone the Repository:**

    ```bash
    git clone <repository_url>
    cd lms/backend
    ```

3.  **Environment Variables:**
    Create a `.env` file in the `lms/backend` directory. Copy the contents from `.env.example` (if provided) or use the structure below, filling in your actual credentials and settings:

    ```dotenv
    # Django Core
    SECRET_KEY='your-strong-django-secret-key-here' # REQUIRED for production
    DEBUG=True # Set to False in production
    ALLOWED_HOSTS=localhost,127.0.0.1 # Add production domains

    # Database (PostgreSQL)
    DATABASE_URL=postgres://lms_user:lms_password@localhost:5432/lms_db

    # Cache (Redis)
    CACHE_URL=redis://localhost:6379/1

    # Celery (Redis)
    CELERY_BROKER_URL=redis://localhost:6379/0
    CELERY_RESULT_BACKEND=redis://localhost:6379/0

    # Email (Example: Console for dev, configure SMTP for prod)
    EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
    # EMAIL_HOST=...
    # EMAIL_PORT=...
    # EMAIL_USE_TLS=True
    # EMAIL_HOST_USER=...
    # EMAIL_HOST_PASSWORD=...
    DEFAULT_FROM_EMAIL=noreply@lms.example.com

    # Cloud Storage (AWS S3 Example) - REQUIRED if using S3
    AWS_ACCESS_KEY_ID=YOUR_AWS_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY=YOUR_AWS_SECRET_ACCESS_KEY
    AWS_STORAGE_BUCKET_NAME=your-lms-media-bucket
    AWS_S3_REGION_NAME=your-aws-region # e.g., us-east-1
    # AWS_S3_ENDPOINT_URL= # Optional: for MinIO etc.
    # AWS_S3_CUSTOM_DOMAIN= # Optional: cdn.yourdomain.com

    # AI Services (Example OpenAI)
    OPENAI_API_KEY=sk-your-openai-api-key # Required if using AI features

    # JWT Settings
    JWT_SECRET_KEY='your-strong-jwt-secret-key-here' # REQUIRED, can be same as SECRET_KEY or different

    # CORS Allowed Origins (REQUIRED for frontend interaction)
    CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000 # Add production frontend URL(s)

    # Settings Environment ('development' or 'production')
    DJANGO_SETTINGS_ENV=development
    ```

4.  **Install Dependencies:**

    ```bash
    poetry install
    ```

5.  **Activate Virtual Environment:**

    ```bash
    poetry shell
    # Or source .venv/bin/activate manually
    ```

6.  **Apply Database Migrations:**

    ```bash
    python manage.py migrate
    ```

7.  **Create Superuser (Optional):**

    ```bash
    python manage.py createsuperuser
    ```

8.  **Run Development Server:**

    ```bash
    python manage.py runserver
    ```

    The backend API should now be running, typically at `http://127.0.0.1:8000/`.

9.  **Run Celery Worker (for async tasks):**
    In a separate terminal (with the virtual environment activated):
    ```bash
    celery -A lms_backend worker --loglevel=info
    ```
    Optional: Run Celery Beat for scheduled tasks (if configured):
    ```bash
    celery -A lms_backend beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    ```

## API Documentation

Once the server is running, API documentation (OpenAPI/Swagger UI) is available at:

- `/api/schema/swagger-ui/`
- `/api/schema/redoc/`

## Running Tests

```bash
python manage.py test apps/ # Run tests for all apps
# or specify an app:
# python manage.py test apps.courses
```

## Seed Demo Data

Populate the database with comprehensive demo data for testing:

```bash
# Clear existing data and seed fresh
python manage.py seed_demo_data --clear

# Or add data without clearing (may cause duplicates)
python manage.py seed_demo_data
```

### Test Credentials

All accounts use the password: `password123`

| Role         | Acme Learning (acme.localhost) | TechU Academy (techu.localhost) |
| ------------ | ------------------------------ | ------------------------------- |
| Superuser    | admin@lms.local                | admin@lms.local                 |
| Tenant Admin | admin@acme.local               | admin@techu.local               |
| Instructor   | john.smith@acme.local          | john.smith@techu.local          |
| Learner      | alice.williams@acme.local      | alice.williams@techu.local      |

### Seeded Data Summary

Per tenant, the seed script creates:

- **16 users**: 1 admin, 3 instructors, 12 learners
- **3 learner groups**: 2024 Cohort A, 2024 Cohort B, Engineering Team
- **4 folders**: Documents, Course Materials, Assessments, Archives
- **6 courses**: Python, Web Dev, Data Science, Digital Marketing, Project Management, UX Design
- **38 modules** with **150+ content items** (text, video, URL)
- **6 assessments** with **30 questions** (5 multiple-choice per assessment)
- **30-40 enrollments** with progress tracking
- **30+ assessment attempts** with scores
- **10-15 certificates** for completed courses
- **3 learning paths** with steps
- **2 AI model configs** (GPT-4, GPT-3.5)
- **5 AI prompt templates**
- **12 notifications** and **4 announcements**
- **120+ analytics events**

### Skills System

The platform includes a comprehensive skills and competencies system:

**Proficiency Levels** (in ascending order):

- `NOVICE` - Basic awareness
- `BEGINNER` - Foundational knowledge
- `INTERMEDIATE` - Working proficiency
- `ADVANCED` - Deep understanding
- `EXPERT` - Mastery level

**Generation Types** for personalized paths:

- `SKILL_BASED` - Build path to achieve target skill proficiency
- `GOAL_BASED` - Build path based on learning goals
- `REMEDIAL` - Build path to address gaps from failed/low-score assessments
- `RECOMMENDATION` - AI-recommended learning content

## Testing Workflows

### Authentication Flows

```bash
# Login with tenant user
curl -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email": "alice.williams@acme.local", "password": "password123"}'

# Response includes access & refresh tokens
# Use access token in subsequent requests:
# Authorization: Bearer <access_token>

# Refresh token
curl -X POST http://localhost:8000/api/auth/token/refresh/ \
  -H "Content-Type: application/json" \
  -d '{"refresh": "<refresh_token>"}'

# Get current user profile
curl http://localhost:8000/api/users/me/ \
  -H "Authorization: Bearer <access_token>"
```

### Admin Workflows

```bash
# List all tenants (superuser only)
curl http://localhost:8000/api/core/tenants/ \
  -H "Authorization: Bearer <admin_token>"

# List users in tenant
curl http://localhost:8000/api/users/ \
  -H "Authorization: Bearer <admin_token>"

# Create a new user
curl -X POST http://localhost:8000/api/users/ \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"email": "new.user@acme.local", "first_name": "New", "last_name": "User", "role": "learner", "password": "securepassword123"}'

# Update platform settings
curl -X PATCH http://localhost:8000/api/core/settings/ \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"features": {"ai_content_generation": true}}'
```

### Instructor Workflows

```bash
# List courses (instructor sees their own)
curl http://localhost:8000/api/courses/ \
  -H "Authorization: Bearer <instructor_token>"

# Create a new course
curl -X POST http://localhost:8000/api/courses/ \
  -H "Authorization: Bearer <instructor_token>" \
  -H "Content-Type: application/json" \
  -d '{"title": "Advanced Python", "description": "Deep dive into Python", "category": "programming", "difficulty_level": "advanced"}'

# Add a module to course
curl -X POST http://localhost:8000/api/courses/<course_id>/modules/ \
  -H "Authorization: Bearer <instructor_token>" \
  -H "Content-Type: application/json" \
  -d '{"title": "Decorators and Metaclasses", "description": "Advanced Python patterns", "order": 1}'

# Add content to module
curl -X POST http://localhost:8000/api/modules/<module_id>/content/ \
  -H "Authorization: Bearer <instructor_token>" \
  -H "Content-Type: application/json" \
  -d '{"title": "Understanding Decorators", "content_type": "text", "text_content": "# Decorators\n\nDecorators are...", "order": 1}'

# Create an assessment
curl -X POST http://localhost:8000/api/assessments/ \
  -H "Authorization: Bearer <instructor_token>" \
  -H "Content-Type: application/json" \
  -d '{"course": "<course_id>", "title": "Python Quiz", "assessment_type": "quiz", "pass_mark_percentage": 70}'

# Add questions to assessment
curl -X POST http://localhost:8000/api/assessments/<assessment_id>/questions/ \
  -H "Authorization: Bearer <instructor_token>" \
  -H "Content-Type: application/json" \
  -d '{"question_text": "What is a decorator?", "question_type": "multiple_choice", "points": 10, "type_specific_data": {"options": [{"id": "a", "text": "A function wrapper", "is_correct": true}, {"id": "b", "text": "A class", "is_correct": false}]}}'

# View enrollments in your courses
curl http://localhost:8000/api/enrollments/?course=<course_id> \
  -H "Authorization: Bearer <instructor_token>"

# View assessment attempts for grading
curl http://localhost:8000/api/assessments/<assessment_id>/attempts/ \
  -H "Authorization: Bearer <instructor_token>"
```

### Learner Workflows

```bash
# Browse available courses
curl http://localhost:8000/api/courses/?status=published \
  -H "Authorization: Bearer <learner_token>"

# Enroll in a course
curl -X POST http://localhost:8000/api/enrollments/ \
  -H "Authorization: Bearer <learner_token>" \
  -H "Content-Type: application/json" \
  -d '{"course": "<course_id>"}'

# View my enrollments
curl http://localhost:8000/api/enrollments/my/ \
  -H "Authorization: Bearer <learner_token>"

# Get course content (modules and items)
curl http://localhost:8000/api/courses/<course_id>/modules/ \
  -H "Authorization: Bearer <learner_token>"

# Mark content as viewed/completed
curl -X POST http://localhost:8000/api/progress/ \
  -H "Authorization: Bearer <learner_token>" \
  -H "Content-Type: application/json" \
  -d '{"content_item": "<content_id>", "status": "completed"}'

# Start an assessment attempt
curl -X POST http://localhost:8000/api/assessments/<assessment_id>/attempts/ \
  -H "Authorization: Bearer <learner_token>"

# Submit assessment answers
curl -X PATCH http://localhost:8000/api/attempts/<attempt_id>/ \
  -H "Authorization: Bearer <learner_token>" \
  -H "Content-Type: application/json" \
  -d '{"answers": {"<question_id>": {"selected_option_id": "a"}}, "status": "submitted"}'

# View my certificates
curl http://localhost:8000/api/certificates/my/ \
  -H "Authorization: Bearer <learner_token>"

# View my notifications
curl http://localhost:8000/api/notifications/ \
  -H "Authorization: Bearer <learner_token>"

# Mark notification as read
curl -X PATCH http://localhost:8000/api/notifications/<notification_id>/ \
  -H "Authorization: Bearer <learner_token>" \
  -H "Content-Type: application/json" \
  -d '{"is_read": true}'
```

### Learning Paths

```bash
# View available learning paths
curl http://localhost:8000/api/learning-paths/ \
  -H "Authorization: Bearer <learner_token>"

# View learning path details with steps
curl http://localhost:8000/api/learning-paths/<path_id>/ \
  -H "Authorization: Bearer <learner_token>"

# Start a learning path
curl -X POST http://localhost:8000/api/learning-paths/<path_id>/enroll/ \
  -H "Authorization: Bearer <learner_token>"

# View my learning path progress
curl http://localhost:8000/api/learning-paths/my-progress/ \
  -H "Authorization: Bearer <learner_token>"
```

### Analytics (Admin/Instructor)

```bash
# View analytics events
curl http://localhost:8000/api/analytics/events/ \
  -H "Authorization: Bearer <admin_token>"

# Get course analytics
curl http://localhost:8000/api/analytics/courses/<course_id>/stats/ \
  -H "Authorization: Bearer <instructor_token>"

# Get user activity
curl http://localhost:8000/api/analytics/users/<user_id>/activity/ \
  -H "Authorization: Bearer <admin_token>"
```

### Skills & Competencies

```bash
# List all skills (admin)
curl http://localhost:8000/api/admin/skills/ \
  -H "Authorization: Bearer <admin_token>"

# Create a new skill (admin)
curl -X POST http://localhost:8000/api/admin/skills/ \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Python Programming", "category": "programming", "description": "Core Python skills"}'

# Get learner's skill progress
curl http://localhost:8000/api/learner/skills/ \
  -H "Authorization: Bearer <learner_token>"

# Get skill gap analysis for a learner
curl http://localhost:8000/api/learner/skills/gap-analysis/ \
  -H "Authorization: Bearer <learner_token>"

# Map skills to a module (instructor)
curl -X POST http://localhost:8000/api/instructor/modules/<module_id>/skills/ \
  -H "Authorization: Bearer <instructor_token>" \
  -H "Content-Type: application/json" \
  -d '{"skill_id": "<skill_uuid>", "proficiency_level": "INTERMEDIATE"}'
```

### Personalized Learning Paths

```bash
# List learner's personalized paths
curl http://localhost:8000/api/learner/personalized-paths/ \
  -H "Authorization: Bearer <learner_token>"

# Preview a personalized learning path (before creating)
curl -X POST http://localhost:8000/api/learner/personalized-paths/preview/ \
  -H "Authorization: Bearer <learner_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "generation_type": "SKILL_BASED",
    "target_skills": ["<skill_uuid_1>", "<skill_uuid_2>"],
    "target_proficiency": "ADVANCED"
  }'

# Create a personalized path from preview
curl -X POST http://localhost:8000/api/learner/personalized-paths/ \
  -H "Authorization: Bearer <learner_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "My Python Learning Journey",
    "generation_type": "SKILL_BASED",
    "target_skills": ["<skill_uuid>"],
    "target_proficiency": "ADVANCED"
  }'

# Generate remedial path from assessment attempt
curl -X POST http://localhost:8000/api/learner/personalized-paths/ \
  -H "Authorization: Bearer <learner_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Remedial Path for Python Quiz",
    "generation_type": "REMEDIAL",
    "assessment_attempt_id": "<attempt_uuid>"
  }'

# Get personalized path details with steps
curl http://localhost:8000/api/learner/personalized-paths/<path_id>/ \
  -H "Authorization: Bearer <learner_token>"

# Start a personalized path (activate it)
curl -X POST http://localhost:8000/api/learner/personalized-paths/<path_id>/start/ \
  -H "Authorization: Bearer <learner_token>"

# Mark a step as completed
curl -X POST http://localhost:8000/api/learner/personalized-paths/<path_id>/steps/<step_id>/complete/ \
  -H "Authorization: Bearer <learner_token>"
```

### File Management

```bash
# List folders
curl http://localhost:8000/api/files/folders/ \
  -H "Authorization: Bearer <token>"

# Upload a file
curl -X POST http://localhost:8000/api/files/ \
  -H "Authorization: Bearer <token>" \
  -F "file=@/path/to/document.pdf" \
  -F "folder=<folder_id>"

# Get file download URL
curl http://localhost:8000/api/files/<file_id>/download/ \
  -H "Authorization: Bearer <token>"
```

### AI Engine

```bash
# List AI model configurations
curl http://localhost:8000/api/ai/models/ \
  -H "Authorization: Bearer <admin_token>"

# List prompt templates
curl http://localhost:8000/api/ai/templates/ \
  -H "Authorization: Bearer <admin_token>"

# Generate content (requires valid API key in config)
curl -X POST http://localhost:8000/api/ai/generate/ \
  -H "Authorization: Bearer <instructor_token>" \
  -H "Content-Type: application/json" \
  -d '{"template": "<template_id>", "variables": {"topic": "Python decorators", "level": "intermediate"}}'
```

## Related Documentation

- [Frontend README](https://github.com/Mont3ll/lms-frontend/README.md) - Frontend setup and development guide
