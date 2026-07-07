from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)

def create_default_permissions(sender, **kwargs):
    from django.core.management import call_command
    try:
        call_command('setup_permissions')
        call_command('seed_currencies')
    except Exception as e:
        logger.error(f"Failed to run post-migrate setups: {e}")

class AuthenticationConfig(AppConfig):
    name = 'apps.authentication'

    def ready(self):
        from django.db.models.signals import post_migrate
        post_migrate.connect(create_default_permissions, sender=self)
