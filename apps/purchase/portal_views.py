from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView, TemplateView, View

from .models import Bill, PurchaseOrder, RequestForQuotation, VendorBid


class VendorPortalMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not hasattr(request.user, "vendor_profile"):
            messages.error(request, "Access denied. Vendor portal only.")
            return redirect("dashboard:index")
        return super().dispatch(request, *args, **kwargs)

    def get_vendor(self):
        return self.request.user.vendor_profile


class VendorPortalDashboardView(VendorPortalMixin, TemplateView):
    template_name = "purchase/portal/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        vendor = self.get_vendor()

        ctx["vendor"] = vendor
        ctx["active_rfqs"] = RequestForQuotation.objects.filter(
            status="published"
        ).count()
        ctx["pending_orders"] = PurchaseOrder.objects.filter(
            vendor=vendor, status__in=["sent", "confirmed"]
        ).count()
        ctx["unpaid_bills"] = Bill.objects.filter(
            vendor=vendor, status__in=["open", "partial"]
        ).count()

        ctx["recent_orders"] = PurchaseOrder.objects.filter(vendor=vendor).order_by(
            "-order_date"
        )[:5]
        return ctx


class VendorPortalRFQListView(VendorPortalMixin, ListView):
    template_name = "purchase/portal/rfq_list.html"
    context_object_name = "rfqs"
    paginate_by = 20

    def get_queryset(self):
        return RequestForQuotation.objects.filter(
            company=self.get_vendor().company, status="published"
        ).order_by("-created_at")


class VendorPortalRFQDetailView(VendorPortalMixin, DetailView):
    template_name = "purchase/portal/rfq_detail.html"
    context_object_name = "rfq"

    def get_object(self):
        return get_object_or_404(
            RequestForQuotation, pk=self.kwargs["pk"], company=self.get_vendor().company
        )


class VendorPortalBidCreateView(VendorPortalMixin, View):
    template_name = "purchase/portal/bid_form.html"

    def get(self, request, rfq_pk):
        rfq = get_object_or_404(
            RequestForQuotation, pk=rfq_pk, company=self.get_vendor().company
        )
        return render(request, self.template_name, {"rfq": rfq})

    def post(self, request, rfq_pk):
        rfq = get_object_or_404(
            RequestForQuotation, pk=rfq_pk, company=self.get_vendor().company
        )
        vendor = self.get_vendor()

        if VendorBid.objects.filter(rfq=rfq, vendor=vendor).exists():
            messages.error(request, "You have already submitted a bid for this RFQ.")
            return redirect("purchase:portal_rfq_detail", pk=rfq.pk)

        data = request.POST
        try:
            bid = VendorBid.objects.create(
                company=vendor.company,
                rfq=rfq,
                vendor=vendor,
                valid_until=data.get("valid_until") or None,
                notes=data.get("notes", ""),
            )

            from decimal import Decimal

            from .models import VendorBidLine

            total_amount = Decimal("0")
            for line in rfq.lines.all():
                price = Decimal(data.get(f"price_{line.pk}", "0"))
                VendorBidLine.objects.create(
                    bid=bid,
                    rfq_line=line,
                    unit_price=price,
                    subtotal=price * line.quantity,
                )
                total_amount += price * line.quantity

            bid.total_amount = total_amount
            bid.save(update_fields=["total_amount"])

            messages.success(request, "Bid submitted successfully!")
            return redirect("purchase:portal_dashboard")

        except Exception as e:
            messages.error(request, f"Error submitting bid: {e}")
            return redirect("purchase:portal_bid_create", rfq_pk=rfq.pk)
