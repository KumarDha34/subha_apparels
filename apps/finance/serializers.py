from decimal import Decimal
from django.db import transaction as db_transaction
from django.utils import timezone
from rest_framework import serializers
from .models import (
    PurchaseOrder, PurchaseOrderItem, Invoice, PaymentRecord,
    IncomeRecord, ExpenseRecord, Quotation, CustomerInvoice,
)


class CustomerInvoiceSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    party_name = serializers.CharField(source="order.party.name", read_only=True, default=None)
    due_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = CustomerInvoice
        fields = [
            "id", "invoice_number", "order", "order_number", "party_name", "invoice_date",
            "amount", "paid_amount", "due_amount", "payment_status", "due_date", "remarks",
            "created_by", "created_at",
        ]
        read_only_fields = ["invoice_number", "payment_status", "created_by"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        invoice = super().create(validated_data)
        # Raising the sales invoice moves the order into financial closure.
        if invoice.order_id:
            invoice.order.advance_status(invoice.order.Status.INVOICED)
        return invoice


class QuotationSerializer(serializers.ModelSerializer):
    party_name = serializers.CharField(source="party.name", read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    converted_order_number = serializers.CharField(source="converted_order.order_number", read_only=True, default=None)
    is_expired = serializers.SerializerMethodField()

    class Meta:
        model = Quotation
        fields = [
            "id", "quote_number", "party", "party_name", "product", "product_code", "product_name",
            "quantity", "rate_per_piece", "amount", "valid_till", "terms", "status",
            "converted_order", "converted_order_number", "is_expired", "created_by", "created_at",
        ]
        read_only_fields = ["quote_number", "status", "converted_order", "created_by"]

    def get_is_expired(self, obj):
        return obj.status not in ("CONVERTED", "REJECTED") and obj.valid_till < timezone.localdate()

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    fabric_type_name = serializers.CharField(source="fabric_type.name", read_only=True, default=None)
    color_name = serializers.CharField(source="color.name", read_only=True, default=None)
    accessory_label = serializers.CharField(source="accessory.__str__", read_only=True, default=None)

    class Meta:
        model = PurchaseOrderItem
        fields = [
            "id", "purchase_order", "material_type", "item_name",
            "fabric_type", "fabric_type_name", "color", "color_name",
            "accessory", "accessory_label", "quantity", "no_of_rolls", "unit", "rate",
            "received_quantity", "total",
        ]
        # purchase_order is always set by the parent PurchaseOrderSerializer's
        # create()/update(), never provided by the client. rate is only ever
        # set during receiving, never at PO creation/edit.
        read_only_fields = ["purchase_order", "rate"]


class PurchaseOrderSerializer(serializers.ModelSerializer):
    items = PurchaseOrderItemSerializer(many=True, required=False)
    vendor_name = serializers.CharField(source="vendor.company_name", read_only=True, default=None)
    party_name = serializers.CharField(source="party.name", read_only=True, default=None)
    order_number = serializers.CharField(source="related_order.order_number", read_only=True, default=None)

    class Meta:
        model = PurchaseOrder
        fields = [
            "id", "po_number", "vendor", "vendor_name", "party", "party_name",
            "related_order", "order_number", "po_type", "po_date", "receipt_status",
            "remarks", "created_by", "items", "created_at",
        ]
        read_only_fields = ["po_number", "created_by", "receipt_status"]

    def validate(self, attrs):
        po_type = attrs.get("po_type", getattr(self.instance, "po_type", None))
        vendor = attrs.get("vendor", getattr(self.instance, "vendor", None))
        party = attrs.get("party", getattr(self.instance, "party", None))
        related_order = attrs.get("related_order", getattr(self.instance, "related_order", None))
        items = attrs.get("items")

        if po_type in (PurchaseOrder.POType.BULK, PurchaseOrder.POType.ORDER_SPECIFIC) and not vendor:
            raise serializers.ValidationError({"vendor": "Vendor is required for this purchase type."})
        if po_type == PurchaseOrder.POType.CUSTOMER_SUPPLIED:
            if not party:
                raise serializers.ValidationError({"party": "Party is required for customer-supplied purchases."})
            if vendor:
                raise serializers.ValidationError({"vendor": "Vendor must not be set for customer-supplied purchases."})
        if po_type == PurchaseOrder.POType.ORDER_SPECIFIC and not related_order:
            raise serializers.ValidationError({"related_order": "Select the order this purchase is for."})
        if po_type == PurchaseOrder.POType.BULK and related_order:
            raise serializers.ValidationError({"related_order": "Bulk purchases must not reference an order."})

        if items is not None:
            if not items:
                raise serializers.ValidationError({"items": "Add at least one item."})
            for item in items:
                mt = item.get("material_type")
                if mt == PurchaseOrderItem.MaterialType.FABRIC:
                    if not item.get("fabric_type") or not item.get("color"):
                        raise serializers.ValidationError({"items": "Each fabric item needs a fabric type and a color."})
                    if item.get("accessory"):
                        raise serializers.ValidationError({"items": "Fabric items must not have an accessory set."})
                elif mt == PurchaseOrderItem.MaterialType.ACCESSORY:
                    if not item.get("accessory"):
                        raise serializers.ValidationError({"items": "Each accessory item needs an accessory selected."})
                    if item.get("fabric_type") or item.get("color"):
                        raise serializers.ValidationError({"items": "Accessory items must not have a fabric type/color set."})
                else:
                    raise serializers.ValidationError({"items": "Each item needs a material_type of FABRIC or ACCESSORY."})
        return attrs

    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        validated_data["created_by"] = self.context["request"].user
        with db_transaction.atomic():
            po = PurchaseOrder.objects.create(**validated_data)
            for item in items_data:
                PurchaseOrderItem.objects.create(purchase_order=po, **item)
            if po.po_type == PurchaseOrder.POType.CUSTOMER_SUPPLIED:
                from . import services
                services.receive_customer_supplied(po, self.context["request"].user)
        return po

    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", None)
        if items_data is not None:
            if instance.receipt_status != PurchaseOrder.ReceiptStatus.PENDING:
                raise serializers.ValidationError({"items": "Items can no longer be edited once receiving has started."})
            with db_transaction.atomic():
                instance.items.all().delete()
                for item in items_data:
                    PurchaseOrderItem.objects.create(purchase_order=instance, **item)
        return super().update(instance, validated_data)


class InvoiceSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.company_name", read_only=True)
    po_number = serializers.CharField(source="purchase_order.po_number", read_only=True)
    paid_amount = serializers.SerializerMethodField()
    due_amount = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id", "invoice_number", "purchase_order", "po_number", "vendor", "vendor_name",
            "invoice_date", "subtotal", "tax_amount", "additional_costs", "total_amount",
            "payment_status", "due_date", "remarks", "paid_amount", "due_amount", "created_at",
        ]
        read_only_fields = ["invoice_number", "total_amount"]

    def _latest_payment(self, invoice):
        return invoice.payment_records.order_by("-id").first()

    def get_paid_amount(self, invoice):
        latest = self._latest_payment(invoice)
        return latest.paid_amount if latest else 0

    def get_due_amount(self, invoice):
        latest = self._latest_payment(invoice)
        return latest.due_amount if latest else invoice.total_amount


class AddCostSerializer(serializers.Serializer):
    """Payload for POST /invoices/{id}/add-cost/"""
    key = serializers.ChoiceField(choices=["transportation", "customs", "documentation", "other"])
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))


class PaymentRecordSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True)

    class Meta:
        model = PaymentRecord
        fields = [
            "id", "purchase_order", "invoice", "invoice_number", "total_amount",
            "paid_amount", "due_amount", "payment_status", "invoice_date", "due_date",
            "payment_date", "payment_method", "notes", "recorded_by", "created_at",
        ]
        read_only_fields = ["due_amount", "recorded_by"]

    def create(self, validated_data):
        validated_data["recorded_by"] = self.context["request"].user
        return super().create(validated_data)


class IncomeRecordSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True, default=None)
    party_name = serializers.CharField(source="order.party.name", read_only=True, default=None)
    invoice_number = serializers.CharField(source="customer_invoice.invoice_number", read_only=True, default=None)

    class Meta:
        model = IncomeRecord
        fields = [
            "id", "order", "order_number", "party_name", "customer_invoice", "invoice_number",
            "income_type", "amount", "received_date", "payment_method", "reference",
            "remarks", "recorded_by", "created_at",
        ]
        read_only_fields = ["recorded_by"]

    def create(self, validated_data):
        validated_data["recorded_by"] = self.context["request"].user
        return super().create(validated_data)


class ExpenseRecordSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True, default=None)

    class Meta:
        model = ExpenseRecord
        fields = ["id", "category", "amount", "expense_date", "order", "order_number", "remarks", "recorded_by", "created_at"]
        read_only_fields = ["recorded_by"]

    def create(self, validated_data):
        validated_data["recorded_by"] = self.context["request"].user
        return super().create(validated_data)
