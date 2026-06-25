from django.apps import AppConfig


class AdministrationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.administration'

    def ready(self):
        import apps.administration.signals  # noqa
