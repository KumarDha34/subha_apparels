from decimal import Decimal
from rest_framework import serializers
from apps.cutting.models import Bundle
from .models import Operator, BundleAssignment, OperatorIncome
from django.db.models import Sum

class GroupMemberSerializer(serializers.ModelSerializer):
    """Serializer for group members"""
    pieces = serializers.SerializerMethodField()
    defects = serializers.SerializerMethodField()
    efficiency = serializers.SerializerMethodField()
    
    class Meta:
        model = Operator
        fields = ["id", "name", "contact", "is_active", "joined_date", "pieces", "defects", "efficiency"]
    
    def get_pieces(self, obj):
        from apps.operators.models import BundleAssignment
        return BundleAssignment.objects.filter(
            operator=obj,
            status__in=[BundleAssignment.Status.COMPLETED, BundleAssignment.Status.QUALITY_CHECKED]
        ).aggregate(total=Sum('returned_quantity'))['total'] or 0
    
    def get_defects(self, obj):
        from apps.operators.models import BundleAssignment
        return BundleAssignment.objects.filter(operator=obj).aggregate(total=Sum('defects'))['total'] or 0
    
    def get_efficiency(self, obj):
        pieces = self.get_pieces(obj)
        defects = self.get_defects(obj)
        if pieces:
            return round((pieces - defects) / pieces * 100, 2)
        return 0


class OperatorSerializer(serializers.ModelSerializer):
    members = GroupMemberSerializer(source="member_list", many=True, read_only=True)
    member_count = serializers.IntegerField(read_only=True)
    is_group = serializers.SerializerMethodField()
    
    class Meta:
        model = Operator
        fields = "__all__"
    
    def get_is_group(self, obj):
        return obj.operator_type == "GROUP"


class BundleAssignmentSerializer(serializers.ModelSerializer):
    bundle_number = serializers.CharField(source="bundle.bundle_number", read_only=True)
    size_name = serializers.CharField(source="bundle.size.name", read_only=True, default=None)
    color_name = serializers.CharField(source="bundle.color.name", read_only=True, default=None)
    product_code = serializers.CharField(source="bundle.cutting_order.order_item.product.code", read_only=True, default=None)
    product_name = serializers.CharField(source="bundle.cutting_order.order_item.product.name", read_only=True, default=None)
    order_number = serializers.CharField(source="bundle.cutting_order.order.order_number", read_only=True, default=None)
    operator_name = serializers.CharField(source="operator.name", read_only=True)
    shortage_quantity = serializers.IntegerField(read_only=True)
    # Set by Production at allocation -- required when creating an assignment.
    rate_per_piece = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0"))
    # Pay tracking (per piece): earned = returned x rate; pending = unpaid pieces.
    pending_quantity = serializers.SerializerMethodField()
    earned_amount = serializers.SerializerMethodField()
    paid_amount = serializers.SerializerMethodField()
    pending_amount = serializers.SerializerMethodField()

    def _r(self, obj):
        return obj.returned_quantity or 0

    def get_pending_quantity(self, obj):
        return max(self._r(obj) - (obj.paid_quantity or 0), 0)

    def get_earned_amount(self, obj):
        return float(Decimal(self._r(obj)) * Decimal(obj.rate_per_piece or 0))

    def get_paid_amount(self, obj):
        return float(Decimal(obj.paid_quantity or 0) * Decimal(obj.rate_per_piece or 0))

    def get_pending_amount(self, obj):
        return float(Decimal(self.get_pending_quantity(obj)) * Decimal(obj.rate_per_piece or 0))

    class Meta:
        model = BundleAssignment
        fields = [
            "id", "bundle", "bundle_number", "size_name", "color_name", "product_code", "product_name", "order_number",
            "operator", "operator_name", "rate_per_piece",
            "paid_quantity", "pending_quantity", "earned_amount", "paid_amount", "pending_amount",
            "assigned_date", "completion_date", "status",
            "issued_quantity", "returned_quantity", "shortage_quantity",
            "shortage_reason", "shortage_reason_status", "shortage_reviewed_by",
            "shortage_reviewed_at", "shortage_review_notes",
            "quality_check_passed", "defects", "defect_reason", "remarks", "assigned_by", "created_at", "updated_at",
        ]
        read_only_fields = [
            "assigned_date", "assigned_by", "returned_quantity", "paid_quantity", "shortage_reason",
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
