import os
import re

APPS_DIR = 'apps'

# Pattern to find 'class CompanyMixin(...):' and its following lines
# We will just look for `class CompanyMixin(` and the lines inside it.
pattern = re.compile(
    r'class CompanyMixin\([^)]+\):\n(?:[ \t]+def company\(self\):\n[ \t]+return self\.request\.user\.primary_company\n)?',
    re.MULTILINE
)
# Same for the LoginRequiredMixin version if it exists
pattern_login = re.compile(
    r'class CompanyMixin\(LoginRequiredMixin\):\n(?:[ \t]+def company\(self\):\n[ \t]+return self\.request\.user\.primary_company\n)?',
    re.MULTILINE
)

pattern_generic = re.compile(
    r'class CompanyMixin\([^)]+\):\n(?:[ \t]+"""[^"]*"""\n)?(?:[ \t]+def company\(self\):\n[ \t]+return self\.request\.user\.primary_company\n)?',
    re.MULTILINE
)

# A more robust approach:
# We just replace any declaration of `class CompanyMixin(...):` and the following 2 lines if they define `def company(self):`

for root, dirs, files in os.walk(APPS_DIR):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8') as file:
                content = file.read()

            original = content
            
            # Simple regex to remove the class definition
            # This matches `class CompanyMixin(...):` and optionally the `def company` method.
            regex = r'class CompanyMixin\s*\([^)]*\):(?:\s*""".*?""")?\s*(?:def company\(self\):\s*return self\.request\.user\.primary_company\s*)?'
            
            if re.search(regex, content):
                content = re.sub(regex, '', content, flags=re.DOTALL)
                
                # Add the import at the top of the file if not already present
                if 'from core.mixins import CompanyMixin' not in content:
                    # Find a good place to put it: after the first block of imports
                    # For simplicity, we just put it after `from django...` or at the top
                    
                    if 'from core.' in content:
                        content = content.replace('from core.', 'from core.mixins import CompanyMixin\nfrom core.', 1)
                    elif 'from django.' in content:
                        content = content.replace('from django.', 'from core.mixins import CompanyMixin\nfrom django.', 1)
                    else:
                        content = 'from core.mixins import CompanyMixin\n' + content

                # Let's clean up multiple blank lines left behind
                content = re.sub(r'\n{4,}', '\n\n\n', content)

            if content != original:
                with open(path, 'w', encoding='utf-8') as file:
                    file.write(content)
                print(f"Patched {path}")

