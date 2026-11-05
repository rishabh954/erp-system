from django.db import transaction

from apps.company.models import Company

from .models import Customer, Lead


@transaction.atomic
def convert_lead_to_customer(lead):
    """Convert a lead once, reusing an existing same-company email match."""
    Company.objects.select_for_update().get(pk=lead.company_id)
    lead = (
        Lead.objects.select_for_update()
        .select_related("customer")
        .get(pk=lead.pk, company_id=lead.company_id, is_deleted=False)
    )
    if lead.customer_id:
        return lead, lead.customer, False

    email = lead.email.strip()
    customer = None
    if email:
        customer = (
            Customer.objects.select_for_update()
            .filter(company_id=lead.company_id, email__iexact=email, is_deleted=False)
            .first()
        )

    created = customer is None
    if created:
        customer = Customer.objects.create(
            company_id=lead.company_id,
            name=lead.company_name or lead.name,
            email=email,
            phone=lead.phone,
            mobile=lead.mobile,
            sales_rep=lead.assigned_to,
        )

    lead.customer = customer
    lead.status = Lead.Status.WON
    lead.converted_to_customer = True
    lead.save(update_fields=["customer", "status", "converted_to_customer"])
    return lead, customer, created
