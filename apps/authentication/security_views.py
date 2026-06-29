from django.views.generic import TemplateView, View, ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.contrib import messages
import pyotp
import qrcode
import qrcode.image.svg
from io import BytesIO
from apps.authentication.models import UserSession, LoginHistory, IPRestriction

class SecurityDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'authentication/security_dashboard.html'
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['recent_logins'] = LoginHistory.objects.filter(user=self.request.user)[:5]
        ctx['active_sessions'] = UserSession.objects.filter(user=self.request.user)
        ctx['ip_restrictions'] = IPRestriction.objects.filter(user=self.request.user)
        return ctx

class TwoFactorSetupView(LoginRequiredMixin, View):
    template_name = 'authentication/2fa_setup.html'
    
    def get(self, request):
        user = request.user
        if not user.totp_secret:
            user.totp_secret = pyotp.random_base32()
            user.save(update_fields=['totp_secret'])
            
        totp_uri = pyotp.totp.TOTP(user.totp_secret).provisioning_uri(name=user.email, issuer_name="ERP System")
        img = qrcode.make(totp_uri, image_factory=qrcode.image.svg.SvgImage)
        stream = BytesIO()
        img.save(stream)
        svg = stream.getvalue().decode('utf-8')
        
        return render(request, self.template_name, {'svg': svg, 'secret': user.totp_secret})
        
    def post(self, request):
        token = request.POST.get('token')
        totp = pyotp.TOTP(request.user.totp_secret)
        if totp.verify(token):
            request.user.two_factor_enabled = True
            request.user.save(update_fields=['two_factor_enabled'])
            messages.success(request, "Two-Factor Authentication successfully enabled!")
            return redirect('auth:security_dashboard')
        else:
            messages.error(request, "Invalid token. Please try again.")
            return redirect('auth:2fa_setup')

class SessionRevokeView(LoginRequiredMixin, View):
    def post(self, request, pk):
        try:
            session = UserSession.objects.get(pk=pk, user=request.user)
            # In a real scenario we'd also delete the Django session from django_session table
            # using SessionStore(session_key=session.session_key).delete()
            from django.contrib.sessions.backends.db import SessionStore
            s = SessionStore(session_key=session.session_key)
            s.delete()
            session.delete()
            messages.success(request, "Session revoked successfully.")
        except UserSession.DoesNotExist:
            pass
        return redirect('auth:security_dashboard')

class IPRestrictionAddView(LoginRequiredMixin, View):
    def post(self, request):
        ip = request.POST.get('ip_address')
        desc = request.POST.get('description', '')
        if ip:
            IPRestriction.objects.create(user=request.user, ip_address=ip, description=desc, is_allowed=True)
            messages.success(request, f"IP {ip} added to allowlist.")
        return redirect('auth:security_dashboard')
