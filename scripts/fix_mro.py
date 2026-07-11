import os
import re

APPS_DIR = 'apps'

for root, dirs, files in os.walk(APPS_DIR):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8') as file:
                content = file.read()

            original = content
            
            # Find class definitions that include CompanyMixin and PermissionRequiredMixin or LoginRequiredMixin
            # We just do text replacements for common patterns
            
            # Replace "PermissionRequiredMixin, CompanyMixin" -> "CompanyMixin"
            content = content.replace("PermissionRequiredMixin, CompanyMixin", "CompanyMixin")
            # Replace "CompanyMixin, PermissionRequiredMixin" -> "CompanyMixin"
            content = content.replace("CompanyMixin, PermissionRequiredMixin", "CompanyMixin")
            
            # Replace "LoginRequiredMixin, CompanyMixin" -> "CompanyMixin"
            content = content.replace("LoginRequiredMixin, CompanyMixin", "CompanyMixin")
            # Replace "CompanyMixin, LoginRequiredMixin" -> "CompanyMixin"
            content = content.replace("CompanyMixin, LoginRequiredMixin", "CompanyMixin")

            if content != original:
                with open(path, 'w', encoding='utf-8') as file:
                    file.write(content)
                print(f"Cleaned up MRO in {path}")
