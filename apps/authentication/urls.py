"""Authentication Web URLs"""
from django.urls import path
from .views import (
    LoginView, LogoutView, RegisterView, TwoFactorVerifyView,
    EmailVerifyView, PasswordResetRequestView, PasswordResetConfirmView,
    ProfileView, ProfileUpdateView, ChangePasswordView,
    RevokeSessionView, RevokeAllSessionsView, ActivityLogView,
)
from . import security_views

app_name = 'auth'

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('register/', RegisterView.as_view(), name='register'),
    path('two-factor/', TwoFactorVerifyView.as_view(), name='two_factor_verify'),
    path('verify-email/<str:token>/', EmailVerifyView.as_view(), name='email_verify'),
    path('password-reset/', PasswordResetRequestView.as_view(), name='password_reset'),
    path('password-reset/confirm/<str:token>/', PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('profile/', ProfileView.as_view(), name='profile'),
    path('profile/update/', ProfileUpdateView.as_view(), name='profile_update'),
    path('profile/change-password/', ChangePasswordView.as_view(), name='change_password'),
    path('sessions/<uuid:session_id>/revoke/', RevokeSessionView.as_view(), name='revoke_session'),
    path('sessions/revoke-all/', RevokeAllSessionsView.as_view(), name='revoke_all_sessions'),
    path('activity-log/', ActivityLogView.as_view(), name='activity_log'),
    
    # Enterprise Security
    path('security/', security_views.SecurityDashboardView.as_view(), name='security_dashboard'),
    path('security/2fa/setup/', security_views.TwoFactorSetupView.as_view(), name='2fa_setup'),
    path('security/sessions/<int:pk>/revoke/', security_views.SessionRevokeView.as_view(), name='session_revoke'),
    path('security/ip/add/', security_views.IPRestrictionAddView.as_view(), name='ip_add'),
]
