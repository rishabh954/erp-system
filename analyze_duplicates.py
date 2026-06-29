import os
import ast
from collections import defaultdict
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.apps import apps

# Analyze Models for common fields
model_fields = defaultdict(list)
for model in apps.get_models():
    # Only our apps
    if model._meta.app_label in ['auth', 'admin', 'contenttypes', 'sessions', 'messages', 'staticfiles', 'otp_static', 'otp_totp', 'token_blacklist', 'django_celery_beat', 'django_celery_results']:
        continue
    
    fields = [f.name for f in model._meta.fields]
    for field in fields:
        model_fields[field].append(f"{model._meta.app_label}.{model.__name__}")

common_fields = {k: v for k, v in model_fields.items() if len(v) > 5}
print("=== COMMON MODEL FIELDS ===")
for field, models_list in sorted(common_fields.items(), key=lambda item: len(item[1]), reverse=True):
    print(f"{field}: {len(models_list)} models")

# Analyze AST for views
def analyze_views():
    view_classes = 0
    list_views = 0
    create_views = 0
    update_views = 0
    delete_views = 0
    
    for app_config in apps.get_app_configs():
        if app_config.label in ['auth', 'admin', 'contenttypes', 'sessions', 'otp_static', 'otp_totp']: continue
        views_path = os.path.join(app_config.path, 'views.py')
        if os.path.exists(views_path):
            with open(views_path, 'r', encoding='utf-8') as f:
                content = f.read()
                try:
                    tree = ast.parse(content)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef):
                            view_classes += 1
                            bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
                            if any('ListView' in b for b in bases): list_views += 1
                            if any('CreateView' in b for b in bases): create_views += 1
                            if any('UpdateView' in b for b in bases): update_views += 1
                            if any('DeleteView' in b for b in bases): delete_views += 1
                except SyntaxError:
                    pass
    
    print("\n=== VIEWS ANALYSIS ===")
    print(f"Total View Classes: {view_classes}")
    print(f"List Views: {list_views}")
    print(f"Create Views: {create_views}")
    print(f"Update Views: {update_views}")
    print(f"Delete Views: {delete_views}")

analyze_views()
