#!/usr/bin/env python3
"""
Test script to verify course completion logic requires assessments to be passed.
This script creates a test course with content and assessments, then verifies
that certificates are only issued when all assessments are passed.
"""

import os
import sys
import django
from decimal import Decimal

# Add the backend directory to Python path
sys.path.insert(0, '/home/mel/Documents/Projects/lms/backend')

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lms_backend.settings.development')
django.setup()

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.core.models import Tenant
from apps.courses.models import Course, Module, ContentItem
from apps.assessments.models import Assessment, AssessmentAttempt
from apps.enrollments.models import Enrollment, LearnerProgress
from apps.enrollments.services import ProgressTrackerService, EnrollmentService

User = get_user_model()

def create_test_data():
    """Create test tenant, course, content, and assessments"""
    print("Creating test data...")
    
    # Create or get test tenant
    tenant, created = Tenant.objects.get_or_create(
        name="Test Tenant",
        defaults={
            'domain': 'test.example.com',
            'schema_name': 'test',
            'is_active': True
        }
    )
    print(f"Tenant: {tenant.name} ({'created' if created else 'existing'})")
    
    # Create test user
    user, created = User.objects.get_or_create(
        email="testlearner@example.com",
        defaults={
            'first_name': 'Test',
            'last_name': 'Learner',
            'tenant': tenant,
            'is_active': True
        }
    )
    if created:
        user.set_password('testpass123')
        user.save()
    print(f"User: {user.email} ({'created' if created else 'existing'})")
    
    # Create test course
    course, created = Course.objects.get_or_create(
        title="Test Course with Assessments",
        defaults={
            'description': 'A test course to verify completion logic',
            'tenant': tenant,
            'status': Course.Status.PUBLISHED
        }
    )
    print(f"Course: {course.title} ({'created' if created else 'existing'})")
    
    # Create module
    module, created = Module.objects.get_or_create(
        course=course,
        title="Test Module",
        defaults={
            'description': 'Test module',
            'order': 1
        }
    )
    print(f"Module: {module.title} ({'created' if created else 'existing'})")
    
    # Create content items
    content_items = []
    for i in range(2):
        content_item, created = ContentItem.objects.get_or_create(
            module=module,
            title=f"Test Content {i+1}",
            defaults={
                'content_type': ContentItem.ContentType.TEXT,
                'text_content': f'This is test content {i+1}',
                'order': i + 1,
                'is_published': True
            }
        )
        content_items.append(content_item)
        print(f"Content Item: {content_item.title} ({'created' if created else 'existing'})")
    
    # Create assessments
    assessments = []
    for i in range(2):
        assessment, created = Assessment.objects.get_or_create(
            course=course,
            title=f"Test Assessment {i+1}",
            defaults={
                'description': f'Test assessment {i+1}',
                'assessment_type': Assessment.AssessmentType.QUIZ,
                'pass_mark_percentage': 70,
                'is_published': True
            }
        )
        assessments.append(assessment)
        print(f"Assessment: {assessment.title} ({'created' if created else 'existing'})")
    
    return {
        'tenant': tenant,
        'user': user,
        'course': course,
        'module': module,
        'content_items': content_items,
        'assessments': assessments
    }

def test_completion_logic(test_data):
    """Test the course completion logic"""
    print("\n" + "="*50)
    print("TESTING COURSE COMPLETION LOGIC")
    print("="*50)
    
    user = test_data['user']
    course = test_data['course']
    content_items = test_data['content_items']
    assessments = test_data['assessments']
    
    # Enroll user in course
    enrollment, created = EnrollmentService.enroll_user(user, course)
    print(f"\nEnrollment status: {enrollment.status}")
    print(f"Progress: {enrollment.progress}%")
    
    # Test 1: Complete content but no assessments - should NOT complete
    print("\n--- Test 1: Content completed, no assessments ---")
    for content_item in content_items:
        progress, updated = ProgressTrackerService.update_content_progress(
            enrollment, content_item, LearnerProgress.Status.COMPLETED
        )
        print(f"Marked content '{content_item.title}' as completed")
    
    # Check completion
    ProgressTrackerService.check_and_update_course_completion(enrollment)
    enrollment.refresh_from_db()
    print(f"Course completion status: {enrollment.status}")
    print(f"Progress: {enrollment.progress}%")
    
    if enrollment.status == Enrollment.Status.COMPLETED:
        print("❌ FAIL: Course marked as completed without passing assessments!")
    else:
        print("✅ PASS: Course correctly NOT completed (assessments not passed)")
    
    # Test 2: Pass first assessment only - should NOT complete
    print("\n--- Test 2: Content + first assessment passed ---")
    attempt1, created = AssessmentAttempt.objects.get_or_create(
        assessment=assessments[0],
        user=user,
        defaults={
            'status': AssessmentAttempt.AttemptStatus.GRADED,
            'score': Decimal('80.00'),
            'max_score': 100,
            'is_passed': True,
            'end_time': timezone.now()
        }
    )
    print(f"Assessment '{assessments[0].title}' passed with score: {attempt1.score}")
    
    # Check completion
    ProgressTrackerService.check_and_update_course_completion(enrollment)
    enrollment.refresh_from_db()
    print(f"Course completion status: {enrollment.status}")
    print(f"Progress: {enrollment.progress}%")
    
    if enrollment.status == Enrollment.Status.COMPLETED:
        print("❌ FAIL: Course marked as completed with only one assessment passed!")
    else:
        print("✅ PASS: Course correctly NOT completed (second assessment not passed)")
    
    # Test 3: Pass second assessment - should complete
    print("\n--- Test 3: Content + both assessments passed ---")
    attempt2, created = AssessmentAttempt.objects.get_or_create(
        assessment=assessments[1],
        user=user,
        defaults={
            'status': AssessmentAttempt.AttemptStatus.GRADED,
            'score': Decimal('75.00'),
            'max_score': 100,
            'is_passed': True,
            'end_time': timezone.now()
        }
    )
    print(f"Assessment '{assessments[1].title}' passed with score: {attempt2.score}")
    
    # Check completion
    ProgressTrackerService.check_and_update_course_completion(enrollment)
    enrollment.refresh_from_db()
    print(f"Course completion status: {enrollment.status}")
    print(f"Progress: {enrollment.progress}%")
    
    if enrollment.status == Enrollment.Status.COMPLETED:
        print("✅ PASS: Course correctly completed with all content and assessments!")
        
        # Check if certificate was generated
        from apps.enrollments.models import Certificate
        certificate = Certificate.objects.filter(enrollment=enrollment).first()
        if certificate:
            print(f"✅ Certificate generated: {certificate.id}")
        else:
            print("❌ FAIL: No certificate generated!")
    else:
        print("❌ FAIL: Course should be completed but isn't!")
    
    # Test 4: Fail one assessment - should revert completion
    print("\n--- Test 4: Fail one assessment (should revert completion) ---")
    # Update second attempt to failed
    attempt2.score = Decimal('60.00')  # Below 70% pass mark
    attempt2.is_passed = False
    attempt2.save()
    print(f"Assessment '{assessments[1].title}' now failed with score: {attempt2.score}")
    
    # Check completion
    ProgressTrackerService.check_and_update_course_completion(enrollment)
    enrollment.refresh_from_db()
    print(f"Course completion status: {enrollment.status}")
    print(f"Progress: {enrollment.progress}%")
    
    if enrollment.status == Enrollment.Status.ACTIVE:
        print("✅ PASS: Course correctly reverted to ACTIVE when assessment failed")
    else:
        print("❌ FAIL: Course should have been reverted to ACTIVE!")

def main():
    """Main test function"""
    try:
        # Create test data
        test_data = create_test_data()
        
        # Run completion tests
        test_completion_logic(test_data)
        
        print("\n" + "="*50)
        print("TEST COMPLETE")
        print("="*50)
        
    except Exception as e:
        print(f"Error during testing: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
