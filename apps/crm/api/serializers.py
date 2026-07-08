from rest_framework import serializers

from apps.crm.models import Campaign, Contract, Customer, Lead, LeadActivity


class CampaignSerializer(serializers.ModelSerializer):
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


class LeadSerializer(serializers.ModelSerializer):
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


class CustomerSerializer(serializers.ModelSerializer):
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


class LeadActivitySerializer(serializers.ModelSerializer):
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


class ContractSerializer(serializers.ModelSerializer):
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
