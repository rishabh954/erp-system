from rest_framework import serializers

from core.api.fields import TenantModelSerializer
from apps.inventory.models import (
    InventoryTransfer,
    Product,
    StockMovement,
    StockRecord,
    Warehouse,
)


class ProductSerializer(TenantModelSerializer):
    class Meta:
        model = Product
        fields = "__all__"
        read_only_fields = [
            "company",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]


class WarehouseSerializer(TenantModelSerializer):
    class Meta:
        model = Warehouse
        fields = "__all__"
        read_only_fields = [
            "company",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]


class StockRecordSerializer(TenantModelSerializer):
    class Meta:
        model = StockRecord
        fields = "__all__"
        read_only_fields = [
            "company",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]


class StockMovementSerializer(TenantModelSerializer):
    class Meta:
        model = StockMovement
        fields = "__all__"
        read_only_fields = [
            "company",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]


class InventoryTransferSerializer(TenantModelSerializer):
    class Meta:
        model = InventoryTransfer
        fields = "__all__"
        read_only_fields = [
            "company",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]
