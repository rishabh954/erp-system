"""
Authentication Forms
Login, Register, Password Reset, Profile, 2FA
"""

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils.translation import gettext_lazy as _
from .models import User


class LoginForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'placeholder': 'you@company.com', 'autofocus': True}),
        label=_('Email Address'),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': '••••••••'}),
        label=_('Password'),
    )
    remember_me = forms.BooleanField(required=False, label=_('Remember me'))


class RegisterForm(forms.ModelForm):
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': '••••••••'}),
        label=_('Password'),
        min_length=8,
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': '••••••••'}),
        label=_('Confirm Password'),
    )

    class Meta:
        model  = User
        fields = ['first_name', 'last_name', 'email', 'phone']
        widgets = {
            'first_name': forms.TextInput(attrs={'placeholder': 'First name'}),
            'last_name':  forms.TextInput(attrs={'placeholder': 'Last name'}),
            'email':      forms.EmailInput(attrs={'placeholder': 'you@company.com'}),
            'phone':      forms.TextInput(attrs={'placeholder': '+1 234 567 8900'}),
        }

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(_('An account with this email already exists.'))
        return email

    def clean(self):
        cd = super().clean()
        if cd.get('password1') != cd.get('password2'):
            self.add_error('password2', _('Passwords do not match.'))
        return cd


class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(
        label=_('Email Address'),
        widget=forms.EmailInput(attrs={'placeholder': 'you@company.com'}),
    )


class PasswordResetConfirmForm(forms.Form):
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': '••••••••'}),
        label=_('New Password'),
        min_length=8,
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': '••••••••'}),
        label=_('Confirm New Password'),
    )

    def clean(self):
        cd = super().clean()
        if cd.get('password1') != cd.get('password2'):
            self.add_error('password2', _('Passwords do not match.'))
        return cd


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model  = User
        fields = [
            'first_name', 'last_name', 'phone',
            'language', 'timezone', 'theme',
            'date_format', 'avatar',
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name':  forms.TextInput(attrs={'class': 'form-control'}),
            'phone':      forms.TextInput(attrs={'class': 'form-control'}),
            'language':   forms.Select(attrs={'class': 'form-select'}),
            'timezone':   forms.TextInput(attrs={'class': 'form-control'}),
            'theme':      forms.Select(attrs={'class': 'form-select'}),
            'date_format': forms.TextInput(attrs={'class': 'form-control'}),
        }


class ChangePasswordForm(forms.Form):
    old_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        label=_('Current Password'),
    )
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        label=_('New Password'),
        min_length=8,
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        label=_('Confirm New Password'),
    )

    def __init__(self, user=None, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_old_password(self):
        old = self.cleaned_data.get('old_password')
        if self.user and not self.user.check_password(old):
            raise forms.ValidationError(_('Current password is incorrect.'))
        return old

    def clean(self):
        cd = super().clean()
        if cd.get('password1') != cd.get('password2'):
            self.add_error('password2', _('Passwords do not match.'))
        return cd

    def save(self):
        if self.user:
            self.user.set_password(self.cleaned_data['password1'])
            self.user.save()
            return self.user


class TwoFactorVerifyForm(forms.Form):
    code = forms.CharField(
        max_length=10,
        label=_('Verification Code'),
        widget=forms.TextInput(attrs={
            'placeholder': '000000',
            'autocomplete': 'one-time-code',
            'inputmode': 'numeric',
            'pattern': '[0-9]*',
            'class': 'form-control text-center fw-700',
            'style': 'font-size:28px;letter-spacing:8px',
        }),
    )
