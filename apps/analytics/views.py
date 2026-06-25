from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView, ListView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import JsonResponse
from .models import CustomReport
from django.db.models import Sum, Count, Avg
from django.apps import apps
import json

class AnalyticsRequiredMixin(LoginRequiredMixin):
    pass

class AnalyticsDashboardView(AnalyticsRequiredMixin, TemplateView):
    template_name = 'analytics/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['reports'] = CustomReport.objects.filter(created_by=self.request.user)
        return context

class ReportBuilderView(AnalyticsRequiredMixin, TemplateView):
    template_name = 'analytics/report_builder.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['modules'] = CustomReport.MODULE_CHOICES
        context['charts'] = CustomReport.CHART_CHOICES
        context['aggregates'] = CustomReport.AGGREGATE_CHOICES
        return context

    def post(self, request, *args, **kwargs):
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        module_source = request.POST.get('module_source')
        chart_type = request.POST.get('chart_type')
        group_by_field = request.POST.get('group_by_field')
        aggregate_field = request.POST.get('aggregate_field')
        aggregate_function = request.POST.get('aggregate_function')

        report = CustomReport.objects.create(
            name=name,
            description=description,
            module_source=module_source,
            chart_type=chart_type,
            group_by_field=group_by_field,
            aggregate_field=aggregate_field,
            aggregate_function=aggregate_function,
            created_by=request.user
        )
        messages.success(request, f"Report '{report.name}' saved successfully!")
        return redirect('analytics:dashboard')

class GenerateReportAPIView(AnalyticsRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        report_id = request.GET.get('report_id')
        if not report_id:
            return JsonResponse({'error': 'No report ID provided'}, status=400)
        
        report = get_object_or_404(CustomReport, pk=report_id, created_by=request.user)
        
        model_map = {
            'sales': ('sales', 'SalesOrder'),
            'purchases': ('purchase', 'PurchaseOrder'),
            'inventory': ('inventory', 'InventoryTransaction'),
            'accounting': ('accounting', 'JournalItem'),
        }
        
        app_label, model_name = model_map.get(report.module_source, (None, None))
        if not app_label:
            return JsonResponse({'error': 'Invalid module source'}, status=400)
            
        try:
            ModelClass = apps.get_model(app_label, model_name)
        except LookupError:
            return JsonResponse({'error': f'Model not found: {app_label}.{model_name}'}, status=400)
            
        group_by = report.group_by_field
        agg_field = report.aggregate_field
        
        if report.aggregate_function == 'sum':
            agg_func = Sum(agg_field)
        elif report.aggregate_function == 'avg':
            agg_func = Avg(agg_field)
        else:
            agg_func = Count(agg_field)

        try:
            qs = ModelClass.objects.all().values(group_by).annotate(value=agg_func).order_by(group_by)
            labels = []
            values = []
            for row in qs:
                labels.append(str(row[group_by]) if row[group_by] else 'Unknown')
                val = row['value']
                values.append(float(val) if val is not None else 0)
                
            return JsonResponse({
                'labels': labels,
                'values': values,
                'chart_type': report.chart_type,
                'name': report.name
            })
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

class GetModuleFieldsAPIView(AnalyticsRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        module_source = request.GET.get('module')
        if not module_source:
            return JsonResponse({'fields': []})

        model_map = {
            'sales': ('sales', 'SalesOrder'),
            'purchases': ('purchase', 'PurchaseOrder'),
            'inventory': ('inventory', 'InventoryTransaction'),
            'accounting': ('accounting', 'JournalItem'),
        }

        app_label, model_name = model_map.get(module_source, (None, None))
        if not app_label:
            return JsonResponse({'fields': []})

        try:
            ModelClass = apps.get_model(app_label, model_name)
            fields = [f.name for f in ModelClass._meta.get_fields() if not f.is_relation or f.many_to_one]
            return JsonResponse({'fields': sorted(fields)})
        except LookupError:
            return JsonResponse({'fields': []})

class ReportDeleteView(AnalyticsRequiredMixin, View):
    def post(self, request, pk):
        report = get_object_or_404(CustomReport, pk=pk, created_by=request.user)
        report.delete()
        messages.success(request, f"Report deleted successfully!")
        return redirect('analytics:dashboard')
