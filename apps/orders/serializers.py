from django.db import transaction
from rest_framework import serializers
from apps.store.serializers import FabricStockSerializer
from .models import Order, OrderItem, OrderItemColor, OrderItemColorSize


class OrderItemColorSizeSerializer(serializers.ModelSerializer):
    size_name = serializers.CharField(source="size.name", read_only=True)

    class Meta:
        model = OrderItemColorSize
        fields = ["id", "size", "size_name", "quantity", "ratio_part"]


class OrderItemColorSerializer(serializers.ModelSerializer):
    color_name = serializers.CharField(source="color.name", read_only=True)
    color_hex = serializers.CharField(source="color.hex_code", read_only=True)
    rolls_detail = FabricStockSerializer(source="rolls", many=True, read_only=True)
    size_lines = OrderItemColorSizeSerializer(many=True)

    class Meta:
        model = OrderItemColor
        fields = ["id", "color", "color_name", "color_hex", "rolls", "rolls_detail", "half_roll", "size_lines"]


class OrderItemSerializer(serializers.ModelSerializer):
    product_code = serializers.CharField(source="product.code", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    fabric_type_name = serializers.CharField(source="fabric_type.name", read_only=True)
    colors = OrderItemColorSerializer(many=True)

    class Meta:
        model = OrderItem
        fields = [
            "id", "product", "product_code", "product_name", "fabric_type", "fabric_type_name",
            "approved_average", "price_per_piece", "inner_required", "fusing_required", "resting_needed", "colors",
        ]


class OrderSerializer(serializers.ModelSerializer):
    party_name = serializers.CharField(source="party.name", read_only=True)
    items = OrderItemSerializer(many=True)

    class Meta:
        model = Order
        fields = [
            "id", "order_number", "party", "party_name", "order_date", "order_type",
            "is_repeat", "remarks", "cutting_instruction", "total_order_amount", "status", "created_by",
            "items", "created_at", "updated_at",
        ]
        read_only_fields = ["order_number", "created_by", "status", "total_order_amount"]

    def validate(self, attrs):
        order_type = attrs.get("order_type", getattr(self.instance, "order_type", None))
        party = attrs.get("party", getattr(self.instance, "party", None))
        items = attrs.get("items")
        if not items:
            raise serializers.ValidationError({"items": "At least one product item is required."})
        seen_rolls = {}  # roll_id -> True, to catch the same roll picked twice in this order
        for item in items:
            colors = item.get("colors") or []
            if not colors:
                raise serializers.ValidationError({"items": "Each product item needs at least one color."})
            for color in colors:
                lines = color.get("size_lines") or []
                if not lines:
                    raise serializers.ValidationError({"items": "Each color needs at least one size row."})
                if order_type == Order.OrderType.RATIO_BASED and not color.get("rolls"):
                    raise serializers.ValidationError({"items": "Each color needs at least one roll for RATIO_BASED orders."})
                for roll in color.get("rolls") or []:
                    # Rule 1: customer-supplied rolls are earmarked for that
                    # customer's own order(s) -- not spendable on another party's.
                    if roll.supplied_by_party_id and party and roll.supplied_by_party_id != party.id:
                        raise serializers.ValidationError({
                            "items": f"Roll {roll.roll_number or roll.id} is customer-supplied material belonging to "
                                     f"{roll.supplied_by_party.name}, not {party.name if party else '?'} — it can't be used on this order."
                        })
                    # Rule 2a: a roll can't be picked twice within the same order.
                    if roll.id in seen_rolls:
                        raise serializers.ValidationError({
                            "items": f"Roll {roll.roll_number or roll.id} is selected more than once in this order."})
                    seen_rolls[roll.id] = True
                    # Rule 2b: a customer-supplied roll is a single physical
                    # package -- once committed to an active (non-cancelled)
                    # order it can't back another. General vendor stock is a
                    # shared running-balance row, so this only applies to
                    # customer-supplied rolls.
                    if roll.supplied_by_party_id:
                        other = OrderItemColor.objects.filter(rolls=roll).exclude(
                            order_item__order__status=Order.Status.CANCELLED)
                        if self.instance is not None:
                            other = other.exclude(order_item__order=self.instance)
                        other = other.select_related("order_item__order").first()
                        if other is not None:
                            raise serializers.ValidationError({
                                "items": f"Roll {roll.roll_number or roll.id} is already assigned to order "
                                         f"{other.order_item.order.order_number} — it can't be used on two orders at once."})
                for line in lines:
                    qty, ratio = line.get("quantity"), line.get("ratio_part")
                    if order_type == Order.OrderType.FIXED_QUANTITY:
                        if not qty:
                            raise serializers.ValidationError({"items": "Quantity is required on every size row for FIXED_QUANTITY orders."})
                        if ratio:
                            raise serializers.ValidationError({"items": "Ratio must be empty for FIXED_QUANTITY orders."})
                    else:
                        if not ratio:
                            raise serializers.ValidationError({"items": "Ratio is required on every size row for RATIO_BASED orders."})
                        if qty:
                            raise serializers.ValidationError({"items": "Quantity must be empty for RATIO_BASED orders."})
        return attrs

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return self._save(Order(), validated_data, is_new=True)

    def update(self, instance, validated_data):
        if instance.status != Order.Status.DRAFT:
            raise serializers.ValidationError("Only DRAFT orders can be edited. Use the confirm/cancel actions instead.")
        return self._save(instance, validated_data)

    def _save(self, order, validated_data, is_new=False):
        items_data = validated_data.pop("items")
        with transaction.atomic():
            for k, v in validated_data.items():
                setattr(order, k, v)
            order.save()
            if not is_new:
                order.items.all().delete()  # cascades to colors + size_lines
            for item_data in items_data:
                colors_data = item_data.pop("colors")
                item = OrderItem.objects.create(order=order, **item_data)
                for color_data in colors_data:
                    lines_data = color_data.pop("size_lines")
                    rolls = color_data.pop("rolls", [])
                    color = OrderItemColor.objects.create(order_item=item, **color_data)
                    if rolls:
                        color.rolls.set(rolls)
                    OrderItemColorSize.objects.bulk_create(
                        OrderItemColorSize(order_item_color=color, **line) for line in lines_data
                    )
        return order
