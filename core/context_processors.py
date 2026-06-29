def company_context(request):
    return {
        'current_company': getattr(request, 'company', None),
    }


def notification_context(request):
    if not request.user.is_authenticated:
        return {'unread_notification_count': 0}
    from apps.notifications.models import Notification
    count = Notification.objects.filter(
        recipient=request.user, is_read=False
    ).count()
    return {'unread_notification_count': count}


def theme_context(request):
    theme = 'light'
    if request.user.is_authenticated:
        theme = getattr(request.user, 'theme', 'light')
    return {'user_theme': theme}
