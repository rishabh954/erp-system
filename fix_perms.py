import os
import re

fixes = [
    ('apps/assets/views.py', 'ScheduleMaintenanceView', 'assets.create'),
    ('apps/authentication/views.py', 'ChangePasswordView', 'authentication.update'),
    ('apps/authentication/views.py', 'RevokeSessionView', 'authentication.delete'),
    ('apps/authentication/views.py', 'RevokeAllSessionsView', 'authentication.delete'),
    ('apps/crm/views.py', 'LeadToggleOpportunityView', 'crm.update'),
    ('apps/crm/views.py', 'AddActivityView', 'crm.create'),
    ('apps/documents/views.py', 'DocumentUploadView', 'documents.create'),
    ('apps/helpdesk/views.py', 'AddReplyView', 'helpdesk.create'),
    ('apps/hrms/views.py', 'CheckInView', 'hrms.create'),
    ('apps/hrms/views.py', 'CheckOutView', 'hrms.create'),
    ('apps/hrms/views.py', 'PayrollProcessView', 'hrms.approve'),
    ('apps/inventory/views.py', 'StockAdjustmentView', 'inventory.create'),
    ('apps/inventory/views.py', 'TransferActionView', 'inventory.approve'),
    ('apps/inventory/views.py', 'ShipDeliveryView', 'inventory.approve'),
    ('apps/manufacturing/views.py', 'MOActionView', 'manufacturing.approve'),
    ('apps/manufacturing/views.py', 'WorkOrderStartView', 'manufacturing.update'),
    ('apps/manufacturing/views.py', 'MaterialPlanRunView', 'manufacturing.create'),
    ('apps/notifications/views.py', 'MarkReadView', 'notifications.update'),
    ('apps/pos/views.py', 'POSCheckoutAPIView', 'pos.create'),
    ('apps/projects/views.py', 'TaskMoveView', 'projects.update'),
    ('apps/projects/views.py', 'AddCommentView', 'projects.create'),
    ('apps/projects/views.py', 'LogTimeView', 'projects.create'),
    ('apps/purchase/views.py', 'PurchaseOrderSubmitView', 'purchase.update'),
    ('apps/purchase/views.py', 'VendorBidActionView', 'purchase.approve'),
    ('apps/purchase/views.py', 'VendorEvaluateView', 'purchase.create'),
    ('apps/sales/views.py', 'POSAPIView', 'sales.create'),
    ('apps/workflow/views.py', 'WorkflowDesignerSaveAPI', 'workflow.update'),
    ('apps/workflow/views.py', 'StepReorderView', 'workflow.update'),
    ('apps/workflow/views.py', 'WorkflowActionAPIView', 'workflow.approve'),
]

for file_path, class_name, new_perm in fixes:
    if not os.path.exists(file_path):
        print(f'File not found: {file_path}')
        continue
    with open(file_path, encoding='utf-8') as f:
        content = f.read()

    # We want to replace required_permission = \"...\" ONLY inside the specific class.
    lines = content.split('\n')
    inside_class = False
    class_indent = ''
    for i, line in enumerate(lines):
        if line.startswith('class ' + class_name):
            inside_class = True
            class_indent = line[:len(line) - len(line.lstrip())]
            continue

        if inside_class:
            if line.strip().startswith('class ') and len(line) - len(line.lstrip()) <= len(class_indent):
                inside_class = False

        if inside_class and 'required_permission' in line:
            old_perm_match = re.search(r'\"([a-zA-Z0-9_\.]+)\"', line) or re.search(r'\'([a-zA-Z0-9_\.]+)\'', line)
            if old_perm_match:
                lines[i] = line.replace(old_perm_match.group(0), f'\"{new_perm}\"')
                print(f'Updated {class_name} in {file_path}')
                inside_class = False # Only replace the first one

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
