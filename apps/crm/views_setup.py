from core.mixins import CompanyMixin
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .models import LeadAssignmentRule, SalesTarget, Territory


# ════════════════════════ TERRITORIES ═════════════════════════════════════════
class TerritoryListView(CompanyMixin, ListView):
    template_name = "crm/setup/territory_list.html"
    context_object_name = "territories"

    def get_queryset(self):
        return Territory.objects.filter(company=self.company())


class TerritoryCreateView(CompanyMixin, CreateView):
    model = Territory
    fields = ["name", "code", "manager", "sales_reps"]
    template_name = "crm/setup/territory_form.html"
    success_url = reverse_lazy("crm:territory_list")

    def form_valid(self, form):
        form.instance.company = self.company()
        messages.success(self.request, "Territory created.")
        return super().form_valid(form)


class TerritoryUpdateView(CompanyMixin, UpdateView):
    model = Territory
    fields = ["name", "code", "manager", "sales_reps"]
    template_name = "crm/setup/territory_form.html"
    success_url = reverse_lazy("crm:territory_list")

    def get_queryset(self):
        return Territory.objects.filter(company=self.company())

    def form_valid(self, form):
        messages.success(self.request, "Territory updated.")
        return super().form_valid(form)


class TerritoryDeleteView(CompanyMixin, DeleteView):
    model = Territory
    success_url = reverse_lazy("crm:territory_list")

    def get_queryset(self):
        return Territory.objects.filter(company=self.company())


# ════════════════════════ LEAD ASSIGNMENT RULES ══════════════════════════════
class LeadAssignmentRuleListView(CompanyMixin, ListView):
    template_name = "crm/setup/rule_list.html"
    context_object_name = "rules"

    def get_queryset(self):
        return LeadAssignmentRule.objects.filter(company=self.company())


class LeadAssignmentRuleCreateView(CompanyMixin, CreateView):
    model = LeadAssignmentRule
    fields = [
        "name",
        "is_active",
        "source_criteria",
        "min_revenue",
        "assignment_method",
        "target_territory",
        "priority",
    ]
    template_name = "crm/setup/rule_form.html"
    success_url = reverse_lazy("crm:rule_list")

    def form_valid(self, form):
        form.instance.company = self.company()
        messages.success(self.request, "Assignment rule created.")
        return super().form_valid(form)


class LeadAssignmentRuleUpdateView(CompanyMixin, UpdateView):
    model = LeadAssignmentRule
    fields = [
        "name",
        "is_active",
        "source_criteria",
        "min_revenue",
        "assignment_method",
        "target_territory",
        "priority",
    ]
    template_name = "crm/setup/rule_form.html"
    success_url = reverse_lazy("crm:rule_list")

    def get_queryset(self):
        return LeadAssignmentRule.objects.filter(company=self.company())

    def form_valid(self, form):
        messages.success(self.request, "Assignment rule updated.")
        return super().form_valid(form)


class LeadAssignmentRuleDeleteView(CompanyMixin, DeleteView):
    model = LeadAssignmentRule
    success_url = reverse_lazy("crm:rule_list")

    def get_queryset(self):
        return LeadAssignmentRule.objects.filter(company=self.company())


# ════════════════════════ SALES TARGETS ══════════════════════════════════════
class SalesTargetListView(CompanyMixin, ListView):
    template_name = "crm/setup/target_list.html"
    context_object_name = "targets"

    def get_queryset(self):
        return SalesTarget.objects.filter(company=self.company()).order_by(
            "-start_date"
        )


class SalesTargetCreateView(CompanyMixin, CreateView):
    model = SalesTarget
    fields = [
        "sales_rep",
        "period",
        "start_date",
        "end_date",
        "target_revenue",
        "target_deals",
    ]
    template_name = "crm/setup/target_form.html"
    success_url = reverse_lazy("crm:target_list")

    def form_valid(self, form):
        form.instance.company = self.company()
        messages.success(self.request, "Sales target created.")
        return super().form_valid(form)


class SalesTargetUpdateView(CompanyMixin, UpdateView):
    model = SalesTarget
    fields = [
        "sales_rep",
        "period",
        "start_date",
        "end_date",
        "target_revenue",
        "target_deals",
    ]
    template_name = "crm/setup/target_form.html"
    success_url = reverse_lazy("crm:target_list")

    def get_queryset(self):
        return SalesTarget.objects.filter(company=self.company())

    def form_valid(self, form):
        messages.success(self.request, "Sales target updated.")
        return super().form_valid(form)


class SalesTargetDeleteView(CompanyMixin, DeleteView):
    model = SalesTarget
    success_url = reverse_lazy("crm:target_list")

    def get_queryset(self):
        return SalesTarget.objects.filter(company=self.company())
