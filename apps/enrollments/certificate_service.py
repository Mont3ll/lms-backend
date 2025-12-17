import io
import os
from datetime import datetime
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from .models import Certificate


class CertificateService:
    """Service for generating and managing certificate PDFs."""

    # Modern color palette
    COLORS = {
        'primary': colors.HexColor('#1e3a5f'),      # Deep navy blue
        'secondary': colors.HexColor('#c9a227'),     # Gold accent
        'accent': colors.HexColor('#2563eb'),        # Bright blue
        'text_dark': colors.HexColor('#1f2937'),     # Dark gray
        'text_medium': colors.HexColor('#4b5563'),   # Medium gray
        'text_light': colors.HexColor('#6b7280'),    # Light gray
        'border': colors.HexColor('#d4af37'),        # Golden border
        'background': colors.HexColor('#fafafa'),    # Off-white background
    }

    @staticmethod
    def _draw_decorative_border(c, width, height):
        """Draw an elegant decorative border with corner ornaments."""
        margin = 25 * mm
        inner_margin = 30 * mm
        
        # Outer border - thick golden line
        c.setStrokeColor(CertificateService.COLORS['secondary'])
        c.setLineWidth(3)
        c.rect(margin, margin, width - 2 * margin, height - 2 * margin)
        
        # Inner border - thin navy line
        c.setStrokeColor(CertificateService.COLORS['primary'])
        c.setLineWidth(1)
        c.rect(inner_margin, inner_margin, width - 2 * inner_margin, height - 2 * inner_margin)
        
        # Corner decorative elements
        corner_size = 15 * mm
        c.setStrokeColor(CertificateService.COLORS['secondary'])
        c.setLineWidth(2)
        
        # Top-left corner
        c.line(margin, height - margin - corner_size, margin, height - margin)
        c.line(margin, height - margin, margin + corner_size, height - margin)
        
        # Top-right corner
        c.line(width - margin - corner_size, height - margin, width - margin, height - margin)
        c.line(width - margin, height - margin, width - margin, height - margin - corner_size)
        
        # Bottom-left corner
        c.line(margin, margin, margin + corner_size, margin)
        c.line(margin, margin, margin, margin + corner_size)
        
        # Bottom-right corner
        c.line(width - margin - corner_size, margin, width - margin, margin)
        c.line(width - margin, margin, width - margin, margin + corner_size)
        
        # Decorative line under title area
        line_y = height - 85 * mm
        line_width = 80 * mm
        center_x = width / 2
        
        c.setStrokeColor(CertificateService.COLORS['secondary'])
        c.setLineWidth(1.5)
        c.line(center_x - line_width, line_y, center_x + line_width, line_y)
        
        # Small diamond in the center of the line
        diamond_size = 4 * mm
        c.setFillColor(CertificateService.COLORS['secondary'])
        path = c.beginPath()
        path.moveTo(center_x, line_y + diamond_size)
        path.lineTo(center_x + diamond_size, line_y)
        path.lineTo(center_x, line_y - diamond_size)
        path.lineTo(center_x - diamond_size, line_y)
        path.close()
        c.drawPath(path, fill=1, stroke=0)

    @staticmethod
    def _draw_seal(c, x, y, radius):
        """Draw an official-looking seal/stamp."""
        # Outer circle
        c.setStrokeColor(CertificateService.COLORS['secondary'])
        c.setLineWidth(2)
        c.circle(x, y, radius, stroke=1, fill=0)
        
        # Inner circle
        c.setLineWidth(1)
        c.circle(x, y, radius - 5 * mm, stroke=1, fill=0)
        
        # Inner filled circle
        c.setFillColor(CertificateService.COLORS['secondary'])
        c.circle(x, y, radius - 10 * mm, stroke=0, fill=1)
        
        # Checkmark in center
        c.setStrokeColor(colors.white)
        c.setLineWidth(2)
        c.line(x - 4 * mm, y, x - 1 * mm, y - 3 * mm)
        c.line(x - 1 * mm, y - 3 * mm, x + 5 * mm, y + 4 * mm)

    @staticmethod
    def _draw_signature_line(c, x, y, width, label):
        """Draw a signature line with label."""
        c.setStrokeColor(CertificateService.COLORS['text_medium'])
        c.setLineWidth(0.5)
        c.line(x, y, x + width, y)
        
        c.setFillColor(CertificateService.COLORS['text_light'])
        c.setFont('Helvetica', 9)
        text_width = c.stringWidth(label, 'Helvetica', 9)
        c.drawString(x + (width - text_width) / 2, y - 12, label)

    @staticmethod
    def generate_certificate_pdf(certificate: Certificate) -> str:
        """
        Generate a modern, professionally designed PDF certificate.
        
        Args:
            certificate: Certificate instance
            
        Returns:
            str: URL to the generated PDF file
        """
        buffer = io.BytesIO()
        
        # Use landscape A4 for a more traditional certificate look
        page_width, page_height = landscape(A4)
        
        c = canvas.Canvas(buffer, pagesize=landscape(A4))
        
        # Draw background color
        c.setFillColor(CertificateService.COLORS['background'])
        c.rect(0, 0, page_width, page_height, fill=1, stroke=0)
        
        # Draw decorative border
        CertificateService._draw_decorative_border(c, page_width, page_height)
        
        # Certificate header - organization name
        org_name = certificate.course.tenant.name if certificate.course.tenant else 'Learning Management System'
        c.setFillColor(CertificateService.COLORS['primary'])
        c.setFont('Helvetica-Bold', 14)
        org_width = c.stringWidth(org_name, 'Helvetica-Bold', 14)
        c.drawString((page_width - org_width) / 2, page_height - 55 * mm, org_name)
        
        # Main title
        c.setFillColor(CertificateService.COLORS['primary'])
        c.setFont('Helvetica-Bold', 36)
        title = "CERTIFICATE"
        title_width = c.stringWidth(title, 'Helvetica-Bold', 36)
        c.drawString((page_width - title_width) / 2, page_height - 75 * mm, title)
        
        # Subtitle
        c.setFont('Helvetica', 16)
        c.setFillColor(CertificateService.COLORS['secondary'])
        subtitle = "OF COMPLETION"
        subtitle_width = c.stringWidth(subtitle, 'Helvetica', 16)
        c.drawString((page_width - subtitle_width) / 2, page_height - 83 * mm, subtitle)
        
        # Decorative element already drawn by _draw_decorative_border
        
        # "This is to certify that" text
        c.setFillColor(CertificateService.COLORS['text_medium'])
        c.setFont('Helvetica', 12)
        certify_text = "This is to certify that"
        certify_width = c.stringWidth(certify_text, 'Helvetica', 12)
        c.drawString((page_width - certify_width) / 2, page_height - 105 * mm, certify_text)
        
        # Student name - prominent display
        student_name = f"{certificate.user.first_name} {certificate.user.last_name}".strip()
        if not student_name:
            student_name = certificate.user.email
        
        c.setFillColor(CertificateService.COLORS['accent'])
        c.setFont('Helvetica-Bold', 28)
        name_width = c.stringWidth(student_name, 'Helvetica-Bold', 28)
        c.drawString((page_width - name_width) / 2, page_height - 122 * mm, student_name)
        
        # Decorative line under name
        line_y = page_height - 128 * mm
        name_line_width = max(name_width + 40, 150 * mm)
        c.setStrokeColor(CertificateService.COLORS['secondary'])
        c.setLineWidth(1)
        c.line((page_width - name_line_width) / 2, line_y, (page_width + name_line_width) / 2, line_y)
        
        # "has successfully completed" text
        c.setFillColor(CertificateService.COLORS['text_medium'])
        c.setFont('Helvetica', 12)
        completed_text = "has successfully completed the course"
        completed_width = c.stringWidth(completed_text, 'Helvetica', 12)
        c.drawString((page_width - completed_width) / 2, page_height - 142 * mm, completed_text)
        
        # Course title
        course_title = certificate.course.title
        c.setFillColor(CertificateService.COLORS['text_dark'])
        c.setFont('Helvetica-Bold', 20)
        course_width = c.stringWidth(course_title, 'Helvetica-Bold', 20)
        c.drawString((page_width - course_width) / 2, page_height - 158 * mm, course_title)
        
        # Bottom section with date, verification, and seal
        bottom_y = 45 * mm
        
        # Date section (left)
        issued_date = certificate.issued_at.strftime("%B %d, %Y")
        c.setFillColor(CertificateService.COLORS['text_light'])
        c.setFont('Helvetica', 10)
        date_label = "Date of Issue"
        c.drawString(80 * mm, bottom_y + 15, date_label)
        
        c.setFillColor(CertificateService.COLORS['text_dark'])
        c.setFont('Helvetica-Bold', 12)
        c.drawString(80 * mm, bottom_y, issued_date)
        
        # Signature line (center-left)
        CertificateService._draw_signature_line(c, 140 * mm, bottom_y + 8, 60 * mm, "Authorized Signature")
        
        # Seal (center-right)
        seal_x = page_width - 120 * mm
        CertificateService._draw_seal(c, seal_x, bottom_y + 10, 18 * mm)
        
        # Verification code section (right)
        c.setFillColor(CertificateService.COLORS['text_light'])
        c.setFont('Helvetica', 10)
        verify_label = "Verification Code"
        c.drawString(page_width - 80 * mm, bottom_y + 15, verify_label)
        
        c.setFillColor(CertificateService.COLORS['text_dark'])
        c.setFont('Helvetica-Bold', 11)
        verify_code = str(certificate.verification_code)[:8].upper()
        c.drawString(page_width - 80 * mm, bottom_y, verify_code)
        
        # Certificate ID at very bottom
        c.setFillColor(CertificateService.COLORS['text_light'])
        c.setFont('Helvetica', 8)
        cert_id = f"Certificate ID: {certificate.id}"
        cert_id_width = c.stringWidth(cert_id, 'Helvetica', 8)
        c.drawString((page_width - cert_id_width) / 2, 20 * mm, cert_id)
        
        # Save the PDF
        c.save()
        buffer.seek(0)
        
        # Save the PDF file
        filename = f"certificate_{certificate.id}_{certificate.verification_code}.pdf"
        file_path = f"certificates/{filename}"
        
        # Save to storage
        saved_path = default_storage.save(file_path, ContentFile(buffer.getvalue()))
        file_url = default_storage.url(saved_path)
        
        # Update certificate with file URL
        certificate.file_url = file_url
        certificate.save(update_fields=['file_url'])
        
        return file_url

    @staticmethod
    def generate_and_update_certificate(certificate: Certificate) -> str:
        """
        Generate a PDF for an existing certificate and update the file_url.
        
        Args:
            certificate: Certificate instance
            
        Returns:
            str: URL to the generated PDF file
        """
        return CertificateService.generate_certificate_pdf(certificate)

    @staticmethod
    def regenerate_all_certificates():
        """
        Regenerate PDFs for all certificates that don't have file_url set.
        """
        certificates_without_files = Certificate.objects.filter(file_url__isnull=True)
        
        for certificate in certificates_without_files:
            try:
                CertificateService.generate_certificate_pdf(certificate)
                print(f"Generated PDF for certificate {certificate.id}")
            except Exception as e:
                print(f"Error generating PDF for certificate {certificate.id}: {e}")
