from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class APIExplorerView(LoginRequiredMixin, TemplateView):
    template_name = "api/explorer.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["modules"] = [
            {
                "name": "CRM",
                "icon": "fas fa-handshake",
                "endpoints": [
                    {
                        "method": "GET",
                        "path": "/api/crm/leads/",
                        "desc": "List all leads",
                    },
                    {
                        "method": "POST",
                        "path": "/api/crm/leads/",
                        "desc": "Create a lead",
                    },
                    {
                        "method": "GET",
                        "path": "/api/crm/customers/",
                        "desc": "List all customers",
                    },
                    {
                        "method": "POST",
                        "path": "/api/crm/customers/",
                        "desc": "Create a customer",
                    },
                ],
            },
            {
                "name": "Sales",
                "icon": "fas fa-chart-line",
                "endpoints": [
                    {
                        "method": "GET",
                        "path": "/api/sales/quotations/",
                        "desc": "List quotations",
                    },
                    {
                        "method": "GET",
                        "path": "/api/sales/orders/",
                        "desc": "List sales orders",
                    },
                    {
                        "method": "POST",
                        "path": "/api/sales/orders/",
                        "desc": "Create sales order",
                    },
                    {
                        "method": "GET",
                        "path": "/api/sales/invoices/",
                        "desc": "List invoices",
                    },
                ],
            },
            {
                "name": "Purchase",
                "icon": "fas fa-shopping-bag",
                "endpoints": [
                    {
                        "method": "GET",
                        "path": "/api/purchase/vendors/",
                        "desc": "List vendors",
                    },
                    {
                        "method": "GET",
                        "path": "/api/purchase/orders/",
                        "desc": "List purchase orders",
                    },
                    {
                        "method": "GET",
                        "path": "/api/purchase/bills/",
                        "desc": "List bills",
                    },
                ],
            },
            {
                "name": "Inventory",
                "icon": "fas fa-boxes",
                "endpoints": [
                    {
                        "method": "GET",
                        "path": "/api/inventory/products/",
                        "desc": "List products",
                    },
                    {
                        "method": "POST",
                        "path": "/api/inventory/products/",
                        "desc": "Create a product",
                    },
                    {
                        "method": "GET",
                        "path": "/api/inventory/warehouses/",
                        "desc": "List warehouses",
                    },
                ],
            },
            {
                "name": "HRMS",
                "icon": "fas fa-users",
                "endpoints": [
                    {
                        "method": "GET",
                        "path": "/api/hrms/employees/",
                        "desc": "List employees",
                    },
                    {
                        "method": "GET",
                        "path": "/api/hrms/leaves/",
                        "desc": "List leave requests",
                    },
                    {
                        "method": "POST",
                        "path": "/api/hrms/leaves/",
                        "desc": "Submit leave request",
                    },
                ],
            },
            {
                "name": "Manufacturing",
                "icon": "fas fa-industry",
                "endpoints": [
                    {
                        "method": "GET",
                        "path": "/api/manufacturing/boms/",
                        "desc": "List Bills of Material",
                    },
                    {
                        "method": "GET",
                        "path": "/api/manufacturing/orders/",
                        "desc": "List manufacturing orders",
                    },
                    {
                        "method": "POST",
                        "path": "/api/manufacturing/orders/",
                        "desc": "Create manufacturing order",
                    },
                ],
            },
        ]
        return ctx
