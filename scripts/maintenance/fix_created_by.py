import os
import re

apps_dir = r"c:\Users\OM\erp_system\erp_system\apps"

# We want to remove lines that contain exactly `created_by=request.user,` or `created_by=request.user`
# Make sure to handle leading whitespace.
pattern = re.compile(r'^\s*created_by=request\.user,?\s*\n', re.MULTILINE)

count = 0
for root, dirs, files in os.walk(apps_dir):
    for file in files:
        if file == 'views.py':
            filepath = os.path.join(root, file)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            new_content = pattern.sub('', content)
            
            if new_content != content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                count += 1
                print(f"Fixed {filepath}")

print(f"Total files fixed: {count}")
