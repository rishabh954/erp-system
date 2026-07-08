import os

templates_dir = r"c:\Users\OM\erp_system\erp_system\templates"

# 1. Replace -$0.00 with -{{ CURRENCY_SYMBOL }}0.00
# 2. Replace $0.00 with {{ CURRENCY_SYMBOL }}0.00
# 3. Replace $0 with {{ CURRENCY_SYMBOL }}0

count = 0
for root, dirs, files in os.walk(templates_dir):
    for file in files:
        if file.endswith('.html'):
            filepath = os.path.join(root, file)
            with open(filepath, encoding='utf-8') as f:
                content = f.read()

            new_content = content.replace('-$0.00', '-{{ CURRENCY_SYMBOL }}0.00')
            new_content = new_content.replace('$0.00', '{{ CURRENCY_SYMBOL }}0.00')
            new_content = new_content.replace('$0', '{{ CURRENCY_SYMBOL }}0')

            if new_content != content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                count += 1
                print(f"Updated {file}")

print(f"Total files updated for hardcoded zero values: {count}")
