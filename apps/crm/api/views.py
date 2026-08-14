from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.crm.api.serializers import (
    CampaignSerializer,
    ContractSerializer,
    CustomerSerializer,
    LeadActivitySerializer,
    LeadSerializer,
)
from apps.crm.models import Campaign, Contract, Customer, Lead, LeadActivity
from core.api.mixins import TenantScopedViewSetMixin
from core.pagination import StandardResultsSetPagination


class CampaignViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission

    queryset = Campaign.objects.all()
    serializer_class = CampaignSerializer
    pagination_class = StandardResultsSetPagination


class LeadViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission

    queryset = Lead.objects.all()
    serializer_class = LeadSerializer
    pagination_class = StandardResultsSetPagination

    @action(detail=True, methods=["post"])
    def convert_to_customer(self, request, pk=None):
        lead = self.get_object()
        if lead.converted_to_customer:
            return Response(
                {"error": "Lead already converted to customer"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create customer
        customer = Customer.objects.create(
            company=lead.company,
            name=lead.company_name or lead.name,
            email=lead.email,
            phone=lead.phone,
            mobile=lead.mobile,
            address_line1=lead.address_line1,
            city=lead.city,
            state=lead.state,
            country=lead.country,
            zip_code=lead.zip_code,
            sales_rep=lead.assigned_to,
        )

        lead.status = Lead.Status.WON
        lead.converted_to_customer = True
        lead.customer = customer
        lead.save(update_fields=["status", "converted_to_customer", "customer"])

        return Response({"status": "converted", "customer_id": customer.pk})

    @action(detail=True, methods=["post"])
    def update_status(self, request, pk=None):
        lead = self.get_object()
        new_status = request.data.get("status")
        if not new_status or new_status not in [
            choice[0] for choice in Lead.Status.choices
        ]:
            return Response(
                {"error": "Invalid status"}, status=status.HTTP_400_BAD_REQUEST
            )

        lead.status = new_status
        lead.save(update_fields=["status"])
        return Response({"status": "status_updated"})


class CustomerViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission

    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    pagination_class = StandardResultsSetPagination

    @action(detail=True, methods=["get"])
    def statement(self, request, pk=None):
        customer = self.get_object()
        # Mocking statement generation. In a real app, this would aggregate invoices and payments.
        return Response(
            {
                "customer": customer.name,
                "outstanding_balance": customer.outstanding_balance,
                "download_url": f"/api/v1/crm/customers/{customer.pk}/download-statement/",
            }
        )

    @action(detail=True, methods=["get"])
    def activity_timeline(self, request, pk=None):
        customer = self.get_object()
        # Mocking activity timeline. Would aggregate lead activities, order history, tickets, etc.
        return Response(
            {
                "timeline": [
                    {
                        "date": customer.created_at,
                        "type": "system",
                        "description": "Customer created",
                    }
                ]
            }
        )


class LeadActivityViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission

    queryset = LeadActivity.objects.all()
    serializer_class = LeadActivitySerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()
        lead_id = self.request.query_params.get("lead")
        if lead_id:
            qs = qs.filter(lead_id=lead_id)
        return qs

    def perform_create(self, serializer):
        user = getattr(self.request, "user", None)
        company = getattr(user, "primary_company", None)
        serializer.save(company=company)


class ContractViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission

    queryset = Contract.objects.all()
    serializer_class = ContractSerializer
    pagination_class = StandardResultsSetPagination
