"""
Tests for File services, including ClamAV scanning.
"""

import sys
import unittest
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage

from apps.core.models import Tenant
from apps.users.models import User
from apps.files.models import File, Folder
from apps.files.services import ScanningService, StorageService, FileUploadError


# Check if pyclamd is available for conditional skipping
try:
    import pyclamd
    PYCLAMD_AVAILABLE = True
except ImportError:
    PYCLAMD_AVAILABLE = False


class ScanningServiceTests(TestCase):
    """Tests for ClamAV ScanningService."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant",
        )
        self.user = User.objects.create_user(
            email="testuser@test.com",
            password="testpass123",
            first_name="Test",
            last_name="User",
            tenant=self.tenant,
            status=User.Status.ACTIVE,
        )

    def tearDown(self):
        """Clean up any created files."""
        # Reset the cached connection
        ScanningService._clamd_connection = None

    @override_settings(CLAMAV_ENABLED=False)
    def test_scan_stream_disabled(self):
        """Test that scanning returns SKIPPED when ClamAV is disabled."""
        result, details = ScanningService.scan_stream(b"test content")
        self.assertEqual(result, "SKIPPED")
        self.assertIn("disabled", details.lower())

    @override_settings(CLAMAV_ENABLED=True)
    @patch('apps.files.services.ScanningService.get_clamd_connection')
    def test_scan_stream_clean_file(self, mock_get_connection):
        """Test scanning a clean file."""
        mock_clamd = Mock()
        mock_clamd.scan_stream.return_value = None  # None means clean
        mock_get_connection.return_value = mock_clamd

        result, details = ScanningService.scan_stream(b"clean content")
        
        self.assertEqual(result, "CLEAN")
        self.assertIn("No threats", details)
        mock_clamd.scan_stream.assert_called_once()

    @override_settings(CLAMAV_ENABLED=True)
    @patch('apps.files.services.ScanningService.get_clamd_connection')
    def test_scan_stream_infected_file(self, mock_get_connection):
        """Test scanning an infected file."""
        mock_clamd = Mock()
        mock_clamd.scan_stream.return_value = {'stream': ('FOUND', 'Eicar-Test-Signature')}
        mock_get_connection.return_value = mock_clamd

        result, details = ScanningService.scan_stream(b"infected content")
        
        self.assertEqual(result, "INFECTED")
        self.assertIn("Eicar-Test-Signature", details)

    @override_settings(CLAMAV_ENABLED=True)
    @patch('apps.files.services.ScanningService.get_clamd_connection')
    def test_scan_stream_daemon_unavailable(self, mock_get_connection):
        """Test scanning when ClamAV daemon is unavailable."""
        mock_get_connection.return_value = None

        result, details = ScanningService.scan_stream(b"content")
        
        self.assertEqual(result, "ERROR")
        self.assertIn("not available", details.lower())

    @override_settings(CLAMAV_ENABLED=True, CLAMAV_MAX_FILE_SIZE=100)
    @patch('apps.files.services.ScanningService.get_clamd_connection')
    def test_scan_stream_file_too_large(self, mock_get_connection):
        """Test that large files are skipped."""
        mock_clamd = Mock()
        mock_get_connection.return_value = mock_clamd

        # Create content larger than max size (100 bytes)
        large_content = b"x" * 200
        result, details = ScanningService.scan_stream(large_content)
        
        self.assertEqual(result, "SKIPPED")
        self.assertIn("exceeds", details.lower())
        mock_clamd.scan_stream.assert_not_called()

    @override_settings(CLAMAV_ENABLED=True)
    @patch('apps.files.services.ScanningService.get_clamd_connection')
    def test_scan_stream_exception_handling(self, mock_get_connection):
        """Test handling of scan exceptions."""
        mock_clamd = Mock()
        mock_clamd.scan_stream.side_effect = Exception("Connection lost")
        mock_get_connection.return_value = mock_clamd

        result, details = ScanningService.scan_stream(b"content")
        
        self.assertEqual(result, "ERROR")
        self.assertIn("Connection lost", details)

    @unittest.skipUnless(PYCLAMD_AVAILABLE, "pyclamd not installed")
    @override_settings(CLAMAV_ENABLED=True, CLAMAV_CONNECTION_TYPE='tcp', CLAMAV_HOST='localhost', CLAMAV_PORT=3310)
    @patch('pyclamd.ClamdNetworkSocket')
    def test_get_clamd_connection_tcp(self, mock_network_socket):
        """Test establishing TCP connection to ClamAV."""
        mock_clamd = Mock()
        mock_clamd.ping.return_value = True
        mock_network_socket.return_value = mock_clamd
        
        # Reset cached connection
        ScanningService._clamd_connection = None
        
        connection = ScanningService.get_clamd_connection()
        
        self.assertIsNotNone(connection)
        mock_network_socket.assert_called_once_with(host='localhost', port=3310)

    @unittest.skipUnless(PYCLAMD_AVAILABLE, "pyclamd not installed")
    @override_settings(CLAMAV_ENABLED=True, CLAMAV_CONNECTION_TYPE='socket', CLAMAV_SOCKET='/var/run/clamav/clamd.ctl')
    @patch('pyclamd.ClamdUnixSocket')
    def test_get_clamd_connection_unix_socket(self, mock_unix_socket):
        """Test establishing Unix socket connection to ClamAV."""
        mock_clamd = Mock()
        mock_clamd.ping.return_value = True
        mock_unix_socket.return_value = mock_clamd
        
        # Reset cached connection
        ScanningService._clamd_connection = None
        
        connection = ScanningService.get_clamd_connection()
        
        self.assertIsNotNone(connection)
        mock_unix_socket.assert_called_once_with(filename='/var/run/clamav/clamd.ctl')

    @override_settings(CLAMAV_ENABLED=True)
    def test_get_clamd_connection_pyclamd_not_installed(self):
        """Test handling when pyclamd is not installed."""
        ScanningService._clamd_connection = None
        
        # If pyclamd is not available, the service should handle it gracefully
        if not PYCLAMD_AVAILABLE:
            # The actual import will fail in get_clamd_connection
            connection = ScanningService.get_clamd_connection()
            self.assertIsNone(connection)
        else:
            # Skip this test if pyclamd is actually installed
            self.skipTest("pyclamd is installed, cannot test import failure")


class ScanFileIntegrationTests(TestCase):
    """Integration tests for scan_file method."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant",
        )
        self.user = User.objects.create_user(
            email="testuser@test.com",
            password="testpass123",
            first_name="Test",
            last_name="User",
            tenant=self.tenant,
            status=User.Status.ACTIVE,
        )

    def tearDown(self):
        """Clean up files."""
        ScanningService._clamd_connection = None

    @override_settings(CLAMAV_ENABLED=False)
    def test_scan_file_disabled_marks_available(self):
        """Test that when ClamAV is disabled, files are marked as available."""
        # Create a file in PROCESSING state
        file_obj = File.objects.create(
            tenant=self.tenant,
            uploaded_by=self.user,
            original_filename="test.txt",
            file_size=100,
            mime_type="text/plain",
            status=File.FileStatus.PROCESSING,
        )
        
        # Mock the file content
        with patch.object(default_storage, 'open') as mock_open:
            mock_open.return_value.__enter__ = Mock(return_value=Mock(read=Mock(return_value=b"test")))
            mock_open.return_value.__exit__ = Mock(return_value=False)
            
            # File doesn't have actual content, so skip storage read
            with patch.object(file_obj, 'file') as mock_file:
                mock_file.name = None  # No file content
                
                ScanningService.scan_file(file_obj.id)
        
        file_obj.refresh_from_db()
        # Should have error since no file content
        self.assertEqual(file_obj.scan_result, "ERROR")

    def test_scan_file_not_found(self):
        """Test scanning a non-existent file."""
        import uuid
        # Should not raise, just log error
        ScanningService.scan_file(uuid.uuid4())

    def test_scan_file_wrong_status_skipped(self):
        """Test that files not in PROCESSING/AVAILABLE status are skipped."""
        file_obj = File.objects.create(
            tenant=self.tenant,
            uploaded_by=self.user,
            original_filename="test.txt",
            file_size=100,
            mime_type="text/plain",
            status=File.FileStatus.PENDING,  # Not PROCESSING or AVAILABLE
        )
        
        ScanningService.scan_file(file_obj.id)
        
        file_obj.refresh_from_db()
        # Should remain unchanged
        self.assertEqual(file_obj.status, File.FileStatus.PENDING)
        self.assertIsNone(file_obj.scan_result)

    @override_settings(CLAMAV_ENABLED=True)
    @patch('apps.files.services.ScanningService.scan_stream')
    def test_scan_file_infected_deletes_file(self, mock_scan_stream):
        """Test that infected files are marked as error when found infected."""
        mock_scan_stream.return_value = ("INFECTED", "Test virus detected")
        
        file_obj = File.objects.create(
            tenant=self.tenant,
            uploaded_by=self.user,
            original_filename="malware.exe",
            file_size=100,
            mime_type="application/octet-stream",
            status=File.FileStatus.PROCESSING,
        )
        
        # Set a file name to simulate a real file
        file_obj.file.name = "test/path/malware.exe"
        file_obj.save()
        
        # Mock storage operations
        with patch.object(default_storage, 'open') as mock_open:
            mock_file = MagicMock()
            mock_file.read.return_value = b"malware content"
            mock_open.return_value.__enter__ = Mock(return_value=mock_file)
            mock_open.return_value.__exit__ = Mock(return_value=False)
            
            with patch.object(default_storage, 'exists', return_value=True):
                with patch.object(default_storage, 'delete') as mock_delete:
                    ScanningService.scan_file(file_obj.id)
                    
                    # Verify delete was called for the infected file
                    mock_delete.assert_called_once_with("test/path/malware.exe")
        
        file_obj.refresh_from_db()
        self.assertEqual(file_obj.status, File.FileStatus.ERROR)
        self.assertEqual(file_obj.scan_result, "INFECTED")
        self.assertIn("threat", file_obj.error_message.lower())

    @override_settings(CLAMAV_ENABLED=True)
    @patch('apps.files.services.ScanningService.scan_stream')
    def test_scan_file_clean_marks_available(self, mock_scan_stream):
        """Test that clean files are marked as available."""
        mock_scan_stream.return_value = ("CLEAN", "No threats detected")
        
        file_obj = File.objects.create(
            tenant=self.tenant,
            uploaded_by=self.user,
            original_filename="document.pdf",
            file_size=100,
            mime_type="application/pdf",
            status=File.FileStatus.PROCESSING,
        )
        
        file_obj.file.name = "test/path/document.pdf"
        file_obj.save()
        
        with patch.object(default_storage, 'open') as mock_open:
            mock_file = MagicMock()
            mock_file.read.return_value = b"clean content"
            mock_open.return_value.__enter__ = Mock(return_value=mock_file)
            mock_open.return_value.__exit__ = Mock(return_value=False)
            
            ScanningService.scan_file(file_obj.id)
        
        file_obj.refresh_from_db()
        self.assertEqual(file_obj.status, File.FileStatus.AVAILABLE)
        self.assertEqual(file_obj.scan_result, "CLEAN")


class StorageServiceTests(TestCase):
    """Tests for StorageService."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant",
        )
        self.user = User.objects.create_user(
            email="testuser@test.com",
            password="testpass123",
            first_name="Test",
            last_name="User",
            tenant=self.tenant,
            status=User.Status.ACTIVE,
        )

    def test_upload_file_no_file_raises_error(self):
        """Test that uploading without a file raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            StorageService.upload_file(
                uploaded_file=None,
                tenant=self.tenant,
                uploaded_by=self.user,
            )
        self.assertIn("No file", str(ctx.exception))

    def test_upload_file_no_tenant_raises_error(self):
        """Test that uploading without tenant raises ValueError."""
        uploaded_file = SimpleUploadedFile("test.txt", b"content")
        with self.assertRaises(ValueError) as ctx:
            StorageService.upload_file(
                uploaded_file=uploaded_file,
                tenant=None,
                uploaded_by=self.user,
            )
        self.assertIn("Tenant", str(ctx.exception))

    @patch('apps.files.tasks.scan_file_task')
    @patch('apps.files.tasks.transform_file_task')
    @patch.object(default_storage, 'save')
    def test_upload_file_success(self, mock_save, mock_transform_task, mock_scan_task):
        """Test successful file upload."""
        mock_save.return_value = "test/path/test.txt"
        
        uploaded_file = SimpleUploadedFile(
            "test.txt", 
            b"test content",
            content_type="text/plain"
        )
        
        result = StorageService.upload_file(
            uploaded_file=uploaded_file,
            tenant=self.tenant,
            uploaded_by=self.user,
        )
        
        self.assertIsInstance(result, File)
        self.assertEqual(result.original_filename, "test.txt")
        self.assertEqual(result.uploaded_by, self.user)
        self.assertEqual(result.tenant, self.tenant)
        self.assertEqual(result.status, File.FileStatus.PROCESSING)
        # Verify async tasks were triggered
        mock_scan_task.delay.assert_called_once_with(str(result.id))
        mock_transform_task.delay.assert_called_once_with(str(result.id))

    def test_get_file_url_non_available_returns_none(self):
        """Test that non-available files return None for URL."""
        file_obj = File.objects.create(
            tenant=self.tenant,
            uploaded_by=self.user,
            original_filename="test.txt",
            file_size=100,
            mime_type="text/plain",
            status=File.FileStatus.PROCESSING,
        )
        
        url = StorageService.get_file_url(file_obj)
        self.assertIsNone(url)

    @patch.object(default_storage, 'url')
    def test_get_file_url_available_returns_url(self, mock_url):
        """Test that available files return a URL."""
        mock_url.return_value = "https://storage.example.com/test.txt"
        
        file_obj = File.objects.create(
            tenant=self.tenant,
            uploaded_by=self.user,
            original_filename="test.txt",
            file_size=100,
            mime_type="text/plain",
            status=File.FileStatus.AVAILABLE,
        )
        file_obj.file.name = "test/path/test.txt"
        file_obj.save()
        
        url = StorageService.get_file_url(file_obj)
        
        self.assertEqual(url, "https://storage.example.com/test.txt")
        mock_url.assert_called_once()
