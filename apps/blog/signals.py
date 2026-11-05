"""
Blog signals — triggers automatic side-effects on model events.
"""

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.blog.models import BlogEnquiry, BlogPost, BlogRevision

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=BlogPost)
def _snapshot_revision_on_content_change(sender, instance, **kwargs):
    """
    Before saving a published/approved post that already has a PK,
    snapshot the previous version as a BlogRevision so history is preserved.
    """
    if not instance.pk:
        return  # new post — nothing to snapshot

    try:
        previous = BlogPost.objects.get(pk=instance.pk)
    except BlogPost.DoesNotExist:
        return

    content_changed = (
        previous.title != instance.title
        or previous.content_raw != instance.content_raw
        or previous.excerpt != instance.excerpt
        or previous.meta_description != instance.meta_description
    )

    if not content_changed:
        return

    next_version = (previous.revision_count or 0) + 1
    try:
        BlogRevision.objects.create(
            post=previous,
            version=next_version,
            title=previous.title,
            subtitle=previous.subtitle,
            content=previous.content,
            excerpt=previous.excerpt,
            seo_title=previous.seo_title,
            meta_description=previous.meta_description,
            meta_keywords=previous.meta_keywords,
            revised_by=getattr(instance, "_current_user", None),
            change_summary="Auto-snapshot before content update.",
        )
        instance.revision_count = next_version
    except Exception as exc:
        logger.warning("BlogPost revision snapshot failed: %s", exc)


@receiver(post_save, sender=BlogEnquiry)
def _process_blog_enquiry(sender, instance, created, **kwargs):
    """
    After a new BlogEnquiry is saved with status=NEW,
    queue the CRM lead creation task asynchronously.
    """
    if not created:
        return
    if instance.status != BlogEnquiry.Status.NEW:
        return

    try:
        from apps.blog.tasks import process_blog_enquiry_task
        process_blog_enquiry_task.delay(str(instance.pk))
    except Exception as exc:
        logger.warning("Failed to queue blog enquiry processing task: %s", exc)
