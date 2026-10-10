from rest_framework import serializers

from core.api.fields import TenantModelSerializer
from apps.crm.models import Campaign, Contract, Customer, Lead, LeadActivity


class CampaignSerializer(TenantModelSerializer):
    total_leads_count = serializers.IntegerField(read_only=True)
    opportunities_count = serializers.IntegerField(read_only=True)
    won_count = serializers.IntegerField(read_only=True)
    actual_revenue_generated = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )
    roi_percentage = serializers.FloatField(read_only=True)

    class Meta:
        model = Campaign
        fields = "__all__"
        read_only_fields = [
            "company",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]


class LeadSerializer(TenantModelSerializer):
    class Meta:
        model = Lead
        fields = "__all__"
        read_only_fields = [
            "company",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]


class CustomerSerializer(TenantModelSerializer):
    outstanding_balance = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )

    class Meta:
        model = Customer
        fields = "__all__"
        read_only_fields = [
            "company",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]


class LeadActivitySerializer(TenantModelSerializer):
    class Meta:
        model = LeadActivity
        fields = "__all__"
        read_only_fields = [
            "company",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]


class ContractSerializer(TenantModelSerializer):
    is_valid = serializers.BooleanField(read_only=True)
    days_until_expiry = serializers.IntegerField(read_only=True)

    class Meta:
        model = Contract
        fields = "__all__"
        read_only_fields = [
            "company",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]
