import re

with open('templates/base.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Modules mapping
modules = {
    'crm': 'CRM',
    'sales': 'Sales',
    'purchase': 'Purchase',
    'inventory': 'Inventory',
    'manufacturing': 'Manufacturing',
    'hrms': 'HRMS',
    'projects': 'Projects',
    'helpdesk': 'Helpdesk',
    'assets': 'Assets',
    'pos': 'POS',
    'documents': 'Documents',
    'portals': 'Portals',
    'analytics': 'Analytics',
    'workflow': 'Workflow'
}

for mod, label in modules.items():
    # Find the nav item
    pattern = rf'(<li class="nav-item nav-has-children {{% block nav_{mod} %}}{{% endblock %}}">.*?</nav-children>\s*</ul>\s*</li>)'
    match = re.search(pattern, content, re.DOTALL)
    if match:
        original = match.group(1)
        replacement = f"{{% if '{mod}' in active_app_labels or request.user.is_superuser %}}\n" + original + "\n{% endif %}"
        content = content.replace(original, replacement)
        
    # Same for single items without children if they exist
    pattern_single = rf'(<li class="nav-item {{% block nav_{mod} %}}{{% endblock %}}">.*?<span class="nav-label">{label}</span>.*?</li>)'
    match_single = re.search(pattern_single, content, re.DOTALL)
    if match_single:
        original = match_single.group(1)
        replacement = f"{{% if '{mod}' in active_app_labels or request.user.is_superuser %}}\n" + original + "\n{% endif %}"
        content = content.replace(original, replacement)

with open('templates/base.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated base.html with active_app_labels conditions")
