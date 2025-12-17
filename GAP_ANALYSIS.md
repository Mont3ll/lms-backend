# LMS Backend Gap Analysis

This document summarizes the implementation status of the backend services, identifies gaps, and prioritizes work to complete the system.

## Executive Summary

The LMS backend is largely functional with core features implemented. However, several placeholder services need completion, test coverage is minimal, and some TODO items remain in the codebase.

---

## 1. Service Implementation Status

### Fully Implemented Services

| App | Service | Lines | Status | Notes |
|-----|---------|-------|--------|-------|
| `enrollments` | EnrollmentService | ~200 | Complete | User/group enrollment, bulk operations |
| `enrollments` | ProgressTrackerService | ~150 | Complete | Content progress, course completion |
| `enrollments` | CertificateService | ~150 | Complete | PDF generation, verification |
| `enrollments` | NotificationService | ~50 | Complete | Triggers notifications on events |
| `assessments` | GradingService | ~279 | Complete | Auto-grading for all question types |
| `analytics` | AnalyticsService | ~800 | Complete | Event tracking, engagement metrics |
| `analytics` | ReportGeneratorService | ~400 | Complete | Multiple report types |
| `analytics` | DataProcessorService | ~200 | Complete | Daily aggregation |
| `analytics` | ExportService | ~100 | Complete | CSV/JSON export |
| `analytics` | ComprehensiveAnalyticsService | ~500 | Complete | Instructor dashboard |
| `core` | TenantService | ~100 | Complete | Hostname lookup with caching |
| `core` | LTIService | ~400 | Complete | Full LTI 1.3 implementation |
| `core` | SSOService | ~500 | Complete | SAML and OAuth providers |
| `learning_paths` | LearningPathService | ~229 | Complete | Course sync, progress tracking |
| `ai_engine` | ContentGeneratorService | ~150 | Complete | Job creation, Celery dispatch |
| `ai_engine` | AIAdapterFactory | ~50 | Complete | Dynamic adapter loading |
| `files` | StorageService | ~130 | Complete | Upload, URL generation, deletion |
| `notifications` | NotificationService | ~200 | Complete | Creation, preference handling |
| `notifications` | EmailService | ~45 | Complete | Django send_mail integration |
| `notifications` | InAppService | ~15 | Complete | DB-based delivery |

### Placeholder/Incomplete Services (Priority Order)

| App | Service | Priority | Effort | Description |
|-----|---------|----------|--------|-------------|
| `notifications` | SMSService | Medium | 2h | Twilio integration commented out |
| `notifications` | PushService | Medium | 4h | FCM integration not implemented |
| `files` | ScanningService | High | 4h | Virus scanning (ClamAV) placeholder |
| `files` | TransformationService | Medium | 8h | Image/doc transforms placeholder |
| `ai_engine` | PersonalizationService | Low | 16h+ | Content recommendation system |
| `ai_engine` | NLPProcessorService | Low | 16h+ | Text analysis, keyword extraction |
| `ai_engine` | EvaluationService | Low | 8h | Generated content quality scoring |

---

## 2. TODO Items in Codebase

| File | Line | Description | Priority |
|------|------|-------------|----------|
| `enrollments/services.py` | 541 | Filter by required items | Medium |
| `assessments/views.py` | 165 | Refine permission check | High |
| `courses/viewsets.py` | 364 | File linking logic | Medium |
| `courses/viewsets.py` | 391 | Assessment linking logic | Medium |
| `assessments/viewsets.py` | 49 | Enrollment check | High |
| `assessments/viewsets.py` | 64 | Permission check | High |
| `ai_engine/views.py` | 30 | Permission refinement | Medium |
| `ai_engine/views.py` | 41 | Permission refinement | Medium |
| `ai_engine/views.py` | 146 | Tenant feature flags | Low |

---

## 3. Test Coverage Analysis

### Current State

| App | Test Files | Test Classes | Coverage |
|-----|------------|--------------|----------|
| `core` | `test_lti_sso.py` | 8 classes | LTI/SSO only |
| `enrollments` | `__init__.py` only | 0 | None |
| `assessments` | `__init__.py` only | 0 | None |
| `courses` | `__init__.py` only | 0 | None |
| `analytics` | `__init__.py` only | 0 | None |
| `ai_engine` | `__init__.py` only | 0 | None |
| `files` | `__init__.py` only | 0 | None |
| `notifications` | `__init__.py` only | 0 | None |
| `learning_paths` | `__init__.py` only | 0 | None |
| `users` | `__init__.py` only | 0 | None |

### Recommended Test Priority

1. **Critical**: `enrollments` - Core business logic
2. **Critical**: `assessments` - Grading accuracy
3. **High**: `courses` - Content delivery
4. **High**: `analytics` - Data integrity
5. **Medium**: `notifications` - Delivery reliability
6. **Medium**: `files` - Upload/security
7. **Low**: `ai_engine` - Generation quality

---

## 4. Recommended Action Plan

### Phase 1: Security & Stability (Week 1)

1. **Implement File Scanning** (`files/services.py`)
   - Integrate ClamAV or cloud-based scanning API
   - Add Celery task for async scanning
   - Block infected files from being served

2. **Fix Assessment Permission TODOs**
   - `assessments/views.py:165` - Permission check
   - `assessments/viewsets.py:49,64` - Enrollment/permission checks

3. **Add Critical Tests**
   - `enrollments/tests/test_services.py` - Enrollment logic
   - `assessments/tests/test_grading.py` - Grading accuracy

### Phase 2: Feature Completion (Week 2)

4. **Implement SMS Notifications**
   - Uncomment and configure Twilio integration
   - Add phone number field to UserProfile if missing
   - Test with sandbox account

5. **Implement Push Notifications**
   - Set up Firebase Cloud Messaging
   - Create UserDevice model for token storage
   - Implement FCM send logic

6. **Complete File Transformations**
   - Image thumbnail generation (Pillow)
   - Document preview (optional, complex)

### Phase 3: Enhancement (Week 3+)

7. **Expand Test Coverage**
   - Target 80% coverage on critical paths
   - Add integration tests for API endpoints

8. **AI Services (If Required)**
   - PersonalizationService - Requires ML infrastructure
   - NLPProcessorService - Consider using existing AI adapters
   - EvaluationService - Define quality metrics first

---

## 5. Implementation Details

### 5.1 SMS Service (Twilio)

```python
# notifications/services.py - SMSService.send_sms_notification

def send_sms_notification(notification: Notification) -> bool:
    from twilio.rest import Client
    
    phone = getattr(getattr(notification.recipient, 'profile', None), 'phone_number', None)
    if not phone:
        return False
    
    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=notification.message[:160],
            from_=settings.TWILIO_FROM_NUMBER,
            to=phone
        )
        logger.info(f"SMS sent: {message.sid}")
        return True
    except Exception as e:
        logger.error(f"SMS failed: {e}")
        return False
```

### 5.2 Push Service (FCM)

```python
# notifications/services.py - PushService.send_push_notification

def send_push_notification(notification: Notification) -> bool:
    import firebase_admin
    from firebase_admin import messaging
    
    # Get device tokens from UserDevice model
    tokens = list(UserDevice.objects.filter(
        user=notification.recipient, 
        is_active=True
    ).values_list('fcm_token', flat=True))
    
    if not tokens:
        return False
    
    try:
        message = messaging.MulticastMessage(
            tokens=tokens,
            notification=messaging.Notification(
                title=notification.subject,
                body=notification.message[:200],
            ),
            data={'action_url': notification.action_url or ''}
        )
        response = messaging.send_multicast(message)
        logger.info(f"Push sent: {response.success_count} success, {response.failure_count} failed")
        return response.success_count > 0
    except Exception as e:
        logger.error(f"Push failed: {e}")
        return False
```

### 5.3 File Scanning (ClamAV)

```python
# files/services.py - ScanningService.scan_file

def scan_file(file_id: uuid.UUID):
    import clamd
    
    file_instance = File.objects.get(pk=file_id)
    
    try:
        cd = clamd.ClamdUnixSocket()  # or ClamdNetworkSocket('clamav', 3310)
        
        with file_instance.file.open('rb') as f:
            result = cd.instream(f)
        
        status, signature = result['stream']
        
        file_instance.scan_completed_at = timezone.now()
        if status == 'OK':
            file_instance.scan_result = 'CLEAN'
            file_instance.status = File.FileStatus.AVAILABLE
        else:
            file_instance.scan_result = 'INFECTED'
            file_instance.scan_details = signature
            file_instance.status = File.FileStatus.ERROR
            file_instance.error_message = f"Malware detected: {signature}"
        
        file_instance.save()
    except Exception as e:
        logger.error(f"Scan error: {e}")
        file_instance.scan_result = 'ERROR'
        file_instance.save()
```

---

## 6. Dependencies to Add

```toml
# pyproject.toml additions

[tool.poetry.dependencies]
# For SMS
twilio = "^8.0.0"

# For Push Notifications  
firebase-admin = "^6.0.0"

# For File Scanning
clamd = "^1.0.2"  # ClamAV client

# For Image Transformations
Pillow = "^10.0.0"

# For Testing
pytest-django = "^4.5.0"
pytest-cov = "^4.1.0"
factory-boy = "^3.3.0"
```

---

## 7. Environment Variables Needed

```bash
# SMS (Twilio)
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_FROM_NUMBER=+1234567890

# Push Notifications (Firebase)
GOOGLE_APPLICATION_CREDENTIALS=/path/to/firebase-credentials.json
# Or use FIREBASE_CREDENTIALS as JSON string

# File Scanning (ClamAV)
CLAMAV_HOST=clamav  # Docker service name
CLAMAV_PORT=3310
```

---

## 8. Quick Wins (Can Do Today)

1. [ ] Enable SMS globally in `_is_method_globally_enabled()` when Twilio configured
2. [ ] Enable Push globally when Firebase configured
3. [ ] Add missing `uuid` import in `notifications/services.py` (line 139 uses `uuid.UUID`)
4. [ ] Add `default_storage` import in `files/services.py` (used but not imported)
5. [ ] Create empty test files with basic structure for each app

---

*Generated: December 2024*
*Last Updated: Based on codebase analysis*
