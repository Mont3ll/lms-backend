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
