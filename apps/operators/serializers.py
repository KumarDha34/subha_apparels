from rest_framework import serializers
from apps.cutting.models import Bundle
from .models import Operator, OperatorRate, BundleAssignment, OperatorIncome


class OperatorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Operator
        fields = "__all__"


class OperatorRateSerializer(serializers.ModelSerializer):
    operator_name = serializers.CharField(source="operator.name", read_only=True)
    order_number = serializers.CharField(source="order.order_number", read_only=True, default=None)

    class Meta:
        model = OperatorRate
        fields = [
            "id", "operator", "operator_name", "product", "order", "order_number", "rate_type",
            "rate_amount", "effective_date", "is_active", "created_at",
        ]

    def validate(self, attrs):
        order = attrs.get("order", getattr(self.instance, "order", None))
        product = attrs.get("product", getattr(self.instance, "product", None))
        if order and product:
            raise serializers.ValidationError(
                "Leave Product blank for an order-specific rate -- it applies to all work on that order."
            )
        return attrs


class BundleAssignmentSerializer(serializers.ModelSerializer):
    bundle_number = serializers.CharField(source="bundle.bundle_number", read_only=True)
    size_name = serializers.CharField(source="bundle.size.name", read_only=True, default=None)
    color_name = serializers.CharField(source="bundle.color.name", read_only=True, default=None)
    product_code = serializers.CharField(source="bundle.cutting_order.order_item.product.code", read_only=True, default=None)
    product_name = serializers.CharField(source="bundle.cutting_order.order_item.product.name", read_only=True, default=None)
    order_number = serializers.CharField(source="bundle.cutting_order.order.order_number", read_only=True, default=None)
    operator_name = serializers.CharField(source="operator.name", read_only=True)
    shortage_quantity = serializers.IntegerField(read_only=True)

    class Meta:
        model = BundleAssignment
        fields = [
            "id", "bundle", "bundle_number", "size_name", "color_name", "product_code", "product_name", "order_number",
            "operator", "operator_name",
            "assigned_date", "completion_date", "status",
            "issued_quantity", "returned_quantity", "shortage_quantity",
            "shortage_reason", "shortage_reason_status", "shortage_reviewed_by",
            "shortage_reviewed_at", "shortage_review_notes",
            "quality_check_passed", "defects", "defect_reason", "remarks", "assigned_by", "created_at", "updated_at",
        ]
        read_only_fields = [
            "assigned_date", "assigned_by", "returned_quantity", "shortage_reason",
            "shortage_reason_status", "shortage_reviewed_by", "shortage_reviewed_at", "shortage_review_notes",
            "defects", "defect_reason",
        ]

    def create(self, validated_data):
        validated_data["assigned_by"] = self.context["request"].user
        if not validated_data.get("issued_quantity"):
            validated_data["issued_quantity"] = validated_data["bundle"].quantity
        # Allocating a bundle auto-starts it -- the operator begins immediately,
        # no separate manual "Start" step.
        validated_data["status"] = BundleAssignment.Status.IN_PROGRESS
        assignment = super().create(validated_data)
        bundle = assignment.bundle
        bundle.status = Bundle.Status.IN_PROGRESS
        bundle.save(update_fields=["status"])
        return assignment


class OperatorIncomeSerializer(serializers.ModelSerializer):
    operator_name = serializers.CharField(source="operator.name", read_only=True)

    class Meta:
        model = OperatorIncome
        fields = [
            "id", "operator", "operator_name", "period_start", "period_end",
            "bundles_completed", "pieces_completed", "rate_applied",
            "total_income", "paid_amount", "payment_status", "payment_date", "remarks",
            "created_at",
        ]
        read_only_fields = ["total_income", "paid_amount"]
