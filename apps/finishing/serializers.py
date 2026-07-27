from rest_framework import serializers
from .models import FinishingQualityCheck, Packing, Dispatch, FinishingOperation, FinishingReceipt, ReworkAssignment
from apps.orders.models import Order


class FinishingQualityCheckSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    color_name = serializers.CharField(source="color.name", read_only=True, default=None)
    size_name = serializers.CharField(source="size.name", read_only=True, default=None)
    product_summary = serializers.SerializerMethodField()
    alteration_pending = serializers.IntegerField(read_only=True)
    final_good = serializers.IntegerField(read_only=True)
    allocatable_rework = serializers.IntegerField(read_only=True)
    allocated_for_rework = serializers.IntegerField(read_only=True)
    returned_from_rework = serializers.IntegerField(read_only=True)
    awaiting_second_qc = serializers.IntegerField(read_only=True)

    class Meta:
        model = FinishingQualityCheck
        fields = "__all__"
        read_only_fields = ["checked_by", "checked_date", "quantity_reworked_passed", "quantity_reworked_failed"]

    def get_product_summary(self, obj):
        names = []
        for it in obj.order.items.all():
            n = it.product.name if it.product_id else None
            if n and n not in names:
                names.append(n)
        return ", ".join(names) if names else "—"

    def create(self, validated_data):
        validated_data["checked_by"] = self.context["request"].user
        return super().create(validated_data)


class ReworkAssignmentSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="qc.order.order_number", read_only=True)
    order = serializers.IntegerField(source="qc.order_id", read_only=True)
    color_name = serializers.CharField(source="qc.color.name", read_only=True, default=None)
    size_name = serializers.CharField(source="qc.size.name", read_only=True, default=None)
    operator_name = serializers.CharField(source="operator.name", read_only=True)
    product_summary = serializers.SerializerMethodField()
    earned_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    paid_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    pending_pay_quantity = serializers.IntegerField(read_only=True)
    pending_pay_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = ReworkAssignment
        fields = [
            "id", "qc", "order", "order_number", "color_name", "size_name", "product_summary",
            "operator", "operator_name", "quantity", "rate_per_piece", "returned_quantity",
            "paid_quantity", "status", "allocated_by", "completed_at", "remarks",
            "earned_amount", "paid_amount", "pending_pay_quantity", "pending_pay_amount", "created_at",
        ]
        read_only_fields = ["status", "returned_quantity", "paid_quantity", "allocated_by", "completed_at"]

    def get_product_summary(self, obj):
        names = []
        for it in obj.qc.order.items.all():
            n = it.product.name if it.product_id else None
            if n and n not in names:
                names.append(n)
        return ", ".join(names) if names else "—"

    def validate(self, attrs):
        qc = attrs.get("qc")
        qty = attrs.get("quantity") or 0
        if qty <= 0:
            raise serializers.ValidationError({"quantity": "Allocate at least 1 piece."})
        if qc and qty > qc.allocatable_rework:
            raise serializers.ValidationError({
                "quantity": f"Only {qc.allocatable_rework} altered piece(s) are still unallocated for this QC row."})
        return attrs

    def create(self, validated_data):
        validated_data["allocated_by"] = self.context["request"].user
        return super().create(validated_data)


class PackingSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)

    class Meta:
        model = Packing
        fields = "__all__"
        read_only_fields = ["packed_by", "packed_date"]

    def create(self, validated_data):
        validated_data["packed_by"] = self.context["request"].user
        return super().create(validated_data)


class FinishingOperationSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    vendor_name = serializers.CharField(source="vendor.company_name", read_only=True, default=None)

    class Meta:
        model = FinishingOperation
        fields = [
            "id", "order", "order_number", "operation_type", "quantity", "quantity_rejected", "cost_per_piece", "total_cost",
            "is_outsourced", "vendor", "vendor_name", "status", "performed_date", "remarks",
            "recorded_by", "created_at", "updated_at",
        ]
        read_only_fields = ["recorded_by"]

    def create(self, validated_data):
        validated_data["recorded_by"] = self.context["request"].user
        if validated_data.get("cost_per_piece") and not validated_data.get("total_cost"):
            validated_data["total_cost"] = validated_data["cost_per_piece"] * validated_data["quantity"]
        return super().create(validated_data)

    def update(self, instance, validated_data):
        cost_per_piece = validated_data.get("cost_per_piece", instance.cost_per_piece)
        quantity = validated_data.get("quantity", instance.quantity)
        if cost_per_piece and "total_cost" not in validated_data:
            validated_data["total_cost"] = cost_per_piece * quantity
        return super().update(instance, validated_data)


class FinishingReceiptSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)

    class Meta:
        model = FinishingReceipt
        fields = ["id", "order", "order_number", "quantity_sent", "sent_by", "sent_at", "remarks"]
        read_only_fields = ["sent_by", "sent_at"]


class DispatchSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    party_name = serializers.CharField(source="order.party.name", read_only=True, default=None)

    class Meta:
        model = Dispatch
        fields = [
            "id", "order", "order_number", "party_name", "dispatched_by", "dispatch_date",
            "challan_number", "size_breakdown", "color_breakdown",
            "tracking_number", "carrier", "mode_of_transport", "quantity_dispatched",
            "delivery_date", "delivery_acknowledged_by", "transport_cost",
            "status", "remarks", "created_at",
        ]
        read_only_fields = ["dispatched_by"]

    @staticmethod
    def available_to_dispatch(order):
        """Good pieces ready to ship = every QC row's final-good (first-pass
        passed + reworked-and-passed), minus whatever's already been dispatched
        for this order on other challans."""
        from .models import FinishingQualityCheck
        final_good = sum(qc.final_good for qc in FinishingQualityCheck.objects.filter(order=order))
        already = sum(d.quantity_dispatched or 0 for d in Dispatch.objects.filter(order=order))
        return max(final_good - already, 0), final_good, already

    def validate(self, attrs):
        # Only guard the quantity when the challan is actually going out.
        order = attrs.get("order") or getattr(self.instance, "order", None)
        status = attrs.get("status", getattr(self.instance, "status", None))
        qty = attrs.get("quantity_dispatched", getattr(self.instance, "quantity_dispatched", None))
        if order and status == Dispatch.Status.DISPATCHED and qty:
            available, final_good, already = self.available_to_dispatch(order)
            # On update, the current record's own quantity shouldn't count against itself.
            if self.instance and self.instance.status == Dispatch.Status.DISPATCHED:
                available += (self.instance.quantity_dispatched or 0)
            if int(qty) > available:
                raise serializers.ValidationError({
                    "quantity_dispatched": f"Only {available} good piece(s) are available to dispatch "
                    f"(QC-passed {final_good}, already dispatched {already}). Dispatch that many or fewer — "
                    f"the rest can go on a later partial shipment."})
        return attrs

    def _advance_if_dispatched(self, dispatch):
        # Bug fix: previously a raw string assignment that bypassed
        # Order.advance_status()'s forward-only guard entirely.
        if dispatch.status == Dispatch.Status.DISPATCHED:
            dispatch.order.advance_status(Order.Status.DISPATCHED)
            self._record_into_store(dispatch)

    def _record_into_store(self, dispatch):
        """Close the loop: a dispatched order's finished garments are logged
        into Store's finished-goods register (idempotent per order)."""
        from django.utils import timezone
        from apps.store.models import FinishedGoodsReceipt
        request = self.context.get("request")
        FinishedGoodsReceipt.objects.get_or_create(
            order=dispatch.order,
            defaults={
                "quantity": dispatch.quantity_dispatched or 0,
                "dispatch_reference": dispatch.tracking_number or "",
                "received_at": timezone.now(),
                "received_by": getattr(request, "user", None),
                "remarks": f"Auto-logged from dispatch {dispatch.tracking_number or dispatch.order.order_number}.",
            },
        )

    def create(self, validated_data):
        validated_data["dispatched_by"] = self.context["request"].user
        dispatch = super().create(validated_data)
        self._advance_if_dispatched(dispatch)
        return dispatch

    def update(self, instance, validated_data):
        # Bug fix: previously only create() advanced the order -- PATCHing
        # an existing Dispatch from PENDING to DISPATCHED did nothing.
        dispatch = super().update(instance, validated_data)
        self._advance_if_dispatched(dispatch)
        return dispatch
