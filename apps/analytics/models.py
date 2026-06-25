from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class CustomReport(models.Model):
    MODULE_CHOICES = [
        ('sales', 'Sales Orders'),
        ('purchases', 'Purchase Orders'),
        ('inventory', 'Inventory Transactions'),
        ('accounting', 'Journal Items'),
    ]

    CHART_CHOICES = [
        ('bar', 'Bar Chart'),
        ('line', 'Line Chart'),
        ('pie', 'Pie Chart'),
        ('doughnut', 'Doughnut Chart'),
        ('table', 'Data Table'),
    ]

    AGGREGATE_CHOICES = [
        ('sum', 'Sum'),
        ('count', 'Count'),
        ('avg', 'Average'),
    ]

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    module_source = models.CharField(max_length=50, choices=MODULE_CHOICES)
    chart_type = models.CharField(max_length=20, choices=CHART_CHOICES, default='bar')
    
    group_by_field = models.CharField(max_length=100, help_text="The field to group the data by (e.g., status, created_at__month)")
    aggregate_field = models.CharField(max_length=100, help_text="The field to calculate (e.g., total_amount, id)")
    aggregate_function = models.CharField(max_length=20, choices=AGGREGATE_CHOICES, default='sum')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='analytics_reports')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name
