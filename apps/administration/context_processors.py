from apps.administration.models import InstalledApp


def active_apps(request):
    """
    Injects a list of active app labels into the template context
    so that the sidebar can conditionally hide/show links.
    """
    context = {"active_app_labels": []}

    if hasattr(request, "user") and request.user.is_authenticated:
        company = getattr(request.user, "primary_company", None)
        if company:
            apps = InstalledApp.objects.filter(
                company=company, is_active=True
            ).values_list("app_label", flat=True)
            context["active_app_labels"] = list(apps)

    return context
