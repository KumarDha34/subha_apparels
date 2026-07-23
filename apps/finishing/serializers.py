from rest_framework import serializers
from .models import FinishingQualityCheck, Packing, Dispatch, FinishingOperation, FinishingReceipt
from apps.orders.models import Order


class FinishingQualityCheckSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    color_name = serializers.CharField(source="color.name", read_only=True, default=None)
    size_name = serializers.CharField(source="size.name", read_only=True, default=None)
    alteration_pending = serializers.IntegerField(read_only=True)
    final_good = serializers.IntegerField(read_only=True)

    class Meta:
        model = FinishingQualityCheck
        fields = "__all__"
        read_only_fields = ["checked_by", "checked_date", "quantity_reworked_passed", "quantity_reworked_failed"]

    def create(self, validated_data):
        validated_data["checked_by"] = self.context["request"].user
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
