import os
import re

templates_dir = r"c:\Users\OM\erp_system\erp_system\templates"

# 1. Replace ${{ with {{ CURRENCY_SYMBOL }}{{
# 2. Replace $ {{ with {{ CURRENCY_SYMBOL }} {{
pattern = re.compile(r'\$(\s*\{\{)')

count = 0
for root, dirs, files in os.walk(templates_dir):
    for file in files:
        if file.endswith('.html'):
            filepath = os.path.join(root, file)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            new_content = pattern.sub(r'{{ CURRENCY_SYMBOL }}\1', content)
            
            if new_content != content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                count += 1
                print(f"Updated {file}")

print(f"Total files updated: {count}")
