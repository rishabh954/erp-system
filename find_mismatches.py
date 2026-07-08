import ast
import os


def check_file(path):
    with open(path, encoding='utf-8') as f:
        try:
            tree = ast.parse(f.read(), filename=path)
        except SyntaxError:
            return

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Check if it has required_permission = '*.read'
            permission = None
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and target.id == 'required_permission':  # noqa: E501
                            if isinstance(item.value, ast.Constant):
                                permission = item.value.value
                            elif isinstance(item.value, ast.Str): # python < 3.8
                                permission = item.value.s
            if permission and 'read' in permission:
                # Let's check its methods
                mutates = False
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name in ('post', 'put', 'patch', 'delete', 'create', 'update', 'destroy'):  # noqa: E501
                        mutates = True

                name_lower = node.name.lower()
                suspicious_name = any(x in name_lower for x in ['create', 'update', 'delete', 'checkout', 'submit', 'approve', 'reject', 'cancel', 'process', 'action'])  # noqa: E501

                # Exclude false positives like "interaction" which has "action", or "payroll" which has "pay" (wait, I removed pay from this list)  # noqa: E501
                if 'interaction' in name_lower:
                    suspicious_name = False

                if mutates or suspicious_name:
                    print(f"{path} -> {node.name} (Has mutation handlers or suspicious name, but permission is {permission})")  # noqa: E501

for root, _, files in os.walk('apps'):
    for file in files:
        if file.endswith('.py'):
            check_file(os.path.join(root, file))
