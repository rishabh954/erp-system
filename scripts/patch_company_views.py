import re
import os

path = "apps/company/views.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

permissions = {
    "CompanySettingsView": "company.update",
    "SwitchCompanyView": "company.read",
    "BranchListView": "company.read",
    "BranchCreateView": "company.create",
    "DepartmentListView": "company.read",
    "DepartmentCreateView": "company.create",
    "UserManagementView": "company.manage_users",
    "InviteUserView": "company.manage_users",
    "UserUpdateView": "company.manage_users",
    "UserRemoveView": "company.manage_users",
    "FiscalYearListView": "company.read",
    "FiscalYearCreateView": "company.create",
    "CurrencyListView": "company.read",
    "CurrencyCreateView": "company.create",
    "CurrencyUpdateView": "company.update",
    "CurrencyDeleteView": "company.delete",
    "ExchangeRateCreateView": "company.create",
    "UomListView": "company.read",
    "UomCreateView": "company.create",
    "UomUpdateView": "company.update",
    "UomDeleteView": "company.delete",
    "TaxListView": "company.read",
    "TaxCreateView": "company.create",
    "TaxUpdateView": "company.update",
    "TaxDeleteView": "company.delete",
}

for class_name, perm in permissions.items():
    pattern = rf"(class {class_name}\([^)]+\):)\n"
    replacement = rf"\1\n    required_permission = \"{perm}\"\n"
    content = re.sub(pattern, replacement, content)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Updated apps/company/views.py")
