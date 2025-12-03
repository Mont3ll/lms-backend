# Stage 1: Build dependencies
FROM python:3.11-slim as builder

WORKDIR /app

# Install poetry
RUN pip install --upgrade pip && pip install poetry==1.6.1

# Copy only dependency definition files
COPY pyproject.toml poetry.lock ./

# Install dependencies, excluding development ones
# --no-root: Don't install the project itself yet
# --without dev: Exclude development dependencies
RUN poetry install --no-interaction --no-ansi --without dev --no-root

# Stage 2: Build the final application image
FROM python:3.11-slim

WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV DJANGO_SETTINGS_MODULE=lms_backend.settings.production # Default to production
ENV PORT=8000

# Install system dependencies if needed (e.g., for psycopg2)
# RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# Copy installed dependencies from the builder stage
COPY --from=builder /app/.venv /app/.venv

# Activate the virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Create a non-root user
RUN addgroup --system app && adduser --system --group app

# Copy the application code
COPY . .

# Set ownership to the app user
RUN chown -R app:app /app

# Switch to the non-root user
USER app

# Expose the port the app runs on
EXPOSE 8000

# Run database migrations and start the application server (adjust as needed)
# Using Gunicorn is common for production WSGI serving
# CMD ["sh", "-c", "python manage.py migrate && gunicorn lms_backend.wsgi:application --bind 0.0.0.0:$PORT"]
# For development/testing using runserver:
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
