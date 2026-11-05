"""
Blog Notification Helpers
Thin wrappers around NotificationService for blog-specific events.
"""

from apps.notifications.services import NotificationService


def notify_post_published(post, published_by):
    """Notify the author that their post went live."""
    if not post.author or post.author == published_by:
        return
    NotificationService.send(
        recipient=post.author,
        title="Your Blog Post is Live!",
        message=f"'{post.title}' has been published. {post.public_url or ''}",
        notification_type="success",
        channels=["in_app", "email"],
        action_url=f"/blog/posts/{post.pk}/",
        company=post.company,
        related_object=post,
    )


def notify_post_scheduled(post, scheduled_by):
    """Notify relevant users when a post is scheduled."""
    if post.author and post.author != scheduled_by:
        NotificationService.send(
            recipient=post.author,
            title="Blog Post Scheduled",
            message=(
                f"'{post.title}' is scheduled to publish on "
                f"{post.scheduled_publish_at.strftime('%Y-%m-%d %H:%M')} UTC."
            ),
            notification_type="info",
            channels=["in_app"],
            action_url=f"/blog/posts/{post.pk}/",
            company=post.company,
        )


def notify_social_published(publication):
    """Notify the post author when their post goes live on social media."""
    post = publication.post
    if not post.author:
        return
    NotificationService.send(
        recipient=post.author,
        title="Post Shared on Social Media",
        message=(
            f"'{post.title}' was shared on {publication.account.get_platform_display()}. "
            f"{publication.external_post_url or ''}"
        ),
        notification_type="success",
        channels=["in_app"],
        action_url=f"/blog/posts/{post.pk}/",
        company=post.company,
        related_object=publication,
    )


def notify_social_failed(publication):
    """Alert admins when social publishing fails."""
    from apps.authentication.models import UserCompany, User
    admin_pks = UserCompany.objects.filter(
        company=publication.post.company,
        is_active=True,
        role__in=["company_admin", "super_admin"],
    ).values_list("user_id", flat=True)

    for user in User.objects.filter(pk__in=admin_pks):
        NotificationService.send(
            recipient=user,
            title="Social Media Publishing Failed",
            message=(
                f"Failed to publish '{publication.post.title}' to "
                f"{publication.account.get_platform_display()}. "
                f"Error: {publication.error_detail[:200]}"
            ),
            notification_type="error",
            channels=["in_app"],
            action_url=f"/blog/posts/{publication.post_id}/",
            company=publication.post.company,
        )


def notify_website_sync_failed(pub):
    """Alert admins when website publishing fails."""
    from apps.authentication.models import UserCompany, User
    admin_pks = UserCompany.objects.filter(
        company=pub.post.company,
        is_active=True,
        role__in=["company_admin", "super_admin"],
    ).values_list("user_id", flat=True)

    for user in User.objects.filter(pk__in=admin_pks):
        NotificationService.send(
            recipient=user,
            title="Website Publishing Failed",
            message=(
                f"Failed to publish '{pub.post.title}' to {pub.integration.name}. "
                f"Error: {pub.error_detail[:200]}"
            ),
            notification_type="error",
            channels=["in_app"],
            action_url=f"/blog/posts/{pub.post_id}/",
            company=pub.post.company,
        )
