import os
import glob
import re

template_dir = 'templates'
files = glob.glob(os.path.join(template_dir, '**/*.html'), recursive=True)

table_count = 0
card_count = 0
form_count = 0

for file in files:
    with open(file, 'r', encoding='utf-8') as f:
        content = f.read()
        table_count += len(re.findall(r'<table', content))
        card_count += len(re.findall(r'<div class="card', content))
        form_count += len(re.findall(r'<form', content))

print(f"Tables: {table_count}")
print(f"Cards: {card_count}")
print(f"Forms: {form_count}")
