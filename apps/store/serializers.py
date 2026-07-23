from rest_framework import serializers
from .models import FabricStock, StockTransaction, AccessoryStock, AccessoryStockTransaction, FinishedGoodsReceipt, OrderAdditionalCharge


class OrderAdditionalChargeSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    party_name = serializers.CharField(source="order.party.name", read_only=True, default=None)
    charge_type_display = serializers.CharField(source="get_charge_type_display", read_only=True)

    class Meta:
        model = OrderAdditionalCharge
        fields = [
            "id", "order", "order_number", "party_name", "charge_type", "charge_type_display",
            "amount", "remarks", "created_by", "created_at",
        ]
        read_only_fields = ["created_by"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class FinishedGoodsReceiptSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    party_name = serializers.CharField(source="order.party.name", read_only=True, default=None)
    received_by_name = serializers.CharField(source="received_by.username", read_only=True, default=None)

    class Meta:
        model = FinishedGoodsReceipt
        fields = [
            "id", "order", "order_number", "party_name", "quantity", "dispatch_reference",
            "received_at", "received_by", "received_by_name", "remarks", "created_at",
        ]
        read_only_fields = ["received_by"]

    def create(self, validated_data):
        from django.utils import timezone
        validated_data.setdefault("received_by", self.context["request"].user)
        validated_data.setdefault("received_at", timezone.now())
        return super().create(validated_data)


class _MovementMixin(serializers.Serializer):
    """Exposes the lifetime received / issued / returned / wastage totals that
    the viewset annotates onto each stock row (0 when not annotated)."""
    total_received = serializers.SerializerMethodField()
    total_issued = serializers.SerializerMethodField()
    total_returned = serializers.SerializerMethodField()
    total_wastage = serializers.SerializerMethodField()

    def _amt(self, obj, attr):
        return float(getattr(obj, attr, 0) or 0)

    def get_total_received(self, obj): return self._amt(obj, "total_received")
    def get_total_issued(self, obj): return self._amt(obj, "total_issued")
    def get_total_returned(self, obj): return self._amt(obj, "total_returned")
    def get_total_wastage(self, obj): return self._amt(obj, "total_wastage")


class FabricStockSerializer(_MovementMixin, serializers.ModelSerializer):
    fabric_type_name = serializers.CharField(source="fabric_type.name", read_only=True)
    color_name = serializers.CharField(source="color.name", read_only=True)
    vendor_name = serializers.CharField(source="vendor.company_name", read_only=True, default=None)
    supplied_by_party_name = serializers.CharField(source="supplied_by_party.name", read_only=True, default=None)
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = FabricStock
        fields = [
            "id", "fabric_type", "fabric_type_name", "color", "color_name",
            "width", "unit", "roll_number", "available_quantity",
            "total_received", "total_issued", "total_returned", "total_wastage",
            "reorder_level", "vendor", "vendor_name", "supplied_by_party", "supplied_by_party_name",
            "is_active", "is_low_stock", "created_at", "updated_at",
        ]
        read_only_fields = ["available_quantity"]


class StockTransactionSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = StockTransaction
        fields = [
            "id", "fabric_stock", "transaction_type", "quantity", "reference",
            "remarks", "transaction_date", "created_by", "created_by_name", "created_at",
        ]
        read_only_fields = ["created_by", "transaction_date"]

    def validate(self, attrs):
        transaction_type = attrs["transaction_type"]
        fabric_stock = attrs["fabric_stock"]
        quantity = attrs["quantity"]
        if transaction_type in (StockTransaction.TransactionType.ISSUE, StockTransaction.TransactionType.WASTAGE):
            if quantity > fabric_stock.available_quantity:
                raise serializers.ValidationError(
                    f"Insufficient stock. Available: {fabric_stock.available_quantity} {fabric_stock.unit}."
                )
        return attrs

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        transaction = StockTransaction.objects.create(**validated_data)

        stock = transaction.fabric_stock
        if transaction.transaction_type in (StockTransaction.TransactionType.RECEIPT, StockTransaction.TransactionType.RETURN):
            stock.available_quantity += transaction.quantity
        elif transaction.transaction_type in (StockTransaction.TransactionType.ISSUE, StockTransaction.TransactionType.WASTAGE):
            stock.available_quantity -= transaction.quantity
        elif transaction.transaction_type == StockTransaction.TransactionType.ADJUSTMENT:
            stock.available_quantity = transaction.quantity
        stock.save(update_fields=["available_quantity", "updated_at"])
        return transaction


class AccessoryStockSerializer(_MovementMixin, serializers.ModelSerializer):
    accessory_label = serializers.CharField(source="accessory.__str__", read_only=True)
    unit = serializers.CharField(source="accessory.unit", read_only=True)
    vendor_name = serializers.CharField(source="vendor.company_name", read_only=True, default=None)
    supplied_by_party_name = serializers.CharField(source="supplied_by_party.name", read_only=True, default=None)
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = AccessoryStock
        fields = [
            "id", "accessory", "accessory_label", "unit", "available_quantity",
            "total_received", "total_issued", "total_returned", "total_wastage",
            "reorder_level", "vendor", "vendor_name", "supplied_by_party", "supplied_by_party_name",
            "is_active", "is_low_stock", "created_at", "updated_at",
        ]
        read_only_fields = ["available_quantity"]


class AccessoryStockTransactionSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = AccessoryStockTransaction
        fields = [
            "id", "accessory_stock", "transaction_type", "quantity", "reference",
            "remarks", "transaction_date", "created_by", "created_by_name", "created_at",
        ]
        read_only_fields = ["created_by", "transaction_date"]

    def validate(self, attrs):
        transaction_type = attrs["transaction_type"]
        accessory_stock = attrs["accessory_stock"]
        quantity = attrs["quantity"]
        if transaction_type in (AccessoryStockTransaction.TransactionType.ISSUE, AccessoryStockTransaction.TransactionType.WASTAGE):
            if quantity > accessory_stock.available_quantity:
                raise serializers.ValidationError(
                    f"Insufficient stock. Available: {accessory_stock.available_quantity}."
                )
        return attrs

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        transaction = AccessoryStockTransaction.objects.create(**validated_data)

        stock = transaction.accessory_stock
        if transaction.transaction_type in (AccessoryStockTransaction.TransactionType.RECEIPT, AccessoryStockTransaction.TransactionType.RETURN):
            stock.available_quantity += transaction.quantity
        elif transaction.transaction_type in (AccessoryStockTransaction.TransactionType.ISSUE, AccessoryStockTransaction.TransactionType.WASTAGE):
            stock.available_quantity -= transaction.quantity
        elif transaction.transaction_type == AccessoryStockTransaction.TransactionType.ADJUSTMENT:
            stock.available_quantity = transaction.quantity
        stock.save(update_fields=["available_quantity", "updated_at"])
        return transaction
