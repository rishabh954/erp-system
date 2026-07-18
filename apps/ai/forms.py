from django import forms

from apps.ai.models import AIConfiguration


class AIConfigurationForm(forms.ModelForm):
    # Render existing keys masked; user can type a new key to overwrite.
    openai_api_key = forms.CharField(
        required=False,
        label="OpenAI API Key",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "sk-… (leave blank to keep existing)",
                "autocomplete": "new-password",
            },
            render_value=True,  # keeps the value in the field so it round-trips
        ),
        help_text="Your OpenAI secret key. Overrides the server-level .env value.",
    )
    gemini_api_key = forms.CharField(
        required=False,
        label="Google Gemini API Key",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "AIza… (leave blank to keep existing)",
                "autocomplete": "new-password",
            },
            render_value=True,
        ),
        help_text="Your Gemini API key. Used as fallback when OpenAI is unavailable.",
    )
    twilio_account_sid = forms.CharField(
        required=False,
        label="Twilio Account SID",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "ACxxxxxxxx"}),
    )
    twilio_auth_token = forms.CharField(
        required=False,
        label="Twilio Auth Token",
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "••••••••", "autocomplete": "new-password"},
            render_value=True,
        ),
    )
    twilio_phone_number = forms.CharField(
        required=False,
        label="Twilio Phone Number",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "+14155238886"}),
    )

    class Meta:
        model = AIConfiguration
        fields = [
            # Provider / model
            "ai_provider",
            "openai_model",
            "temperature",
            "max_tokens",
            # API keys
            "openai_api_key",
            "gemini_api_key",
            "twilio_account_sid",
            "twilio_auth_token",
            "twilio_phone_number",
            # Feature toggles
            "enable_chat",
            "enable_nlp_reports",
            "enable_forecasting",
            "enable_ocr",
            "enable_insights",
            "enable_recommendations",
        ]
        widgets = {
            "ai_provider": forms.Select(attrs={"class": "form-select"}),
            "openai_model": forms.TextInput(attrs={"class": "form-control"}),
            "temperature": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.1", "min": "0", "max": "2"}
            ),
            "max_tokens": forms.NumberInput(
                attrs={"class": "form-control", "step": "1", "min": "1"}
            ),
            "enable_chat": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "enable_nlp_reports": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "enable_forecasting": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "enable_ocr": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "enable_insights": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "enable_recommendations": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_openai_api_key(self):
        """If user submitted blank, keep the stored value."""
        value = self.cleaned_data.get("openai_api_key", "").strip()
        if not value and self.instance and self.instance.pk:
            return self.instance.openai_api_key
        return value

    def clean_gemini_api_key(self):
        value = self.cleaned_data.get("gemini_api_key", "").strip()
        if not value and self.instance and self.instance.pk:
            return self.instance.gemini_api_key
        return value

    def clean_twilio_auth_token(self):
        value = self.cleaned_data.get("twilio_auth_token", "").strip()
        if not value and self.instance and self.instance.pk:
            return self.instance.twilio_auth_token
        return value
