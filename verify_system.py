import os
import django
from django.conf import settings
from django.template.loader import get_template, TemplateDoesNotExist

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

import re

# 1. Find all `template_name` in views.py
print("=== CHECKING MISSING TEMPLATES FROM VIEWS ===")
missing_templates = []
apps_dir = os.path.join(settings.BASE_DIR, "apps")

pattern = re.compile(r"template_name\s*=\s*['\"]([^'\"]+)['\"]")

for root, dirs, files in os.walk(apps_dir):
    for file in files:
        if file.endswith('.py'):
            filepath = os.path.join(root, file)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                matches = pattern.findall(content)
                for tmpl in matches:
                    try:
                        get_template(tmpl)
                    except TemplateDoesNotExist:
                        missing_templates.append((tmpl, filepath))
                    except Exception as e:
                        if 'requires 2' in str(e):
                            print(f'ERROR parsing {tmpl}: {e}')
                        pass

if not missing_templates:
    print("All templates referenced in views exist.")
else:
    for tmpl, fp in missing_templates:
        print(f"MISSING: {tmpl} (referenced in {fp})")

# 2. Check for missing {% url %} definitions in templates
print("\n=== CHECKING MISSING URLS FROM TEMPLATES ===")
templates_dir = os.path.join(settings.BASE_DIR, "templates")
url_pattern = re.compile(r"\{%\s*url\s+['\"]([^'\"]+)['\"]")

from django.urls import resolve, reverse
from django.urls.exceptions import NoReverseMatch

missing_urls = []

for root, dirs, files in os.walk(templates_dir):
    for file in files:
        if file.endswith('.html'):
            filepath = os.path.join(root, file)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                matches = url_pattern.findall(content)
                for url_name in matches:
                    try:
                        # We just check if it can be resolved. Wait, if it takes args, reverse might fail.
                        # So we only catch NoReverseMatch if it says "not found".
                        # A better way is to check the URL registry, but reverse without args is a start.
                        # If it takes args, reverse will say "Reverse for '...' with no arguments not found."
                        # Which means it exists! We only care if it says "Reverse for '...' not found."
                        try:
                            reverse(url_name)
                        except NoReverseMatch as e:
                            if "with no arguments not found" not in str(e) and "with keyword arguments" not in str(e):
                                # Double check if it exists at all
                                missing_urls.append((url_name, filepath))
                    except Exception:
                        pass

if not missing_urls:
    print("All URLs referenced in templates seem to exist (or require args).")
else:
    for url, fp in set(missing_urls):
        print(f"MISSING URL: {url} (in {fp})")
