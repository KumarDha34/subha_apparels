from django.db.models import Sum
from rest_framework import serializers
from django.db import transaction as db_transaction
from apps.store.models import AccessoryStockTransaction
from apps.cutting.models import Bundle
from .models import BundleReceipt, ProductionQualityCheck, AccessoryIssue, BundleAccessoryIssue, OperatorAccessoryIssue, ProcessDispatch


class ProcessDispatchSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    party_name = serializers.CharField(source="order.party.name", read_only=True, default=None)
    order_label = serializers.SerializerMethodField()
    vendor_name = serializers.CharField(source="vendor.company_name", read_only=True, default=None)
    department_display = serializers.CharField(source="get_department_display", read_only=True)

    def get_order_label(self, obj):
        if not obj.order_id:
            return None
        names = []
        for it in obj.order.items.all():
            n = it.product.name if it.product_id else None
            if n and n not in names:
                names.append(n)
        return f"{obj.order.order_number} — {', '.join(names) if names else '—'}"
    loss_quantity = serializers.IntegerField(read_only=True)
    size_breakdown = serializers.SerializerMethodField()
    color_breakdown = serializers.SerializerMethodField()

    def _bd(self, obj):
        from apps.operators.services import order_piece_breakdown
        if not hasattr(self, "_bd_cache"):
            self._bd_cache = {}
        if obj.order_id not in self._bd_cache:
            self._bd_cache[obj.order_id] = order_piece_breakdown(obj.order_id)
        return self._bd_cache[obj.order_id]

    def get_size_breakdown(self, obj):
        return self._bd(obj)["by_size"]

    def get_color_breakdown(self, obj):
        return self._bd(obj)["by_color"]

    class Meta:
        model = ProcessDispatch
        fields = [
            "id", "dispatch_number", "order", "order_number", "party_name", "order_label", "department", "department_display",
            "quantity_sent", "sent_date", "sent_by", "quantity_received", "received_date", "received_by",
            "loss_reason", "loss_status", "loss_reviewed_by", "loss_reviewed_at", "loss_review_notes",
            "size_breakdown", "color_breakdown",
            "is_outsourced", "vendor", "vendor_name", "cost_per_piece", "cost", "loss_quantity", "status", "remarks",
            "created_at", "updated_at",
        ]
        read_only_fields = ["dispatch_number", "sent_by", "quantity_received", "received_date", "received_by",
                            "loss_reason", "loss_status", "loss_reviewed_by", "loss_reviewed_at", "loss_review_notes", "status"]

    def validate(self, attrs):
        # Guard the send: never let more pieces leave the floor than are
        # actually available. Pieces currently OUT at a department must be
        # received back before they can be sent to another department.
        if self.instance is None:  # only on create (a new send)
            order = attrs.get("order")
            qty = attrs.get("quantity_sent") or 0
            if qty <= 0:
                raise serializers.ValidationError({"quantity_sent": "Enter at least 1 piece to send."})
            available = ProcessDispatch.available_to_send(order.id if order else None)
            if qty > available:
                raise serializers.ValidationError({
                    "quantity_sent": f"Only {available} piece(s) are available to send right now. "
                                     f"Pieces already out at a department must be received back first "
                                     f"before they can be sent onward."
                })
        return attrs

    def create(self, validated_data):
        validated_data["sent_by"] = self.context["request"].user
        # Auto-calculate the total processing cost: rate/piece x pieces sent.
        cpp = validated_data.get("cost_per_piece")
        if cpp is not None and not validated_data.get("cost"):
            validated_data["cost"] = cpp * validated_data.get("quantity_sent", 0)
        return super().create(validated_data)


class OperatorAccessoryIssueSerializer(serializers.ModelSerializer):
    operator_name = serializers.CharField(source="operator.name", read_only=True)
    accessory_label = serializers.CharField(source="accessory_stock.accessory.__str__", read_only=True)
    order_number = serializers.CharField(source="order.order_number", read_only=True, default=None)
    remaining_quantity = serializers.DecimalField(read_only=True, max_digits=12, decimal_places=2)

    class Meta:
        model = OperatorAccessoryIssue
        fields = [
            "id", "issue_number", "operator", "operator_name", "accessory_stock", "accessory_label",
            "order", "order_number", "issued_quantity", "used_quantity", "pieces_covered",
            "returned_quantity", "remaining_quantity", "issued_by", "issued_date", "remarks",
            "created_at", "updated_at",
        ]
        read_only_fields = ["issue_number", "used_quantity", "returned_quantity", "issued_by"]

    def validate(self, attrs):
        stock = attrs.get("accessory_stock", getattr(self.instance, "accessory_stock", None))
        qty = attrs.get("issued_quantity", getattr(self.instance, "issued_quantity", 0))
        if self.instance is None and stock and qty > stock.available_quantity:
            raise serializers.ValidationError(f"Insufficient accessory stock. Available: {stock.available_quantity}.")
        return attrs

    def create(self, validated_data):
        validated_data["issued_by"] = self.context["request"].user
        with db_transaction.atomic():
            issue = OperatorAccessoryIssue.objects.create(**validated_data)
            AccessoryStockTransaction.objects.create(
                accessory_stock=issue.accessory_stock,
                transaction_type=AccessoryStockTransaction.TransactionType.ISSUE,
                quantity=issue.issued_quantity, reference=issue.issue_number,
                remarks=f"Issued directly to operator {issue.operator.name}", created_by=self.context["request"].user)
            stock = issue.accessory_stock
            stock.available_quantity -= issue.issued_quantity
            stock.save(update_fields=["available_quantity", "updated_at"])
        return issue


class BundleReceiptSerializer(serializers.ModelSerializer):
    bundle_number = serializers.CharField(source="bundle.bundle_number", read_only=True)
    color_name = serializers.CharField(source="bundle.color.name", read_only=True, default=None)
    size_name = serializers.CharField(source="bundle.size.name", read_only=True, default=None)
    quantity = serializers.IntegerField(source="bundle.quantity", read_only=True, default=None)
    order_number = serializers.CharField(source="bundle.cutting_order.order.order_number", read_only=True, default=None)
    cutting_number = serializers.CharField(source="bundle.cutting_order.cutting_number", read_only=True, default=None)
    received_by_name = serializers.CharField(source="received_by.get_full_name", read_only=True, default=None)

    class Meta:
        model = BundleReceipt
        fields = ["id", "bundle", "bundle_number", "color_name", "size_name", "quantity",
                  "order_number", "cutting_number", "received_date", "received_by", "received_by_name", "remarks", "created_at"]
        read_only_fields = ["received_date", "received_by"]

    def create(self, validated_data):
        validated_data["received_by"] = self.context["request"].user
        with db_transaction.atomic():
            receipt = super().create(validated_data)
            receipt.bundle.status = Bundle.Status.RECEIVED
            receipt.bundle.save(update_fields=["status", "updated_at"])
            # Receiving a cut bundle onto the floor is the real start of
            # production -- advance the order so it shows up on Send to
            # Finishing even when no accessories were issued (accessories are
            # optional for many styles).
            cutting_order = receipt.bundle.cutting_order
            order = cutting_order.order if cutting_order and cutting_order.order_id else None
            if order:
                order.advance_status(order.Status.IN_PRODUCTION)
        return receipt


class ProductionQualityCheckSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductionQualityCheck
        fields = ["id", "bundle", "checked_by", "passed", "defects_found", "notes", "checked_date", "created_at"]
        read_only_fields = ["checked_by", "checked_date"]

    def create(self, validated_data):
        validated_data["checked_by"] = self.context["request"].user
        return super().create(validated_data)


class AccessoryIssueSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    accessory_label = serializers.CharField(source="accessory_stock.accessory.__str__", read_only=True)

    class Meta:
        model = AccessoryIssue
        fields = [
            "id", "issue_number", "order", "order_number", "accessory_stock", "accessory_label",
            "issued_quantity", "issued_date", "issued_by", "remarks", "created_at", "updated_at",
        ]
        read_only_fields = ["issue_number", "issued_by"]

    def validate(self, attrs):
        stock = attrs.get("accessory_stock", getattr(self.instance, "accessory_stock", None))
        qty = attrs.get("issued_quantity", getattr(self.instance, "issued_quantity", 0))
        if self.instance is None and stock and qty > stock.available_quantity:
            raise serializers.ValidationError(f"Insufficient accessory stock. Available: {stock.available_quantity}.")
        return attrs

    def create(self, validated_data):
        validated_data["issued_by"] = self.context["request"].user
        with db_transaction.atomic():
            issue = AccessoryIssue.objects.create(**validated_data)
            AccessoryStockTransaction.objects.create(
                accessory_stock=issue.accessory_stock,
                transaction_type=AccessoryStockTransaction.TransactionType.ISSUE,
                quantity=issue.issued_quantity,
                reference=issue.issue_number,
                remarks=f"Issued to production for order {issue.order.order_number}",
                created_by=self.context["request"].user,
            )
            stock = issue.accessory_stock
            stock.available_quantity -= issue.issued_quantity
            stock.save(update_fields=["available_quantity", "updated_at"])
            issue.order.advance_status(issue.order.Status.IN_PRODUCTION)
        return issue


class BundleAccessoryIssueSerializer(serializers.ModelSerializer):
    bundle_number = serializers.CharField(source="bundle.bundle_number", read_only=True)
    accessory_label = serializers.CharField(source="accessory_issue.accessory_stock.accessory.__str__", read_only=True)
    operator_name = serializers.CharField(source="operator.name", read_only=True, default=None)

    class Meta:
        model = BundleAccessoryIssue
        fields = [
            "id", "bundle", "bundle_number", "accessory_issue", "accessory_label", "operator", "operator_name",
            "issued_quantity", "returned_quantity", "issued_by", "issued_at", "remarks",
        ]
        read_only_fields = ["returned_quantity", "issued_by", "issued_at"]

    def validate(self, attrs):
        accessory_issue = attrs.get("accessory_issue", getattr(self.instance, "accessory_issue", None))
        qty = attrs.get("issued_quantity", getattr(self.instance, "issued_quantity", 0))
        if self.instance is None and accessory_issue:
            already_allocated = accessory_issue.bundle_allocations.aggregate(q=Sum("issued_quantity"))["q"] or 0
            unallocated = accessory_issue.issued_quantity - already_allocated
            if qty > unallocated:
                raise serializers.ValidationError(
                    f"Only {unallocated} unallocated from {accessory_issue.issue_number} -- {qty} requested."
                )
        return attrs

    def create(self, validated_data):
        validated_data["issued_by"] = self.context["request"].user
        return super().create(validated_data)
