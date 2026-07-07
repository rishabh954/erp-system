from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)

def create_default_permissions(sender, **kwargs):
    from django.core.management import call_command
    try:
        call_command('setup_permissions')
    except Exception as e:
        logger.error(f"Failed to setup permissions during migration: {e}")

class AuthenticationConfig(AppConfig):
    name = 'apps.authentication'

    def ready(self):
        from django.db.models.signals import post_migrate
        post_migrate.connect(create_default_permissions, sender=self)
