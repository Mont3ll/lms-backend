import csv
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import Tenant
from apps.courses.models import Course
from apps.enrollments.services import EnrollmentError, EnrollmentService
from apps.users.models import User


class Command(BaseCommand):
    help = "Bulk enroll users from a CSV file into a specified course."

    def add_arguments(self, parser):
        parser.add_argument(
            "course_id", type=str, help="UUID of the course to enroll users into."
        )
        parser.add_argument(
            "tenant_id",
            type=str,
            help="UUID of the tenant the course and users belong to.",
        )
        parser.add_argument(
            "csv_file",
            type=str,
            help='Path to the CSV file containing user emails (one per line, requires header like "email").',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        course_id_str = options["course_id"]
        tenant_id_str = options["tenant_id"]
        csv_file_path = options["csv_file"]

        try:
            course_id = uuid.UUID(course_id_str)
            tenant_id = uuid.UUID(tenant_id_str)
        except ValueError:
            raise CommandError("Invalid UUID format for course_id or tenant_id.")

        self.stdout.write(
            f"Attempting bulk enrollment for course {course_id} in tenant {tenant_id} using file {csv_file_path}..."
        )

        try:
            tenant = Tenant.objects.get(pk=tenant_id)
            course = Course.objects.get(pk=course_id, tenant=tenant)
        except Tenant.DoesNotExist:
            raise CommandError(f"Tenant with ID {tenant_id} not found.")
        except Course.DoesNotExist:
            raise CommandError(
                f"Course with ID {course_id} not found in tenant {tenant_id}."
            )

        user_emails_to_enroll = []
        try:
            with open(csv_file_path, mode="r", encoding="utf-8") as csvfile:
                reader = csv.DictReader(csvfile)
                if "email" not in reader.fieldnames:
                    raise CommandError("CSV file must contain an 'email' header.")
                for row in reader:
                    email = row.get("email", "").strip()
                    if email:
                        user_emails_to_enroll.append(email.lower())  # Normalize email
        except FileNotFoundError:
            raise CommandError(f"CSV file not found at path: {csv_file_path}")
        except Exception as e:
            raise CommandError(f"Error reading CSV file: {e}")

        if not user_emails_to_enroll:
            self.stdout.write(
                self.style.WARNING("No valid user emails found in the CSV file.")
            )
            return

        # Find user IDs corresponding to emails within the tenant
        users_in_tenant = User.objects.filter(
            email__in=user_emails_to_enroll, tenant=tenant
        ).values("id", "email")

        user_ids_to_enroll = []
        found_emails = set()
        for user_data in users_in_tenant:
            user_ids_to_enroll.append(user_data["id"])
            found_emails.add(user_data["email"])

        not_found_emails = set(user_emails_to_enroll) - found_emails
        if not_found_emails:
            self.stdout.write(
                self.style.WARNING(
                    f"Could not find users in tenant {tenant.name} for emails: {', '.join(not_found_emails)}"
                )
            )

        if not user_ids_to_enroll:
            self.stdout.write(
                self.style.WARNING("No valid users identified for enrollment.")
            )
            return

        self.stdout.write(
            f"Attempting to enroll {len(user_ids_to_enroll)} identified users..."
        )

        # Use the service for bulk enrollment
        try:
            created_count, errors = EnrollmentService.bulk_enroll_users(
                user_ids_to_enroll, course.id, tenant
            )
            if errors:
                for error in errors:
                    self.stdout.write(self.style.ERROR(error))
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully enrolled {created_count} new users. Process complete."
                )
            )
        except EnrollmentError as e:
            raise CommandError(f"Enrollment service error: {e}")
        except Exception as e:
            raise CommandError(f"An unexpected error occurred during enrollment: {e}")
