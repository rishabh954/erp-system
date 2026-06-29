import os
import glob

directory = 'templates/analytics/'
pattern = "url 'analytics:report_builder'"
replacement = "url 'analytics:builder'"

for filepath in glob.glob(os.path.join(directory, '*.html')):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if pattern in content:
        content = content.replace(pattern, replacement)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated {filepath}")
