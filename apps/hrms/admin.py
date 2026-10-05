from django.contrib import admin

from .models import BiometricDevice


@admin.register(BiometricDevice)
class BiometricDeviceAdmin(admin.ModelAdmin):
    list_display = ("device_id", "company", "is_active", "created_at")
    list_filter = ("company", "is_active")
    search_fields = ("device_id", "company__name")
