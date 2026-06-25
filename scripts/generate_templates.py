import os
import re

base_dir = r"c:\Users\OM\erp_system\erp_system\templates"

templates_to_create = [
    # Company
    {'path': 'company/settings.html', 'module': 'company', 'title': 'Company Settings', 'type': 'form'},
    {'path': 'company/branches/list.html', 'module': 'company', 'title': 'Branches', 'type': 'list'},
    {'path': 'company/branches/form.html', 'module': 'company', 'title': 'Branch Form', 'type': 'form'},
    {'path': 'company/departments/list.html', 'module': 'company', 'title': 'Departments', 'type': 'list'},
    {'path': 'company/users/list.html', 'module': 'company', 'title': 'Users & Roles', 'type': 'list'},
    {'path': 'company/fiscal_years/list.html', 'module': 'company', 'title': 'Fiscal Years', 'type': 'list'},
    {'path': 'company/currencies/list.html', 'module': 'company', 'title': 'Currencies', 'type': 'list'},

    # CRM
    {'path': 'crm/leads/list.html', 'module': 'crm', 'title': 'Leads', 'type': 'list'},
    {'path': 'crm/leads/form.html', 'module': 'crm', 'title': 'Lead Form', 'type': 'form'},
    {'path': 'crm/leads/detail.html', 'module': 'crm', 'title': 'Lead Details', 'type': 'detail'},
    {'path': 'crm/pipeline.html', 'module': 'crm', 'title': 'Pipeline', 'type': 'kanban'},
    {'path': 'crm/customers/list.html', 'module': 'crm', 'title': 'Customers', 'type': 'list'},
    {'path': 'crm/customers/form.html', 'module': 'crm', 'title': 'Customer Form', 'type': 'form'},
    {'path': 'crm/customers/detail.html', 'module': 'crm', 'title': 'Customer Details', 'type': 'detail'},

    # Sales
    {'path': 'sales/quotations/list.html', 'module': 'sales', 'title': 'Quotations', 'type': 'list'},
    {'path': 'sales/quotations/form.html', 'module': 'sales', 'title': 'Quotation Form', 'type': 'form'},
    {'path': 'sales/quotations/detail.html', 'module': 'sales', 'title': 'Quotation Details', 'type': 'detail'},
    {'path': 'sales/orders/list.html', 'module': 'sales', 'title': 'Sales Orders', 'type': 'list'},
    {'path': 'sales/orders/detail.html', 'module': 'sales', 'title': 'Sales Order Details', 'type': 'detail'},
    {'path': 'sales/invoices/list.html', 'module': 'sales', 'title': 'Invoices', 'type': 'list'},

    # Purchase
    {'path': 'purchase/vendors/list.html', 'module': 'purchase', 'title': 'Vendors', 'type': 'list'},
    {'path': 'purchase/vendors/form.html', 'module': 'purchase', 'title': 'Vendor Form', 'type': 'form'},
    {'path': 'purchase/vendors/detail.html', 'module': 'purchase', 'title': 'Vendor Details', 'type': 'detail'},
    {'path': 'purchase/requests/list.html', 'module': 'purchase', 'title': 'Purchase Requests', 'type': 'list'},
    {'path': 'purchase/requests/form.html', 'module': 'purchase', 'title': 'Purchase Request Form', 'type': 'form'},
    {'path': 'purchase/requests/detail.html', 'module': 'purchase', 'title': 'Purchase Request Details', 'type': 'detail'},
    {'path': 'purchase/orders/list.html', 'module': 'purchase', 'title': 'Purchase Orders', 'type': 'list'},
    {'path': 'purchase/orders/form.html', 'module': 'purchase', 'title': 'Purchase Order Form', 'type': 'form'},
    {'path': 'purchase/orders/detail.html', 'module': 'purchase', 'title': 'Purchase Order Details', 'type': 'detail'},

    # Inventory
    {'path': 'inventory/products/list.html', 'module': 'inventory', 'title': 'Products', 'type': 'list'},
    {'path': 'inventory/products/form.html', 'module': 'inventory', 'title': 'Product Form', 'type': 'form'},
    {'path': 'inventory/products/detail.html', 'module': 'inventory', 'title': 'Product Details', 'type': 'detail'},
    {'path': 'inventory/warehouses/list.html', 'module': 'inventory', 'title': 'Warehouses', 'type': 'list'},
    {'path': 'inventory/movements/list.html', 'module': 'inventory', 'title': 'Stock Movements', 'type': 'list'},
    {'path': 'inventory/movements/adjustment.html', 'module': 'inventory', 'title': 'Stock Adjustment', 'type': 'form'},
    {'path': 'inventory/reports/index.html', 'module': 'inventory', 'title': 'Inventory Reports', 'type': 'dashboard'},

    # HRMS
    {'path': 'hrms/employees/detail.html', 'module': 'hrms', 'title': 'Employee Details', 'type': 'detail'},
    {'path': 'hrms/employees/form.html', 'module': 'hrms', 'title': 'Employee Form', 'type': 'form'},
    {'path': 'hrms/attendance/index.html', 'module': 'hrms', 'title': 'Attendance', 'type': 'list'},
    {'path': 'hrms/leaves/list.html', 'module': 'hrms', 'title': 'Leaves', 'type': 'list'},
    {'path': 'hrms/leaves/form.html', 'module': 'hrms', 'title': 'Leave Form', 'type': 'form'},
    {'path': 'hrms/payroll/list.html', 'module': 'hrms', 'title': 'Payroll', 'type': 'list'},

    # Helpdesk
    {'path': 'helpdesk/tickets/list.html', 'module': 'helpdesk', 'title': 'Tickets', 'type': 'list'},
    {'path': 'helpdesk/tickets/form.html', 'module': 'helpdesk', 'title': 'Ticket Form', 'type': 'form'},
    {'path': 'helpdesk/tickets/detail.html', 'module': 'helpdesk', 'title': 'Ticket Details', 'type': 'detail'},
    {'path': 'helpdesk/kb/list.html', 'module': 'helpdesk', 'title': 'Knowledge Base', 'type': 'list'},
    {'path': 'helpdesk/kb/form.html', 'module': 'helpdesk', 'title': 'KB Article Form', 'type': 'form'},
    {'path': 'helpdesk/kb/detail.html', 'module': 'helpdesk', 'title': 'KB Article Details', 'type': 'detail'},

    # Documents
    {'path': 'documents/list.html', 'module': 'documents', 'title': 'Documents', 'type': 'list'},
    {'path': 'documents/form.html', 'module': 'documents', 'title': 'Document Form', 'type': 'form'},
    {'path': 'documents/detail.html', 'module': 'documents', 'title': 'Document Details', 'type': 'detail'},
    
    # Notifications
    {'path': 'notifications/list.html', 'module': 'notifications', 'title': 'Notifications', 'type': 'list'},

    # Accounting
    {'path': 'accounting/dashboard/index.html', 'module': 'accounting', 'title': 'Accounting Dashboard', 'type': 'dashboard'},
    {'path': 'accounting/journals/list.html', 'module': 'accounting', 'title': 'Journals', 'type': 'list'},
    {'path': 'accounting/journals/form.html', 'module': 'accounting', 'title': 'Journal Entry', 'type': 'form'},
    {'path': 'accounting/journals/detail.html', 'module': 'accounting', 'title': 'Journal Details', 'type': 'detail'},
    {'path': 'accounting/ledgers/list.html', 'module': 'accounting', 'title': 'General Ledger', 'type': 'list'},
    {'path': 'accounting/reports/trial_balance.html', 'module': 'accounting', 'title': 'Trial Balance', 'type': 'list'},
    {'path': 'accounting/reports/balance_sheet.html', 'module': 'accounting', 'title': 'Balance Sheet', 'type': 'list'},
    {'path': 'accounting/reports/profit_and_loss.html', 'module': 'accounting', 'title': 'Profit & Loss', 'type': 'list'},
    {'path': 'accounting/taxes/list.html', 'module': 'accounting', 'title': 'Taxes', 'type': 'list'},
    {'path': 'accounting/bank_accounts.html', 'module': 'accounting', 'title': 'Bank Accounts', 'type': 'list'},
    {'path': 'accounting/chart_of_accounts.html', 'module': 'accounting', 'title': 'Chart of Accounts', 'type': 'list'},

    # Projects
    {'path': 'projects/list.html', 'module': 'projects', 'title': 'Projects', 'type': 'list'},
    {'path': 'projects/form.html', 'module': 'projects', 'title': 'Project Form', 'type': 'form'},
    {'path': 'projects/detail.html', 'module': 'projects', 'title': 'Project Details', 'type': 'detail'},
    {'path': 'projects/tasks/form.html', 'module': 'projects', 'title': 'Task Form', 'type': 'form'},
    {'path': 'projects/tasks/detail.html', 'module': 'projects', 'title': 'Task Details', 'type': 'detail'},
    {'path': 'projects/kanban.html', 'module': 'projects', 'title': 'Project Kanban', 'type': 'kanban'},
    {'path': 'projects/timesheets/list.html', 'module': 'projects', 'title': 'Timesheets', 'type': 'list'},
]

def get_base_html(module, title, ptype):
    content = f"""{{% extends "base.html" %}}
{{% load static humanize %}}

{{% block title %}}{title} | {module.capitalize()}{{% endblock %}}
{{% block nav_{module} %}}active{{% endblock %}}

{{% block breadcrumb %}}
<li class="breadcrumb-item">
  <a href="{{% url 'dashboard:index' %}}"><i class="fas fa-home"></i></a>
</li>
<li class="breadcrumb-item">
  <a href="{{% url '{module}:index' %}}">{module.capitalize()}</a>
</li>
<li class="breadcrumb-item active">{title}</li>
{{% endblock %}}

{{% block content %}}
<div class="page-header">
  <div class="page-header-title">
    <h1>{title}</h1>
    <p class="text-muted">Manage {title.lower()}</p>
  </div>
  <div class="d-flex gap-2 flex-wrap">
    {{% if is_paginated or objects %}}
    <a href="#" class="btn btn-primary btn-sm">
      <i class="fas fa-plus me-1"></i>Add New
    </a>
    {{% endif %}}
  </div>
</div>

"""
    
    if ptype == 'list':
        content += """<div class="card">
  <div class="card-header d-flex align-items-center justify-content-between">
    <h6 class="mb-0 fw-700">List of Records</h6>
  </div>
  <div class="card-body p-0">
    <div class="table-responsive">
      <table class="table table-hover mb-0" data-datatable>
        <thead>
          <tr>
            <th>Name</th>
            <th>Status</th>
            <th>Created</th>
            <th style="width:120px">Actions</th>
          </tr>
        </thead>
        <tbody>
          {% for obj in object_list|default:objects %}
          <tr>
            <td>{{ obj }}</td>
            <td>
              <span class="badge badge-{{ obj.status|default:'draft' }}">{{ obj.get_status_display|default:'Draft' }}</span>
            </td>
            <td>{{ obj.created_at|date:"M j, Y" }}</td>
            <td>
              <div class="d-flex gap-1">
                <a href="#" class="btn btn-outline-primary btn-sm" title="View"><i class="fas fa-eye"></i></a>
                <a href="#" class="btn btn-warning btn-sm" title="Edit"><i class="fas fa-edit"></i></a>
                <form method="post" action="#" class="d-inline">
                  {% csrf_token %}
                  <button type="button" class="btn btn-danger btn-sm" data-confirm-delete="Archive {{ obj }}? This can be restored later." title="Archive">
                    <i class="fas fa-trash"></i>
                  </button>
                </form>
              </div>
            </td>
          </tr>
          {% empty %}
          <tr>
            <td colspan="4" class="text-center py-5">
              <i class="fas fa-folder-open fa-3x text-muted mb-3 d-block opacity-25"></i>
              <p class="text-muted mb-0">No records found</p>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>
"""
    elif ptype == 'form':
        content += """<div class="card">
  <div class="card-header">
    <h6 class="mb-0 fw-700">
      <i class="fas fa-edit me-2 text-primary"></i>Fill out form
    </h6>
  </div>
  <div class="card-body">
    {% if messages %}
      {% for m in messages %}
      <div class="alert alert-{{ m.tags }} alert-dismissible fade show">
        {{ m }}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
      </div>
      {% endfor %}
    {% endif %}

    <form method="post" enctype="multipart/form-data">
      {% csrf_token %}
      <div class="row g-3">
        {% for field in form %}
          <div class="col-md-6">
            <label class="form-label fw-semibold">{{ field.label }} {% if field.field.required %}<span class="text-danger">*</span>{% endif %}</label>
            {{ field }}
            {% if field.help_text %}<div class="form-text small">{{ field.help_text }}</div>{% endif %}
            {% for error in field.errors %}<div class="text-danger small mt-1">{{ error }}</div>{% endfor %}
          </div>
        {% endfor %}
      </div>
      <div class="mt-4 d-flex gap-2">
        <button type="submit" class="btn btn-primary">
          <i class="fas fa-save me-1"></i>Save
        </button>
        <a href="#" class="btn btn-outline-secondary">
          <i class="fas fa-times me-1"></i>Cancel
        </a>
      </div>
    </form>
  </div>
</div>
"""
    elif ptype == 'detail':
        content += """<!-- Header card -->
<div class="card mb-3">
  <div class="card-body">
    <div class="d-flex align-items-start justify-content-between flex-wrap gap-3">
      <div>
        <h4 class="fw-800 mb-1">{{ object.name|default:"Record Details" }}</h4>
        <div class="d-flex align-items-center gap-2 flex-wrap">
          <span class="badge badge-{{ object.status|default:'draft' }}">{{ object.get_status_display|default:'Draft' }}</span>
          <span class="text-muted small">
            <i class="fas fa-calendar me-1"></i>
            {{ object.created_at|date:"M j, Y" }}
          </span>
        </div>
      </div>
      <div class="d-flex gap-2 flex-wrap">
        <a href="#" class="btn btn-warning btn-sm"><i class="fas fa-edit me-1"></i>Edit</a>
        <form method="post" action="#" class="d-inline">
          {% csrf_token %}
          <button type="button" class="btn btn-danger btn-sm" data-confirm-delete="Archive this record?">
            <i class="fas fa-trash me-1"></i>Archive
          </button>
        </form>
      </div>
    </div>
  </div>
</div>

<div class="card">
  <div class="card-body">
    <p>Detailed information will be rendered here.</p>
  </div>
</div>
"""
    else:
        content += """<div class="card">
  <div class="card-body text-center py-5">
    <h4>Specialized view: {ptype}</h4>
    <p class="text-muted">This view requires custom frontend logic (e.g., Kanban, Chart.js, etc.)</p>
  </div>
</div>
"""

    content += """{% endblock %}

{% block extra_js %}
<script>
  // Page specific JS here
</script>
{% endblock %}
"""
    return content

count = 0
for t in templates_to_create:
    filepath = os.path.join(base_dir, os.path.normpath(t['path']))
    # Always create basic scaffold if file is missing, but if it exists, leave it alone to avoid breaking hand-written ones
    if not os.path.exists(filepath):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(get_base_html(t['module'], t['title'], t['type']))
        count += 1
        print(f"Created {t['path']}")

print(f"Total newly created files: {count}")
