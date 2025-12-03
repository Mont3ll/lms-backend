import logging
import uuid  # Import uuid if used directly (e.g., for type hints)
from decimal import Decimal, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.core.models import Tenant  # <<<--- IMPORT TENANT HERE
from apps.courses.models import ContentItem, Course

# Import necessary models from other apps
from apps.users.models import LearnerGroup, User

# Import models from this app
from .models import Certificate, Enrollment, GroupEnrollment, LearnerProgress

logger = logging.getLogger(__name__)


class EnrollmentError(Exception):
    pass


class EnrollmentService:
    """Service layer for managing enrollments."""

    @staticmethod
    @transaction.atomic
    def enroll_user(
        user: User, course: Course, status: str = Enrollment.Status.ACTIVE
    ) -> tuple[Enrollment, bool]:
        """Enrolls a single user in a course. Returns (enrollment, created)."""
        if not user or not course:
            raise ValueError("User and Course must be provided.")
        # Check tenant consistency
        # Allow superuser to enroll in any course? Check requirements.
        if not user.is_superuser and user.tenant != course.tenant:
            raise EnrollmentError(
                f"User {user.id} (tenant: {user.tenant_id}) and Course {course.id} (tenant: {course.tenant_id}) belong to different tenants."
            )

        enrollment, created = Enrollment.objects.get_or_create(
            user=user, course=course, defaults={"status": status}
        )
        if not created and enrollment.status != status:
            # Reactivate/update existing enrollment
            enrollment.status = status
            enrollment.completed_at = None  # Reset completion
            enrollment.expires_at = (
                None  # Reset expiry? Or keep original? Decide policy.
            )
            # Should we update enrolled_at? Probably not, keep original enrollment time.
            enrollment.save(
                update_fields=["status", "completed_at", "expires_at", "updated_at"]
            )
            logger.info(
                f"Reactivated/Updated enrollment for {user.email} in {course.title} with status {status}."
            )
            # Ensure created is False if we just updated
            created = False
        elif created:
            logger.info(
                f"Created enrollment for {user.email} in {course.title} with status {status}."
            )
            # Optionally trigger welcome notification
            NotificationService.notify_enrollment_creation(
                enrollment
            )  # Assumes NotificationService is defined/imported
        return enrollment, created

    @staticmethod
    @transaction.atomic
    def enroll_group(group: LearnerGroup, course: Course) -> GroupEnrollment:
        """Enrolls a learner group in a course and syncs individual members."""
        if not group or not course:
            raise ValueError("Group and Course must be provided.")
        if group.tenant != course.tenant:
            raise EnrollmentError(
                f"Group {group.id} (tenant: {group.tenant_id}) and Course {course.id} (tenant: {course.tenant_id}) belong to different tenants."
            )

        group_enrollment, created = GroupEnrollment.objects.get_or_create(
            group=group, course=course
        )

        if created:
            logger.info(
                f"Created group enrollment for '{group.name}' in '{course.title}'."
            )
            # Sync members immediately after creation
            EnrollmentService.sync_group_enrollment(group_enrollment)
        else:
            logger.info(
                f"Group enrollment for '{group.name}' in '{course.title}' already exists."
            )
            # Optionally re-sync members if needed (e.g., if members changed since last sync)
            EnrollmentService.sync_group_enrollment(
                group_enrollment
            )  # Sync ensures consistency

        return group_enrollment

    @staticmethod
    @transaction.atomic
    def sync_group_enrollment(group_enrollment: GroupEnrollment):
        """Creates/updates individual Enrollment records for members of an enrolled group."""
        group = group_enrollment.group
        course = group_enrollment.course
        logger.info(
            f"Syncing individual enrollments for group '{group.name}' in course '{course.title}'..."
        )

        current_member_ids = set(
            group.members.filter(status=User.Status.ACTIVE).values_list("id", flat=True)
        )  # Only sync active users
        # Get existing enrollments *linked* to these specific users for *this* course
        existing_enrollments = Enrollment.objects.filter(
            course=course,
            user_id__in=group.members.all().values_list(
                "id", flat=True
            ),  # Consider all potential past/present members
        ).select_related("user")

        existing_enrollment_map = {e.user_id: e for e in existing_enrollments}

        enrollments_to_create = []
        enrollments_to_update = []  # To reactivate if previously cancelled

        # Process current active members
        for member_id in current_member_ids:
            if member_id not in existing_enrollment_map:
                # User is in group but not enrolled in course -> Create enrollment
                # Fetch user instance to pass to Enrollment constructor
                try:
                    user = User.objects.get(pk=member_id)  # User object is needed
                    if user.tenant == course.tenant:  # Double check tenant consistency
                        enrollments_to_create.append(
                            Enrollment(
                                user=user,
                                course=course,
                                status=Enrollment.Status.ACTIVE,
                            )
                        )
                    else:
                        logger.warning(
                            f"Skipping sync enrollment for user {member_id} - tenant mismatch with course {course.id}"
                        )
                except User.DoesNotExist:
                    logger.warning(
                        f"User {member_id} from group {group.id} not found during sync."
                    )

            else:
                # User is in group and already has an enrollment record
                existing_enrollment = existing_enrollment_map[member_id]
                if existing_enrollment.status != Enrollment.Status.ACTIVE:
                    # If enrollment was previously cancelled/expired, reactivate it
                    existing_enrollment.status = Enrollment.Status.ACTIVE
                    existing_enrollment.completed_at = None
                    existing_enrollment.expires_at = None  # Reset expiry? Or keep?
                    enrollments_to_update.append(existing_enrollment)

        # Create new enrollments in bulk
        created_count = 0
        if enrollments_to_create:
            created_objs = Enrollment.objects.bulk_create(
                enrollments_to_create, ignore_conflicts=True
            )
            created_count = len(created_objs)
            logger.info(
                f"Created {created_count} new individual enrollments from group sync."
            )

        # Update existing enrollments in bulk
        updated_count = 0
        if enrollments_to_update:
            Enrollment.objects.bulk_update(
                enrollments_to_update,
                ["status", "completed_at", "expires_at", "updated_at"],
            )
            updated_count = len(enrollments_to_update)
            logger.info(
                f"Reactivated {updated_count} existing individual enrollments from group sync."
            )

        # Optional: Handle members removed from the group or inactive users
        # Find enrollments for users *not* in the current active member set
        inactive_or_removed_user_ids = (
            set(existing_enrollment_map.keys()) - current_member_ids
        )
        if inactive_or_removed_user_ids:
            # Decide policy: Cancel their individual enrollment? Keep it? Let's cancel active ones.
            cancelled_count = Enrollment.objects.filter(
                course=course,
                user_id__in=inactive_or_removed_user_ids,
                status=Enrollment.Status.ACTIVE,  # Only cancel currently active enrollments
            ).update(status=Enrollment.Status.CANCELLED, updated_at=timezone.now())
            logger.info(
                f"Cancelled {cancelled_count} individual enrollments due to user removal/inactivity in group."
            )

        return created_count + updated_count

    @staticmethod
    @transaction.atomic
    def bulk_enroll_users(
        user_ids: list[uuid.UUID],
        course_id: uuid.UUID,
        tenant: Tenant,  # Correctly typed now
    ) -> tuple[int, list[str]]:
        """Enrolls a list of users into a course, skipping existing enrollments."""
        created_count = 0
        errors = []
        try:
            course = Course.objects.get(pk=course_id, tenant=tenant)
        except Course.DoesNotExist:
            # Use tenant.id if tenant object might be None somehow, otherwise tenant.name
            tenant_identifier = tenant.name if tenant else str(tenant)
            errors.append(
                f"Course {course_id} not found in tenant {tenant_identifier}."
            )
            return created_count, errors

        # Filter users by ID and ensure they belong to the correct tenant
        users_to_enroll = User.objects.filter(
            id__in=user_ids, tenant=tenant, status=User.Status.ACTIVE
        )  # Only enroll active users?
        valid_user_ids = {u.id for u in users_to_enroll}
        invalid_user_ids_provided = set(user_ids) - valid_user_ids

        # Report users not found or not belonging to the tenant
        for invalid_id in invalid_user_ids_provided:
            errors.append(
                f"User {invalid_id} not found, inactive, or does not belong to tenant {tenant.name}."
            )

        if not valid_user_ids:
            return created_count, errors

        # Find users from the valid list who are already enrolled (in any status)
        existing_enrollments = Enrollment.objects.filter(
            course=course, user_id__in=valid_user_ids
        ).values_list("user_id", flat=True)
        existing_user_ids = set(existing_enrollments)

        # Determine users needing new enrollment
        new_enrollment_user_ids = valid_user_ids - existing_user_ids

        if new_enrollment_user_ids:
            users_for_new_enrollment = User.objects.filter(
                id__in=new_enrollment_user_ids
            )  # Fetch user objects
            enrollments_to_create = [
                Enrollment(user=user, course=course, status=Enrollment.Status.ACTIVE)
                for user in users_for_new_enrollment
            ]
            try:
                # Use ignore_conflicts=True just in case of race conditions, though check above helps
                created_objects = Enrollment.objects.bulk_create(
                    enrollments_to_create, ignore_conflicts=True
                )
                created_count = len(created_objects)
                logger.info(
                    f"Bulk enrolled {created_count} users into course {course.title}"
                )
            except IntegrityError as e:
                errors.append(f"Database error during bulk enrollment: {e}")
            except Exception as e:
                errors.append(f"Unexpected error during bulk enrollment: {e}")
                logger.error(f"Bulk enrollment error: {e}", exc_info=True)

        skipped_count = len(existing_user_ids)
        if skipped_count > 0:
            logger.info(
                f"Bulk enrollment: Skipped {skipped_count} already enrolled users."
            )

        return created_count, errors

    @staticmethod
    def has_active_enrollment(user: User, course: Course) -> bool:
        """
        Check if a user has an active enrollment in a course.
        
        Returns True if user has ACTIVE or COMPLETED enrollment status.
        This is used for access control checks (e.g., assessments).
        """
        if not user or not course:
            return False
        return Enrollment.objects.filter(
            user=user,
            course=course,
            status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
        ).exists()

    @staticmethod
    def get_enrollment(user: User, course: Course) -> Enrollment | None:
        """
        Get the enrollment record for a user in a course if it exists and is active.
        
        Returns the Enrollment object or None.
        """
        if not user or not course:
            return None
        return Enrollment.objects.filter(
            user=user,
            course=course,
            status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
        ).first()


class ProgressTrackerService:
    """Service for managing learner progress."""

    @staticmethod
    def update_content_progress(
        enrollment: Enrollment,
        content_item: ContentItem,
        status: str,
        details: dict = None,
    ):
        """Updates progress for a specific content item."""
        if not enrollment or not content_item:
            raise ValueError("Enrollment and ContentItem must be provided.")
        if content_item.module.course != enrollment.course:
            raise ValueError("ContentItem does not belong to the enrollment's course.")

        # Ensure enrollment is active before updating progress?
        if enrollment.status != Enrollment.Status.ACTIVE:
            logger.warning(
                f"Attempt to update progress for non-active enrollment E:{enrollment.id} C:{content_item.id}. Status: {enrollment.status}"
            )
            # Decide policy: Allow progress update? Or raise error? Let's allow for now.
            # raise ValueError("Cannot update progress for inactive enrollment.")
            pass

        progress, created = LearnerProgress.objects.get_or_create(
            enrollment=enrollment, content_item=content_item
        )

        updated = False
        status_changed = False

        # Handle status updates
        if (
            status == LearnerProgress.Status.COMPLETED
            and progress.status != LearnerProgress.Status.COMPLETED
        ):
            progress.status = LearnerProgress.Status.COMPLETED
            progress.completed_at = timezone.now()
            if not progress.started_at:  # Ensure started_at is set
                progress.started_at = progress.completed_at
            updated = True
            status_changed = True
        elif (
            status == LearnerProgress.Status.IN_PROGRESS
            and progress.status != LearnerProgress.Status.IN_PROGRESS
        ):
            progress.status = LearnerProgress.Status.IN_PROGRESS
            if not progress.started_at:  # Only set started_at if not already set
                progress.started_at = timezone.now()
            # Clear completed_at if moving from COMPLETED to IN_PROGRESS
            if progress.status == LearnerProgress.Status.COMPLETED:
                progress.completed_at = None
            updated = True
            status_changed = True
        elif (
            status == LearnerProgress.Status.NOT_STARTED
            and progress.status != LearnerProgress.Status.NOT_STARTED
        ):
            # Allow resetting progress for better UX (toggle functionality)
            progress.status = LearnerProgress.Status.NOT_STARTED
            progress.started_at = None
            progress.completed_at = None
            progress.progress_details = {}
            updated = True
            status_changed = True
            logger.info(
                f"Resetting progress status to NOT_STARTED for P:{progress.id}"
            )

        # Update details if provided
        if details:
            needs_details_update = False
            for key, value in details.items():
                if progress.progress_details.get(key) != value:
                    progress.progress_details[key] = value
                    needs_details_update = True
            if needs_details_update:
                updated = True

        # Save changes if any occurred
        if updated:
            update_fields = (
                [
                    "status",
                    "completed_at",
                    "started_at",
                    "progress_details",
                    "updated_at",
                ]
                if status_changed
                else ["progress_details", "updated_at"]
            )
            progress.save(update_fields=update_fields)

            # Always trigger progress update and completion check if something changed
            ProgressTrackerService.check_and_update_course_completion(
                progress.enrollment
            )

        logger.debug(
            f"Progress update for E:{enrollment.id} C:{content_item.id} - NewStatus:{progress.status}, Updated:{updated}"
        )
        return progress, updated

    @staticmethod
    def check_and_update_course_completion(enrollment: Enrollment):
        """
        Calculates progress, checks for completion (including assessments), and updates the enrollment record.
        Course is complete when:
        1. All published content items are completed AND
        2. All published assessments are passed (if any exist)
        """
        # 1. Calculate progress percentage
        progress_percentage = ProgressTrackerService.calculate_course_progress_percentage(enrollment)
        enrollment.progress = progress_percentage

        # 2. Check for completion
        course = enrollment.course
        course_items = ContentItem.objects.filter(module__course=course, is_published=True)
        total_items_count = course_items.count()

        # Get published assessments for this course
        course_assessments = course.assessments.filter(is_published=True)
        total_assessments_count = course_assessments.count()

        # Check if no content and no assessments
        if total_items_count == 0 and total_assessments_count == 0:
            if enrollment.status != Enrollment.Status.COMPLETED:
                logger.info(
                    f"Marking enrollment {enrollment.id} as completed (no published content or assessments)."
                )
                enrollment.mark_as_completed()
            else: # If already complete, just ensure progress is 100
                enrollment.progress = 100
                enrollment.save(update_fields=['progress', 'updated_at'])
            return True

        # Check content item completion
        completed_items_count = LearnerProgress.objects.filter(
            enrollment=enrollment,
            status=LearnerProgress.Status.COMPLETED,
            content_item__in=course_items,
        ).count()
        
        content_complete = (total_items_count == 0) or (completed_items_count >= total_items_count)

        # Check assessment completion
        assessments_complete = True
        passed_assessments_count = 0
        
        if total_assessments_count > 0:
            # Import here to avoid circular imports
            from apps.assessments.models import AssessmentAttempt
            
            # For each assessment, check if user has a passing attempt
            for assessment in course_assessments:
                passed_attempt = AssessmentAttempt.objects.filter(
                    assessment=assessment,
                    user=enrollment.user,
                    status__in=[AssessmentAttempt.AttemptStatus.SUBMITTED, AssessmentAttempt.AttemptStatus.GRADED],
                    is_passed=True
                ).exists()
                
                if passed_attempt:
                    passed_assessments_count += 1
                else:
                    assessments_complete = False
                    break

        is_complete = content_complete and assessments_complete

        logger.debug(
            f"Completion check E:{enrollment.id}: "
            f"Content: {completed_items_count}/{total_items_count} completed, "
            f"Assessments: {passed_assessments_count}/{total_assessments_count} passed. "
            f"IsComplete: {is_complete}"
        )

        if is_complete:
            if enrollment.status != Enrollment.Status.COMPLETED:
                logger.info(
                    f"Marking enrollment {enrollment.id} as completed based on content and assessment progress."
                )
                enrollment.mark_as_completed()  # This saves and sets progress to 100
                # Also trigger learning path sync since mark_as_completed may not always be called
                try:
                    from apps.learning_paths.services import LearningPathService
                    LearningPathService.sync_course_completion_with_learning_paths(enrollment)
                except ImportError:
                    logger.warning("Learning paths app not available for synchronization")
            else:
                # Already complete, but we save the progress in case it was somehow not 100
                enrollment.progress = 100
                enrollment.save(update_fields=["progress", "updated_at"])
            return True
        
        # Not complete
        if enrollment.status == Enrollment.Status.COMPLETED:
            # If content was added after completion, or assessments were added/modified, revert status
            completion_reason = []
            if not content_complete:
                completion_reason.append(f"content ({completed_items_count}/{total_items_count})")
            if not assessments_complete:
                completion_reason.append(f"assessments ({passed_assessments_count}/{total_assessments_count})")
            
            logger.warning(
                f"Enrollment {enrollment.id} is COMPLETED but completion check failed: {', '.join(completion_reason)}. Reverting to ACTIVE."
            )
            enrollment.status = Enrollment.Status.ACTIVE
            enrollment.completed_at = None
            enrollment.save(update_fields=["progress", "status", "completed_at", "updated_at"])
            # Sync learning path progress for the status change
            try:
                from apps.learning_paths.services import LearningPathService
                LearningPathService.sync_course_enrollment_with_learning_paths(enrollment)
            except ImportError:
                logger.warning("Learning paths app not available for synchronization")
        else:
            # Just save the new progress
            enrollment.save(update_fields=["progress", "updated_at"])
            
        return False

    @staticmethod
    def calculate_course_progress_percentage(enrollment: Enrollment) -> int:
        """Calculates the percentage of completed published content items for an enrollment."""
        course = enrollment.course
        # TODO: Filter by required items if applicable
        course_items = ContentItem.objects.filter(
            module__course=course, is_published=True
        )
        total_items_count = course_items.count()

        if total_items_count == 0:
            return 100 if enrollment.status == Enrollment.Status.COMPLETED else 0

        completed_items_count = LearnerProgress.objects.filter(
            enrollment=enrollment,
            status=LearnerProgress.Status.COMPLETED,
            content_item__in=course_items,  # Count only relevant items
        ).count()

        percentage = (Decimal(completed_items_count) / Decimal(total_items_count)) * 100
        return int(percentage.quantize(Decimal("1."), rounding=ROUND_HALF_UP))


# Avoid circular imports by potentially having NotificationService defined elsewhere
# or using Django signals for looser coupling. For simplicity, keeping stub here.
class CertificateService:
    """Service for managing certificates."""

    @staticmethod
    def generate_certificate_for_enrollment(
        enrollment: Enrollment,
    ) -> Certificate | None:
        """Generates and saves a certificate record for a completed enrollment if one doesn't exist."""
        if enrollment.status != Enrollment.Status.COMPLETED:
            logger.warning(
                f"Cannot generate certificate for non-completed enrollment {enrollment.id}"
            )
            return None

        certificate, created = Certificate.objects.get_or_create(
            enrollment=enrollment,
            defaults={
                "user": enrollment.user,
                "course": enrollment.course,
                "status": Certificate.Status.ISSUED,
                "issued_at": enrollment.completed_at or timezone.now(),
                "description": f"Certificate of completion for {enrollment.course.title}",
            },
        )

        if created:
            logger.info(
                f"Certificate {certificate.id} created for user {enrollment.user.id}, course {enrollment.course.id}"
            )
            # Generate PDF file
            try:
                from .certificate_service import CertificateService as PDFService
                PDFService.generate_certificate_pdf(certificate)
                logger.info(f"PDF generated for certificate {certificate.id}")
            except Exception as e:
                logger.error(f"Error generating PDF for certificate {certificate.id}: {e}")
            
            # Trigger notification
            NotificationService.notify_certificate_issued(certificate)
        else:
            logger.info(
                f"Certificate {certificate.id} already exists for enrollment {enrollment.id}"
            )
            # Generate PDF if it doesn't exist
            if not certificate.file_url:
                try:
                    from .certificate_service import CertificateService as PDFService
                    PDFService.generate_certificate_pdf(certificate)
                    logger.info(f"PDF generated for existing certificate {certificate.id}")
                except Exception as e:
                    logger.error(f"Error generating PDF for existing certificate {certificate.id}: {e}")

        return certificate

    @staticmethod
    def verify_certificate(verification_code: uuid.UUID) -> Certificate | None:
        """Finds a certificate by its verification code."""
        try:
            return Certificate.objects.select_related("user", "course").get(
                verification_code=verification_code
            )
        except Certificate.DoesNotExist:
            return None


class NotificationService:
    """Service for triggering enrollment-related notifications using the notifications app."""

    @staticmethod
    def notify_enrollment_creation(enrollment: Enrollment):
        """Send notification when a user is enrolled in a course."""
        try:
            from apps.notifications.services import NotificationService as ActualNotificationService
            from apps.notifications.models import NotificationType
            
            context = {
                'user_name': enrollment.user.first_name or enrollment.user.email,
                'course_name': enrollment.course.title
            }
            content = ActualNotificationService.generate_content_for_type(
                NotificationType.COURSE_ENROLLMENT, context
            )
            ActualNotificationService.create_notification(
                user=enrollment.user,
                notification_type=NotificationType.COURSE_ENROLLMENT,
                subject=content['subject'],
                message=content['message'],
                action_url=f"/learner/courses/{enrollment.course.slug}"
            )
            logger.info(f"Sent enrollment notification for user {enrollment.user.id} in course {enrollment.course.id}")
        except Exception as e:
            logger.error(f"Failed to send enrollment notification E:{enrollment.id}: {e}", exc_info=True)

    @staticmethod
    def notify_course_completion(enrollment: Enrollment):
        """Send notification when a user completes a course."""
        try:
            from apps.notifications.services import NotificationService as ActualNotificationService
            from apps.notifications.models import NotificationType
            
            context = {
                'user_name': enrollment.user.first_name or enrollment.user.email,
                'course_name': enrollment.course.title
            }
            content = ActualNotificationService.generate_content_for_type(
                NotificationType.COURSE_COMPLETION, context
            )
            ActualNotificationService.create_notification(
                user=enrollment.user,
                notification_type=NotificationType.COURSE_COMPLETION,
                subject=content['subject'],
                message=content['message'],
                action_url=f"/learner/courses/{enrollment.course.slug}"
            )
            logger.info(f"Sent course completion notification for user {enrollment.user.id} in course {enrollment.course.id}")
        except Exception as e:
            logger.error(f"Failed to send course completion notification E:{enrollment.id}: {e}", exc_info=True)

    @staticmethod
    def notify_certificate_issued(certificate: Certificate):
        """Send notification when a certificate is issued to a user."""
        try:
            from apps.notifications.services import NotificationService as ActualNotificationService
            from apps.notifications.models import NotificationType
            
            context = {
                'user_name': certificate.user.first_name or certificate.user.email,
                'course_name': certificate.course.title
            }
            content = ActualNotificationService.generate_content_for_type(
                NotificationType.CERTIFICATE_ISSUED, context
            )
            # Build verification URL if available
            action_url = None
            if certificate.verification_code:
                action_url = f"/certificates/verify/{certificate.verification_code}"
            
            ActualNotificationService.create_notification(
                user=certificate.user,
                notification_type=NotificationType.CERTIFICATE_ISSUED,
                subject=content['subject'],
                message=content['message'],
                action_url=action_url
            )
            logger.info(f"Sent certificate issued notification for user {certificate.user.id} in course {certificate.course.id}")
        except Exception as e:
            logger.error(f"Failed to send certificate notification C:{certificate.id}: {e}", exc_info=True)
