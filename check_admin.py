import os
import django
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.apps import apps
from django.contrib import admin

unregistered_models = []

for app_config in apps.get_app_configs():
    # Only care about our local apps
    if 'apps.' in app_config.name or app_config.name == 'core':
        for model in app_config.get_models():
            if not admin.site.is_registered(model):
                unregistered_models.append(f"{app_config.name}.{model.__name__}")

for m in unregistered_models:
    print(m)
