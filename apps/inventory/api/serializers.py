from rest_framework import serializers

from apps.inventory.models import (
    InventoryTransfer,
    Product,
    StockMovement,
    StockRecord,
    Warehouse,
)


class ProductSerializer(serializers.ModelSerializer):
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


class WarehouseSerializer(serializers.ModelSerializer):
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


class StockRecordSerializer(serializers.ModelSerializer):
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


class StockMovementSerializer(serializers.ModelSerializer):
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


class InventoryTransferSerializer(serializers.ModelSerializer):
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
