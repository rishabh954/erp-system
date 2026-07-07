from django.contrib.auth.management.commands.createsuperuser import Command as BaseCommand
from django.core.management import CommandError

class Command(BaseCommand):
    help = 'Create a superuser, and ensures primary_company is handled gracefully by Dashboard.'

    def handle(self, *args, **options):
        super().handle(*args, **options)
        self.stdout.write(self.style.SUCCESS(
            "\nSuperuser created! Note: The superuser does not have a primary_company yet. "
            "When you log in, you will be automatically redirected to the Company Onboarding flow to create your first company."
        ))
