import pytest
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest
from django.views import View
from core.permissions import PermissionRequiredMixin, HasModulePermission
from rest_framework.views import APIView
from rest_framework.request import Request
from django.contrib.auth.models import AnonymousUser

class DummyUser:
    is_authenticated = True
    def has_module_permission(self, module, action):
        return True

class MissingPermView(PermissionRequiredMixin, View):
    pass

class MissingPermAPIView(APIView):
    pass

def test_permission_required_mixin_fails_closed():
    view = MissingPermView()
    request = HttpRequest()
    request.user = DummyUser()
    
    with pytest.raises(ImproperlyConfigured) as exc_info:
        view.dispatch(request)
        
    assert "MissingPermView is missing the required_permission attribute" in str(exc_info.value)

def test_has_module_permission_fails_closed():
    perm = HasModulePermission()
    view = MissingPermAPIView()
    
    request = HttpRequest()
    request.user = DummyUser()
    drf_request = Request(request)
    # Force DRF request user to avoid authenticator override
    drf_request._user = DummyUser()
    
    with pytest.raises(ImproperlyConfigured) as exc_info:
        perm.has_permission(drf_request, view)
        
    assert "MissingPermAPIView is missing the required_permission attribute" in str(exc_info.value)
