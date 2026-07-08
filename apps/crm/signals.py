from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import LeadActivity


@receiver(post_save, sender=LeadActivity)
def update_lead_score(sender, instance, created, **kwargs):
    if created:
        lead = instance.lead
        # Simple lead scoring algorithm
        points_map = {"call": 10, "meeting": 20, "email": 5, "task": 2, "note": 1}
        points = points_map.get(instance.activity_type, 0)
        lead.lead_score += points

        # If score exceeds 50, mark as opportunity
        if lead.lead_score >= 50 and not lead.is_opportunity:
            lead.is_opportunity = True

        lead.save(update_fields=["lead_score", "is_opportunity"])
