import io
import os
from datetime import datetime
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from .models import Certificate


class CertificateService:
    """Service for generating and managing certificate PDFs."""

    @staticmethod
    def generate_certificate_pdf(certificate: Certificate) -> str:
        """
        Generate a PDF certificate and return the file URL.
        
        Args:
            certificate: Certificate instance
            
        Returns:
            str: URL to the generated PDF file
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=28,
            textColor=colors.HexColor('#1f2937'),
            alignment=TA_CENTER,
            spaceAfter=30,
        )
        
        subtitle_style = ParagraphStyle(
            'CustomSubtitle',
            parent=styles['Heading2'],
            fontSize=18,
            textColor=colors.HexColor('#374151'),
            alignment=TA_CENTER,
            spaceAfter=20,
        )
        
        body_style = ParagraphStyle(
            'CustomBody',
            parent=styles['Normal'],
            fontSize=14,
            textColor=colors.HexColor('#4b5563'),
            alignment=TA_CENTER,
            spaceAfter=15,
        )
        
        name_style = ParagraphStyle(
            'CustomName',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#059669'),
            alignment=TA_CENTER,
            spaceAfter=20,
            fontName='Helvetica-Bold',
        )

        # Build the certificate content
        content = []
        
        # Header/Logo space (you can add an actual logo later)
        content.append(Spacer(1, 1 * inch))
        
        # Title
        content.append(Paragraph("CERTIFICATE OF COMPLETION", title_style))
        content.append(Spacer(1, 0.5 * inch))
        
        # Subtitle
        content.append(Paragraph("This is to certify that", subtitle_style))
        content.append(Spacer(1, 0.2 * inch))
        
        # Student name
        student_name = f"{certificate.user.first_name} {certificate.user.last_name}".strip()
        if not student_name:
            student_name = certificate.user.email
        content.append(Paragraph(student_name, name_style))
        content.append(Spacer(1, 0.3 * inch))
        
        # Course completion text
        content.append(Paragraph("has successfully completed the course", body_style))
        content.append(Spacer(1, 0.2 * inch))
        
        # Course title
        course_title_style = ParagraphStyle(
            'CourseTitle',
            parent=styles['Heading2'],
            fontSize=20,
            textColor=colors.HexColor('#1f2937'),
            alignment=TA_CENTER,
            spaceAfter=30,
            fontName='Helvetica-Bold',
        )
        content.append(Paragraph(certificate.course.title, course_title_style))
        content.append(Spacer(1, 0.5 * inch))
        
        # Date and verification info
        issued_date = certificate.issued_at.strftime("%B %d, %Y")
        
        # Create a table for the bottom info
        table_data = [
            ["Date of Completion:", "Verification Code:"],
            [issued_date, str(certificate.verification_code)[:8].upper()]
        ]
        
        table = Table(table_data, colWidths=[3*inch, 3*inch])
        table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, 1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#4b5563')),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ]))
        
        content.append(table)
        content.append(Spacer(1, 0.5 * inch))
        
        # Footer
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#6b7280'),
            alignment=TA_CENTER,
        )
        content.append(Paragraph(f"Issued by {certificate.course.tenant.name if certificate.course.tenant else 'Learning Management System'}", footer_style))
        
        # Build the PDF
        doc.build(content)
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
