from core.permissions import HttpMethodPermissionMixin


class CompanyMixin(HttpMethodPermissionMixin):
    """
    Standard mixin for class-based views to enforce company scoping.
    Provides self.company() returning the user's primary company.
    """
    def company(self):
        return self.request.user.primary_company

