from django.db.models import Sum
from rest_framework import serializers
from django.db import transaction as db_transaction
from apps.store.models import StockTransaction
from apps.orders.models import OrderItemColor
from .models import CuttingOrder, CuttingPiece, Bundle, Marker


class MarkerSerializer(serializers.ModelSerializer):
    fabric_type_name = serializers.CharField(source="fabric_type.name", read_only=True, default=None)

    class Meta:
        model = Marker
        fields = [
            "id", "marker_number", "name", "fabric_type", "fabric_type_name",
            "avg_consumption_per_set", "remarks", "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["marker_number"]


class CuttingOrderSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    order_type = serializers.CharField(source="order.order_type", read_only=True, default=None)
    party_name = serializers.CharField(source="order.party.name", read_only=True, default=None)
    cutting_instruction = serializers.CharField(source="order.cutting_instruction", read_only=True, default="")
    order_remarks = serializers.CharField(source="order.remarks", read_only=True, default="")
    product = serializers.IntegerField(source="order_item.product_id", read_only=True, default=None)
    product_name = serializers.CharField(source="order_item.product.name", read_only=True, default=None)
    product_code = serializers.CharField(source="order_item.product.code", read_only=True, default=None)
    fabric_type_name = serializers.CharField(source="fabric_issued.fabric_type.name", read_only=True)
    color = serializers.IntegerField(source="fabric_issued.color_id", read_only=True)
    color_name = serializers.CharField(source="fabric_issued.color.name", read_only=True)
    approved_average = serializers.DecimalField(source="order_item.approved_average", read_only=True, max_digits=8, decimal_places=3, default=None)
    marker_number = serializers.CharField(source="marker.marker_number", read_only=True, default=None)
    remaining_quantity = serializers.DecimalField(read_only=True, max_digits=12, decimal_places=2)
    ratio = serializers.SerializerMethodField()
    quantity_display = serializers.SerializerMethodField()
    bundle_count = serializers.SerializerMethodField()
    unsent_bundle_count = serializers.SerializerMethodField()

    half_roll = serializers.SerializerMethodField()

    def get_unsent_bundle_count(self, obj):
        """Bundles not yet sent to Production -- drives the Send-to-Production
        button (shown only while there are bundles still to send)."""
        return obj.bundles.filter(sent_to_production_at__isnull=True).count()

    def get_half_roll(self, obj):
        """Whether Merchandising flagged this cutting order's colour as
        'use half of each roll' -- so Cutting suggests cutting ~half."""
        if not obj.order_item_id:
            return False
        oic = obj.order_item.colors.filter(color_id=getattr(obj.fabric_issued, "color_id", None)).first()
        return bool(oic and oic.half_roll)

    def get_quantity_display(self, obj):
        """Fixed order -> total ordered pieces for this colour (e.g. '30');
        Ratio order -> the size ratio (e.g. '3:3:2')."""
        if not obj.order_item_id:
            return "—"
        oic = obj.order_item.colors.filter(color_id=getattr(obj.fabric_issued, "color_id", None)).first()
        if not oic:
            return "—"
        if obj.order and obj.order.order_type == "RATIO_BASED":
            return ":".join(str(sl.ratio_part) for sl in oic.size_lines.all())
        return str(sum((sl.quantity or 0) for sl in oic.size_lines.all()))

    def get_bundle_count(self, obj):
        return obj.bundles.count()

    def get_ratio(self, obj):
        """For a Ratio order, the size ratio for this cutting order's colour
        (e.g. [{size_name:'S', ratio_part:4}, ...]) so the cutting page can
        show it and pre-fill pieces-per-layer."""
        if not obj.order_id or obj.order.order_type != "RATIO_BASED" or not obj.order_item_id:
            return []
        oic = obj.order_item.colors.filter(color_id=getattr(obj.fabric_issued, "color_id", None)).first()
        if not oic:
            return []
        return [{"size": sl.size_id, "size_name": sl.size.name, "ratio_part": sl.ratio_part}
                for sl in oic.size_lines.select_related("size").all()]

    class Meta:
        model = CuttingOrder
        fields = [
            "id", "cutting_number", "order", "order_number", "order_type", "party_name",
            "cutting_instruction", "order_remarks", "order_item", "product", "product_name", "product_code",
            "fabric_issued", "fabric_type_name", "color", "color_name",
            "fabric_issued_quantity", "fabric_used_quantity", "wastage_quantity",
            "total_pieces_cut", "actual_average", "approved_average", "average_status",
            "average_override_approved", "average_override_by", "average_override_at", "average_override_remarks",
            "returned_quantity", "returned_at", "returned_by", "remaining_quantity",
            "received_at", "received_by", "marker", "marker_number", "ratio_sets_cut",
            "layer_length", "no_of_layers", "ratio", "quantity_display", "bundle_count",
            "unsent_bundle_count", "half_roll", "status",
            "cutting_date", "supervisor", "remarks", "created_at", "updated_at",
        ]
        read_only_fields = [
            "cutting_number", "order_item", "fabric_used_quantity", "total_pieces_cut", "actual_average",
            "average_status", "average_override_approved", "average_override_by", "average_override_at",
            "average_override_remarks", "returned_quantity", "returned_at", "returned_by",
            "received_at", "received_by", "marker", "ratio_sets_cut", "layer_length", "no_of_layers", "status",
        ]

    def validate(self, attrs):
        fabric_stock = attrs.get("fabric_issued", getattr(self.instance, "fabric_issued", None))
        qty = attrs.get("fabric_issued_quantity", getattr(self.instance, "fabric_issued_quantity", 0))
        if self.instance is None and fabric_stock and qty > fabric_stock.available_quantity:
            raise serializers.ValidationError(
                f"Insufficient fabric stock. Available: {fabric_stock.available_quantity} {fabric_stock.unit}."
            )
        return attrs

    def create(self, validated_data):
        with db_transaction.atomic():
            cutting_order = CuttingOrder.objects.create(**validated_data)
            # Issuing fabric to cutting reduces store stock via the standard ledger.
            StockTransaction.objects.create(
                fabric_stock=cutting_order.fabric_issued,
                transaction_type=StockTransaction.TransactionType.ISSUE,
                quantity=cutting_order.fabric_issued_quantity,
                reference=cutting_order.cutting_number,
                remarks=f"Issued to cutting order {cutting_order.cutting_number}",
                created_by=self.context["request"].user,
            )
            stock = cutting_order.fabric_issued
            stock.available_quantity -= cutting_order.fabric_issued_quantity
            stock.save(update_fields=["available_quantity", "updated_at"])
            cutting_order.status = CuttingOrder.Status.FABRIC_ISSUED

            # Auto-derive which OrderItem this fabric is meant for, from the
            # roll's OrderItemColor link -- avoids relying on whoever issues
            # the fabric to correctly hand-pick the item themselves.
            if cutting_order.order_id and not cutting_order.order_item_id:
                item_ids = list(
                    OrderItemColor.objects.filter(
                        rolls=cutting_order.fabric_issued, order_item__order_id=cutting_order.order_id,
                    ).values_list("order_item_id", flat=True).distinct()
                )
                if not item_ids:
                    # "Rolls to be Used" is optional for FIXED_QUANTITY
                    # orders, so there's often no roll link to go on -- fall
                    # back to matching this order's item by fabric_type+color
                    # directly (still only used when it's unambiguous).
                    item_ids = list(
                        OrderItemColor.objects.filter(
                            color=cutting_order.fabric_issued.color,
                            order_item__order_id=cutting_order.order_id,
                            order_item__fabric_type=cutting_order.fabric_issued.fabric_type,
                        ).values_list("order_item_id", flat=True).distinct()
                    )
                if len(item_ids) == 1:
                    cutting_order.order_item_id = item_ids[0]

            cutting_order.save(update_fields=["status", "order_item"])
            if cutting_order.order:
                cutting_order.order.advance_status(cutting_order.order.Status.IN_CUTTING)
        return cutting_order


class CuttingPieceSerializer(serializers.ModelSerializer):
    color_name = serializers.CharField(source="color.name", read_only=True)
    size_name = serializers.CharField(source="size.name", read_only=True)
    component_name = serializers.CharField(source="component.name", read_only=True, default=None)

    class Meta:
        model = CuttingPiece
        fields = ["id", "cutting_order", "color", "color_name", "size", "size_name", "component", "component_name", "quantity", "created_at"]


class BundleSerializer(serializers.ModelSerializer):
    color_name = serializers.CharField(source="color.name", read_only=True)
    size_name = serializers.CharField(source="size.name", read_only=True)
    order = serializers.IntegerField(source="cutting_order.order_id", read_only=True, default=None)
    order_number = serializers.CharField(source="cutting_order.order.order_number", read_only=True, default=None)
    cutting_number = serializers.CharField(source="cutting_order.cutting_number", read_only=True, default=None)
    product = serializers.IntegerField(source="cutting_order.order_item.product_id", read_only=True, default=None)
    product_code = serializers.CharField(source="cutting_order.order_item.product.code", read_only=True, default=None)
    product_name = serializers.CharField(source="cutting_order.order_item.product.name", read_only=True, default=None)

    class Meta:
        model = Bundle
        fields = [
            "id", "bundle_number", "cutting_order", "cutting_number", "order", "order_number", "color", "color_name",
            "size", "size_name", "product", "product_code", "product_name", "quantity", "status",
            "sent_to_production_at", "sent_by", "created_at", "updated_at",
        ]
        read_only_fields = ["bundle_number", "sent_to_production_at", "sent_by"]

    def validate(self, attrs):
        cutting_order = attrs.get("cutting_order", getattr(self.instance, "cutting_order", None))
        color = attrs.get("color", getattr(self.instance, "color", None))
        size = attrs.get("size", getattr(self.instance, "size", None))
        quantity = attrs.get("quantity", getattr(self.instance, "quantity", None))
        if not (cutting_order and color and size and quantity):
            return attrs
        if not cutting_order.order_item_id:
            return attrs  # nothing to validate a component/order cap against

        already_bundled_qs = Bundle.objects.filter(cutting_order=cutting_order, color=color, size=size)
        if self.instance is not None:
            already_bundled_qs = already_bundled_qs.exclude(pk=self.instance.pk)
        already_bundled = already_bundled_qs.aggregate(q=Sum("quantity"))["q"] or 0

        product = cutting_order.order_item.product
        components = list(product.components.filter(is_active=True))
        if components:
            for component in components:
                piece = CuttingPiece.objects.filter(cutting_order=cutting_order, color=color, size=size, component=component).first()
                cut_qty = piece.quantity if piece else 0
                available = cut_qty - already_bundled
                if available < quantity:
                    raise serializers.ValidationError(
                        f"Not enough '{component.name}' pieces cut for this bundle. Available: {available}, requested: {quantity}."
                    )
        else:
            piece = CuttingPiece.objects.filter(cutting_order=cutting_order, color=color, size=size, component__isnull=True).first()
            cut_qty = piece.quantity if piece else 0
            available = cut_qty - already_bundled
            if available < quantity:
                raise serializers.ValidationError(
                    f"Not enough pieces cut for this bundle. Available: {available}, requested: {quantity}."
                )
        return attrs
