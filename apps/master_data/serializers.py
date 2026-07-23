from django.db import transaction
from rest_framework import serializers
from .models import Party, Product, ProductComponent, Color, FabricType, Size, Vendor, Accessory


class PartySerializer(serializers.ModelSerializer):
    class Meta:
        model = Party
        fields = "__all__"


class ProductSerializer(serializers.ModelSerializer):
    fabric_type_names = serializers.SerializerMethodField()
    # Single URL the frontend can show regardless of whether the style has an
    # uploaded file or a legacy link. None when neither is present.
    image_display_url = serializers.SerializerMethodField()
    measurement_chart_display_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = "__all__"
        read_only_fields = ["code"]

    def get_fabric_type_names(self, obj):
        return [ft.name for ft in obj.fabric_types.all()]

    def _abs(self, file_field):
        if not file_field:
            return None
        url = file_field.url
        request = self.context.get("request")
        return request.build_absolute_uri(url) if request else url

    def get_image_display_url(self, obj):
        return self._abs(obj.image) or (obj.image_url or None)

    def get_measurement_chart_display_url(self, obj):
        return self._abs(obj.measurement_chart_file) or (obj.measurement_chart_url or None)


class ProductComponentSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = ProductComponent
        fields = ["id", "product", "product_name", "name", "is_primary", "is_active", "created_at", "updated_at"]

    def create(self, validated_data):
        # is_primary is never client-set at creation -- the first active
        # component for a product always becomes primary automatically.
        validated_data.pop("is_primary", None)
        with transaction.atomic():
            is_first = not ProductComponent.objects.filter(product=validated_data["product"], is_active=True).exists()
            component = ProductComponent.objects.create(**validated_data, is_primary=is_first)
        return component

    def update(self, instance, validated_data):
        with transaction.atomic():
            if validated_data.get("is_primary"):
                ProductComponent.objects.filter(product=instance.product).exclude(pk=instance.pk).update(is_primary=False)
            return super().update(instance, validated_data)


class ColorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Color
        fields = "__all__"


class FabricTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = FabricType
        fields = "__all__"


class SizeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Size
        fields = "__all__"


class VendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = "__all__"


class AccessorySerializer(serializers.ModelSerializer):
    color_name = serializers.CharField(source="color.name", read_only=True, default=None)

    class Meta:
        model = Accessory
        fields = "__all__"
