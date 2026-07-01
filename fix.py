import os
import re

for root, dirs, files in os.walk('apps/portals/templates/portals'):
    for f in files:
        if f.endswith('.html'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8') as file:
                content = file.read()
                
            new_content = re.sub(
                r'\{\{\s*(.*?\.currency\.symbol)\|default:[\'\"].*?default_currency\.symbol.*?[\'\"]\s*\}\}', 
                r'{% firstof \1 current_company.default_currency.symbol \'$\' %}', 
                content
            )
            
            if new_content != content:
                with open(path, 'w', encoding='utf-8') as file:
                    file.write(new_content)
                print(f'Fixed {path}')
