import re

path = "apps/sales/views.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Remove CompanyScopedMixin definition
content = re.sub(
    r"class CompanyScopedMixin\(PermissionRequiredMixin\):\n.*?def get_base_qs\(self, model\):\n.*?return model\.objects\.filter\(\n.*?company=self\.get_company\(\), is_deleted=False\n.*?\)\.select_related\(\)\n\n",
    "",
    content,
    flags=re.DOTALL
)

# 2. Add import from core.mixins
if "from core.mixins import CompanyMixin" not in content:
    content = content.replace("from django.", "from core.mixins import CompanyMixin\nfrom django.", 1)

# 3. Replace CompanyScopedMixin with CompanyMixin in class signatures
content = content.replace("CompanyScopedMixin,", "CompanyMixin,")

# 4. Replace self.get_company() with self.company()
content = content.replace("self.get_company()", "self.company()")

# 5. Replace self.get_base_qs(Model) with Model.objects.filter(company=self.company(), is_deleted=False).select_related()
content = re.sub(
    r"self\.get_base_qs\(([a-zA-Z0-9_]+)\)",
    r"\1.objects.filter(company=self.company(), is_deleted=False).select_related()",
    content
)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Updated apps/sales/views.py")
