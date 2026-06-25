import os
import re

template_dir = r"c:\Users\OM\erp_system\erp_system\templates"

# Regex to match the entire {% if messages %} block including its ending {% endif %}
# It handles any nesting inside the block by using non-greedy match.
pattern = re.compile(r'\{%\s*if\s+messages\s*%\}.*?\{%\s*endif\s*%\}', re.DOTALL)

for root, dirs, files in os.walk(template_dir):
    for file in files:
        if file.endswith('.html'):
            filepath = os.path.join(root, file)
            # skip the partial itself and base.html where we just added the include
            if filepath.endswith('messages.html') or filepath.endswith('base.html'):
                continue
            
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            new_content = pattern.sub('', content)
            
            if new_content != content:
                # If it's the login or register page, we replace the block with the include
                if 'login.html' in filepath or 'register.html' in filepath:
                    new_content = pattern.sub("{% include 'partials/messages.html' %}", content)
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                print(f"Cleaned up {filepath}")
