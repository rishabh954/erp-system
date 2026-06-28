from decimal import Decimal
from django.db.models import Sum, F
from django.utils import timezone
from .models import Project, Sprint, TimeLog, Task

class ProjectTrackingService:
    @staticmethod
    def update_project_financials(project_id):
        """Calculates actual cost based on time logs."""
        project = Project.objects.get(id=project_id)
        
        # Aggregate cost from time logs (hours * hourly_rate)
        # Assuming we just calculate it in Python for simplicity if not easily aggregated via DB
        logs = TimeLog.objects.filter(task__project=project)
        total_cost = sum([log.hours * log.hourly_rate for log in logs])
        
        project.actual_cost = total_cost
        project.save(update_fields=['actual_cost'])
        return total_cost

    @staticmethod
    def get_sprint_burndown(sprint_id):
        """Returns data for a burndown chart (Ideal vs Actual remaining hours)."""
        sprint = Sprint.objects.get(id=sprint_id)
        tasks = sprint.tasks.filter(is_deleted=False)
        
        total_estimated = tasks.aggregate(total=Sum('estimated_hours'))['total'] or Decimal(0)
        
        # Calculate ideal burndown per day
        days = (sprint.end_date - sprint.start_date).days
        if days <= 0: days = 1
        burn_rate_per_day = total_estimated / Decimal(days)
        
        ideal_data = []
        for i in range(days + 1):
            date = sprint.start_date + timezone.timedelta(days=i)
            ideal_remaining = max(Decimal(0), total_estimated - (burn_rate_per_day * i))
            ideal_data.append({
                'date': date.strftime('%Y-%m-%d'),
                'remaining': float(ideal_remaining)
            })
            
        # Simplification: Actual remaining is just total estimated - total actual logged up to that day
        # For a true burndown, we would calculate remaining estimate per task, but this approximates it.
        actual_data = []
        total_actual_hours = tasks.aggregate(total=Sum('actual_hours'))['total'] or Decimal(0)
        current_remaining = max(Decimal(0), total_estimated - total_actual_hours)
        
        return {
            'sprint': sprint.name,
            'total_estimated': float(total_estimated),
            'current_remaining': float(current_remaining),
            'ideal_burndown': ideal_data
        }
