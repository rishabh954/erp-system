import re

file_path = 'apps/pos/views.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add logging import at the top
if 'import logging' not in content:
    content = 'import logging\n' + content

if 'logger = logging.getLogger(__name__)' not in content:
    content = content.replace('class POSIndexView', 'logger = logging.getLogger(__name__)\n\n\nclass POSIndexView')

# 3. Fix POSIndexView inheritance
if 'PermissionRequiredMixin' not in content:
    content = content.replace('class POSIndexView(CompanyMixin, View):', 'from core.permissions import PermissionRequiredMixin\n\nclass POSIndexView(PermissionRequiredMixin, CompanyMixin, View):')
else:
    content = content.replace('class POSIndexView(CompanyMixin, View):', 'class POSIndexView(PermissionRequiredMixin, CompanyMixin, View):')

# 4. Fix POSCheckoutAPIView inheritance and permission
content = content.replace('class POSCheckoutAPIView(CompanyMixin, View):\n    required_permission = "pos.read"', 'class POSCheckoutAPIView(PermissionRequiredMixin, CompanyMixin, View):\n    required_permission = "pos.create"')

# 5. Fix traceback leak
search_pattern = r'            except Exception as e:\n                import traceback\n\n                return JsonResponse\(\n                    \{\n                        "status": "error",\n                        "message": str\(e\),\n                        "detail": traceback\.format_exc\(\),\n                    \},\n                    status=400,\n                \)'
replace_pattern = r'            except Exception as e:\n                logger.error(f"POS checkout failed: {str(e)}", exc_info=True)\n                return JsonResponse(\n                    {\n                        "status": "error",\n                        "message": "Transaction failed",\n                        "error": "An unexpected error occurred."\n                    },\n                    status=500,\n                )'

content = re.sub(search_pattern, replace_pattern, content)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed apps/pos/views.py')
