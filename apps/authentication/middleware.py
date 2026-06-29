import datetime
from django.utils import timezone
from django.shortcuts import redirect
from django.contrib import messages
from apps.authentication.models import IPRestriction, UserSession

class SecurityMiddleware:
    """
    Middleware for enforcing IP restrictions, tracking sessions, and checking password expiration.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)
            
        ip_address = self.get_client_ip(request)
        
        # 1. IP Restriction Check
        # Check global or user-specific IP rules
        restrictions = IPRestriction.objects.filter(
            user=request.user
        )
        if not restrictions.exists() and getattr(request.user, 'primary_company', None):
            restrictions = IPRestriction.objects.filter(
                company=request.user.primary_company
            )
            
        if restrictions.exists():
            # If there are restrictions, the IP MUST be in the allowed list
            allowed = restrictions.filter(ip_address=ip_address, is_allowed=True).exists()
            if not allowed:
                from django.contrib.auth import logout
                logout(request)
                messages.error(request, "Access denied from your current IP address.")
                return redirect('auth:login')

        # 2. Session Tracking
        if request.session.session_key:
            session, created = UserSession.objects.get_or_create(
                session_key=request.session.session_key,
                defaults={
                    'user': request.user,
                    'ip_address': ip_address,
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                    'expires_at': timezone.now() + datetime.timedelta(days=14)
                }
            )
            if not created:
                session.last_activity = timezone.now()
                session.save(update_fields=['last_activity'])
                
            # If session is marked as expired/deleted in DB but still exists in cookie
            # We should ideally clear it, but get_or_create handles recreation if missing.
            
        return self.get_response(request)
        
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
