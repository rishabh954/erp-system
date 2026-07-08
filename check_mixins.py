import ast
import os
from pathlib import Path

def get_mixins(class_node):
    mixins = []
    for base in class_node.bases:
        if isinstance(base, ast.Name):
            mixins.append(base.id)
    return mixins

def check_views():
    base_dir = Path("apps")
    missing = []
    
    # Authorized base classes that imply LoginRequiredMixin
    authorized_mixins = {
        'LoginRequiredMixin', 'CompanyMixin', 'CompanyScopedMixin', 
        'BaseCreateView', 'BaseUpdateView', 'HRManagerOrAdminMixin', 
        'AdminRequiredMixin'
    }

    # Public views that don't need authentication
    public_views = {
        'LoginView', 'RegisterView', 'LogoutView', 'VerifyEmailView',
        'PasswordResetRequestView', 'PasswordResetConfirmView', 'TwoFactorVerifyView'
    }

    for path in base_dir.rglob("views.py"):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue
            
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if node.name in public_views:
                    continue
                
                # Check if it looks like a view
                if any(base.id in ('View', 'TemplateView', 'ListView', 'DetailView', 'CreateView', 'UpdateView') for base in node.bases if isinstance(base, ast.Name)):
                    bases = get_mixins(node)
                    if not any(base in authorized_mixins for base in bases):
                        missing.append(f"{path}: {node.name}")

    if missing:
        print("Views missing authentication/authorization mixins:")
        for m in missing:
            print(m)
    else:
        print("All views seem to be properly secured.")

if __name__ == "__main__":
    check_views()
