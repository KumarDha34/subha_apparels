from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.users.permissions import ReadOnlyOrHasRole
from .models import Party, Product, ProductComponent, Color, FabricType, Size, Vendor, Accessory
from .serializers import (
    PartySerializer, ProductSerializer, ProductComponentSerializer, ColorSerializer,
    FabricTypeSerializer, SizeSerializer, VendorSerializer, AccessorySerializer,
)


class BaseMasterViewSet(viewsets.ModelViewSet):
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "MERCHANDISE", "STORE_MANAGER"]
    search_fields = []
    filterset_fields = ["is_active"]


class PartyViewSet(BaseMasterViewSet):
    queryset = Party.objects.all().order_by("name")
    serializer_class = PartySerializer
    search_fields = ["name", "contact_person", "phone", "email"]

    @action(detail=True, methods=["get"])
    def orders(self, request, pk=None):
        """Full order history for this party -- used by the party detail
        view. Imported locally to avoid a circular import (apps.orders
        imports apps.master_data.models at module load time)."""
        from apps.orders.models import Order
        from apps.orders.serializers import OrderSerializer

        party = self.get_object()
        qs = (
            Order.objects.filter(party=party)
            .select_related("party")
            .prefetch_related(
                "items__product", "items__fabric_type",
                "items__colors__color", "items__colors__rolls",
                "items__colors__size_lines__size",
            )
        )
        return Response(OrderSerializer(qs, many=True).data)

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        """Consolidated customer view: order counts by status, plus
        aggregate bundle/operator/defect/loss stats across every order this
        party has placed -- joins Order->CuttingOrder->Bundle->BundleAssignment,
        all already-existing FKs, no new joins needed."""
        from django.db.models import Sum, Count
        from apps.orders.models import Order
        from apps.operators.models import BundleAssignment

        party = self.get_object()
        orders = Order.objects.filter(party=party)
        by_status = {row["status"]: row["c"] for row in orders.values("status").annotate(c=Count("id"))}
        total_orders = orders.count()
        # "Completed" = the goods have left the floor: dispatched or in financial closure.
        completed = by_status.get("DISPATCHED", 0) + by_status.get("INVOICED", 0) + by_status.get("PAID", 0)
        cancelled = by_status.get("CANCELLED", 0)
        pending = total_orders - completed - cancelled

        assignments = BundleAssignment.objects.filter(bundle__cutting_order__order__party=party)
        rejected = assignments.filter(shortage_reason_status=BundleAssignment.ShortageStatus.REJECTED)
        pieces_lost = (
            (rejected.aggregate(i=Sum("issued_quantity"))["i"] or 0)
            - (rejected.aggregate(r=Sum("returned_quantity"))["r"] or 0)
        )
        operators = list(
            assignments.values("operator_id", "operator__name")
            .annotate(bundles=Count("id"), pieces_issued=Sum("issued_quantity"), pieces_returned=Sum("returned_quantity"))
            .order_by("-bundles")
        )

        return Response({
            "order_counts": {"total": total_orders, "completed": completed, "cancelled": cancelled, "pending": pending, "by_status": by_status},
            "bundles_total": assignments.values("bundle").distinct().count(),
            "pieces_issued": assignments.aggregate(p=Sum("issued_quantity"))["p"] or 0,
            "pieces_returned": assignments.aggregate(p=Sum("returned_quantity"))["p"] or 0,
            "pieces_lost": pieces_lost,
            "total_defects": assignments.aggregate(d=Sum("defects"))["d"] or 0,
            "operators": operators,
        })


class ProductViewSet(BaseMasterViewSet):
    queryset = Product.objects.prefetch_related("fabric_types").all().order_by("code")
    serializer_class = ProductSerializer
    search_fields = ["code", "name", "category", "product_type"]


class ProductComponentViewSet(BaseMasterViewSet):
    queryset = ProductComponent.objects.select_related("product").all().order_by("product__code", "-is_primary", "name")
    serializer_class = ProductComponentSerializer
    required_roles = ["ADMIN", "MERCHANDISE", "CUTTING_SUPERVISOR"]
    search_fields = ["name", "product__name", "product__code"]
    filterset_fields = ["is_active", "product", "is_primary"]


class ColorViewSet(BaseMasterViewSet):
    queryset = Color.objects.all().order_by("name")
    serializer_class = ColorSerializer
    search_fields = ["name"]


class FabricTypeViewSet(BaseMasterViewSet):
    queryset = FabricType.objects.all().order_by("name")
    serializer_class = FabricTypeSerializer
    search_fields = ["name", "composition"]


class SizeViewSet(BaseMasterViewSet):
    queryset = Size.objects.all()
    serializer_class = SizeSerializer
    search_fields = ["name"]


class VendorViewSet(BaseMasterViewSet):
    queryset = Vendor.objects.all().order_by("company_name")
    serializer_class = VendorSerializer
    required_roles = ["ADMIN", "STORE_MANAGER", "ACCOUNTS"]
    search_fields = ["company_name", "contact_person", "phone", "gst_number"]


class AccessoryViewSet(BaseMasterViewSet):
    queryset = Accessory.objects.select_related("color").all().order_by("accessory_type", "name")
    serializer_class = AccessorySerializer
    search_fields = ["name", "accessory_type", "size_spec"]
