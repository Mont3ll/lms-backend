"""Management command to regenerate all certificate PDFs with the new design."""

from django.core.management.base import BaseCommand
from apps.enrollments.models import Certificate
from apps.enrollments.certificate_service import CertificateService


class Command(BaseCommand):
    help = 'Regenerate all certificate PDFs with the current design'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Regenerate all certificates, not just those without files',
        )
        parser.add_argument(
            '--certificate-id',
            type=str,
            help='Regenerate a specific certificate by ID',
        )

    def handle(self, *args, **options):
        if options['certificate_id']:
            # Regenerate specific certificate
            try:
                certificate = Certificate.objects.get(id=options['certificate_id'])
                self.stdout.write(f"Regenerating certificate {certificate.id}...")
                url = CertificateService.generate_certificate_pdf(certificate)
                self.stdout.write(self.style.SUCCESS(f"Generated: {url}"))
            except Certificate.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Certificate {options['certificate_id']} not found"))
            return

        if options['all']:
            certificates = Certificate.objects.all()
            self.stdout.write(f"Regenerating ALL {certificates.count()} certificates...")
        else:
            certificates = Certificate.objects.filter(file_url__isnull=True) | Certificate.objects.filter(file_url='')
            self.stdout.write(f"Regenerating {certificates.count()} certificates without files...")

        success_count = 0
        error_count = 0

        for certificate in certificates:
            try:
                url = CertificateService.generate_certificate_pdf(certificate)
                self.stdout.write(self.style.SUCCESS(f"[OK] Certificate {certificate.id}: {url}"))
                success_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"[ERROR] Certificate {certificate.id}: {e}"))
                error_count += 1

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Successfully regenerated: {success_count}"))
        if error_count:
            self.stdout.write(self.style.ERROR(f"Errors: {error_count}"))
