import os
import re

APPS = [
    "sales", "purchase", "crm", "inventory", "projects",
    "assets", "helpdesk", "documents", "notifications",
    "workflow", "dashboard", "manufacturing", "pos",
    "portals", "analytics", "ai"
]

def determine_action(class_name):
    class_name = class_name.lower()
    if "create" in class_name or "new" in class_name:
        return "create"
    elif "update" in class_name or "edit" in class_name:
        return "update"
    elif "delete" in class_name or "remove" in class_name:
        return "delete"
    elif any(kw in class_name for kw in ["approve", "reject", "process", "send", "convert", "generate", "record", "pay", "cancel", "confirm", "complete"]):  # noqa: E501
        return "approve"
    else:
        return "read" # detail, list, template, etc.

def process_file(filepath, app_name):
    if not os.path.exists(filepath):
        return

    with open(filepath, encoding='utf-8') as f:
        content = f.read()

    # Avoid double processing
    if "PermissionRequiredMixin" in content and "required_permission =" in content:
        # Check if it's already fully processed
        # We'll just continue and do our regex replacements carefully
        pass

    if "PermissionRequiredMixin" not in content:
        # Add import
        import_stmt = "from core.permissions import PermissionRequiredMixin\n"
        # Find where to put it
        if "from django" in content:
            content = content.replace("from django", import_stmt + "from django", 1)
        else:
            content = import_stmt + content

    # Replace base mixins
    content = content.replace("class CompanyScopedMixin(LoginRequiredMixin):", "class CompanyScopedMixin(PermissionRequiredMixin):")  # noqa: E501
    content = content.replace("class CompanyMixin(LoginRequiredMixin):", "class CompanyMixin(PermissionRequiredMixin):")  # noqa: E501

    lines = content.split('\n')
    new_lines = []

    inside_class = False  # noqa: F841

    for i, line in enumerate(lines):
        new_lines.append(line)

        match = re.match(r'^(\s*)class (\w+)(?:View|APIView|ViewSet|API|List|Detail)?\((.*?)\):', line)  # noqa: E501
        if match:
            indent = match.group(1)
            class_name = match.group(2)
            bases = match.group(3)  # noqa: F841

            # Skip mixins or forms
            if "Mixin" in class_name or "Form" in class_name or "Filter" in class_name or "Serializer" in class_name:  # noqa: E501
                continue

            # Check if next lines already have required_permission
            already_has_perm = False
            for j in range(i+1, min(i+5, len(lines))):
                if "required_permission" in lines[j] or "def " in lines[j] or "class " in lines[j]:  # noqa: E501
                    if "required_permission" in lines[j]:
                        already_has_perm = True
                    break

            if not already_has_perm:
                action = determine_action(class_name)
                req_perm = f'{app_name}.{action}'
                new_lines.append(f'{indent}    required_permission = "{req_perm}"')

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_lines))

def run():
    base_dir = r"c:\Users\OM\Documents\GitHub\erp-system\apps"
    for app in APPS:
        views_path = os.path.join(base_dir, app, "views.py")
        api_views_path = os.path.join(base_dir, app, "api", "views.py")
        process_file(views_path, app)
        process_file(api_views_path, app)
        print(f"Processed {app}")

if __name__ == "__main__":
    run()
