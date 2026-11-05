from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
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
from core.tenancy import get_active_company


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
        if getattr(self, "action", None) == "convert_to_customer":
            return "crm.approve"
        if getattr(self, "action", None) == "update_status":
            if request and request.data.get("status") == Lead.Status.WON:
                return "crm.approve"
            return "crm.update"
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

    def perform_create(self, serializer):
        user = self.request.user
        company = get_active_company(self.request)
        if not company:
            raise PermissionDenied("No active company membership.")
        self.request.company = company
        lead = serializer.save(company=company, created_by=user)
        from apps.crm.notifications import notify_lead_created

        notify_lead_created(lead, user)

    @action(detail=True, methods=["post"])
    def convert_to_customer(self, request, pk=None):
        lead = self.get_object()
        from apps.crm.services import convert_lead_to_customer

        lead, customer, created = convert_lead_to_customer(lead)
        return Response(
            {
                "status": "converted",
                "customer_id": customer.pk,
                "customer_reused": not created,
            }
        )

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

        if new_status == Lead.Status.WON:
            from apps.crm.services import convert_lead_to_customer

            lead, customer, _ = convert_lead_to_customer(lead)
            return Response(
                {"status": "status_updated", "customer_id": customer.pk}
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
        company = get_active_company(self.request)
        if not company:
            raise PermissionDenied("No active company membership.")
        self.request.company = company
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
