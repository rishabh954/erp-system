from celery import shared_task
from django.utils import timezone
from django.db.models import Sum
from datetime import timedelta
from apps.company.models import Company
from apps.accounting.models import Account
from apps.purchase.models import PurchaseOrder
from apps.notifications.tasks import send_bulk_notification
import logging

logger = logging.getLogger(__name__)

@shared_task
def generate_monthly_reports(company_id):
    """
    Auto-generate P&L snapshot for the closed month and notify the finance team.
    """
    try:
        company = Company.objects.get(pk=company_id)
    except Company.DoesNotExist:
        logger.error(f"Company {company_id} not found for monthly report.")
        return "Company not found."

    # In a real scenario, this would generate a PDF or snapshot record.
    # For now, we will calculate the totals and send a notification.
    
    # Simple P&L calculation for the current month (or last month)
    today = timezone.now().date()
    first_of_this_month = today.replace(day=1)
    last_month_end = first_of_this_month - timedelta(days=1)
    first_of_last_month = last_month_end.replace(day=1)

    revenue_accounts = Account.objects.filter(company=company, account_type=Account.AccountType.REVENUE)
    expense_accounts = Account.objects.filter(company=company, account_type=Account.AccountType.EXPENSE)

    total_revenue = sum(acc.get_balance(from_date=first_of_last_month, to_date=last_month_end) for acc in revenue_accounts)
    total_expense = sum(acc.get_balance(from_date=first_of_last_month, to_date=last_month_end) for acc in expense_accounts)
    net_profit = total_revenue - total_expense

    # Find users with 'finance_manager' role or similar to notify
    # Using superusers for simplicity if roles aren't easily filterable by name, 
    # but we can just use the company owner or active users.
    from apps.authentication.models import User
    recipients = User.objects.filter(companies=company, is_active=True, is_superuser=True) # Fallback to superusers
    
    notifications = []
    for user in recipients:
        notifications.append({
            'recipient_id': user.pk,
            'title': f"Monthly P&L Report ({first_of_last_month.strftime('%B %Y')})",
            'message': f"Revenue: {total_revenue}, Expenses: {total_expense}. Net Profit: {net_profit}.",
            'notification_type': 'info',
            'action_url': '/accounting/reports/profit-and-loss/',
            'action_label': 'View Report'
        })

    if notifications:
        send_bulk_notification.delay(notifications)
        return f"Monthly report notification sent to {len(notifications)} users."
    return "No recipients found for monthly report."


@shared_task
def check_overdue_payments():
    """
    Remind finance team about overdue vendor payments.
    """
    # Overdue Purchase Orders: balance_due > 0 and expected_delivery or order_date + payment_terms < today
    today = timezone.now().date()
    overdue_pos = []
    
    pos = PurchaseOrder.objects.filter(balance_due__gt=0).exclude(status__in=[PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.CANCELLED])
    
    for po in pos:
        due_date = po.expected_delivery or (po.order_date + timedelta(days=po.payment_terms))
        if due_date < today:
            overdue_pos.append(po)

    if not overdue_pos:
        return "No overdue payments found."

    from apps.authentication.models import User
    # Find finance managers (fallback to superusers)
    finance_users = User.objects.filter(is_active=True, is_superuser=True)
    
    notifications = []
    for po in overdue_pos:
        for user in finance_users:
            notifications.append({
                'recipient_id': user.pk,
                'title': 'Overdue Vendor Payment',
                'message': f"Purchase Order {po.number} to {po.vendor.name} is overdue. Balance: {po.balance_due}.",
                'notification_type': 'warning',
                'action_url': f"/purchase/orders/{po.pk}/",
                'action_label': 'View PO'
            })
            
    if notifications:
        send_bulk_notification.delay(notifications)
        return f"Queued {len(notifications)} overdue payment notifications."
    return "No finance users found to notify."
