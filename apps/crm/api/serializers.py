from rest_framework import serializers
from apps.crm.models import Lead, Customer, LeadActivity

class LeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        fields = '__all__'
        read_only_fields = ['company', 'created_by', 'updated_by', 'created_at', 'updated_at']

class CustomerSerializer(serializers.ModelSerializer):
    outstanding_balance = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    
    class Meta:
        model = Customer
        fields = '__all__'
        read_only_fields = ['company', 'created_by', 'updated_by', 'created_at', 'updated_at']

class LeadActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = LeadActivity
        fields = '__all__'
        read_only_fields = ['company', 'created_by', 'updated_by', 'created_at', 'updated_at']
