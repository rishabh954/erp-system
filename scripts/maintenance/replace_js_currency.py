import os

templates_dir = r"c:\Users\OM\erp_system\erp_system\templates"

count = 0
for root, dirs, files in os.walk(templates_dir):
    for file in files:
        if file.endswith('.html'):
            filepath = os.path.join(root, file)
            with open(filepath, encoding='utf-8') as f:
                content = f.read()

            # Replace JS concatenations
            new_content = content.replace("'$' +", "'{{ CURRENCY_SYMBOL }}' +")

            # Replace form default discount representation (sometimes '-\$0.00' is hardcoded)  # noqa: E501
            new_content = new_content.replace("'-$0.00'", "'-{{ CURRENCY_SYMBOL }}0.00'")  # noqa: E501

            # Additional JS checks (like `'$' + rowTotal.toFixed(2)`)
            new_content = new_content.replace("`$` +", "`{{ CURRENCY_SYMBOL }}` +")
            new_content = new_content.replace('"$"+', '"{{ CURRENCY_SYMBOL }}"+')

            if new_content != content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                count += 1
                print(f"Updated JS in {file}")

print(f"Total files updated for JS currency: {count}")
