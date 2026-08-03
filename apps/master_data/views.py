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

        # ---- Customer-supplied FABRIC tracking (ALL supplied, even unused) ----
        # Supplied (+ the order it was supplied FOR) comes from the customer's
        # own purchase orders, so fabric still sitting in store with zero usage
        # is still shown. Consumption (used/wastage/returned) is layered in from
        # the cutting orders that drew on it. remaining = supplied - the rest.
        from apps.finance.models import PurchaseOrder
        from apps.cutting.models import CuttingOrder

        def _blank(key, unit):
            return {"fabric": key, "unit": unit or "METERS", "supplied": 0.0,
                    "used": 0.0, "wastage": 0.0, "returned": 0.0, "by_order": {}}

        def _bo(entry, order_no):
            return entry["by_order"].setdefault(
                order_no, {"order": order_no, "supplied": 0.0, "used": 0.0, "wastage": 0.0, "returned": 0.0})

        fabric_map = {}
        for po in (PurchaseOrder.objects
                   .filter(party=party, po_type=PurchaseOrder.POType.CUSTOMER_SUPPLIED)
                   .select_related("related_order").prefetch_related("items__fabric_type", "items__color")):
            order_no = po.related_order.order_number if po.related_order_id else "— (unassigned)"
            for it in po.items.all():
                if it.material_type != "FABRIC":
                    continue
                ft = it.fabric_type.name if it.fabric_type_id else "—"
                cl = it.color.name if it.color_id else "—"
                key = f"{ft} / {cl}"
                e = fabric_map.setdefault(key, _blank(key, it.unit))
                if it.unit and e["unit"] == "METERS":
                    e["unit"] = it.unit
                sup = float(it.received_quantity or it.quantity or 0)
                e["supplied"] += sup
                _bo(e, order_no)["supplied"] += sup

        for co in (CuttingOrder.objects.filter(fabric_issued__supplied_by_party=party)
                   .select_related("fabric_issued__fabric_type", "fabric_issued__color", "order")):
            fs = co.fabric_issued
            ft = fs.fabric_type.name if fs and fs.fabric_type_id else "—"
            cl = fs.color.name if fs and fs.color_id else "—"
            key = f"{ft} / {cl}"
            e = fabric_map.setdefault(key, _blank(key, fs.unit if fs else "METERS"))
            used, waste, ret = float(co.fabric_used_quantity or 0), float(co.wastage_quantity or 0), float(co.returned_quantity or 0)
            e["used"] += used; e["wastage"] += waste; e["returned"] += ret
            bo = _bo(e, co.order.order_number if co.order_id else "— (unassigned)")
            bo["used"] += used; bo["wastage"] += waste; bo["returned"] += ret

        def _status(supplied, used, wastage, returned, remaining):
            if used + wastage + returned <= 0.001:
                return "In Stock"
            return "Partial Used" if remaining > 0.001 else "All Used"

        fabric_tracking = []
        for e in fabric_map.values():
            e["remaining"] = round(e["supplied"] - e["used"] - e["wastage"] - e["returned"], 2)
            e["status"] = _status(e["supplied"], e["used"], e["wastage"], e["returned"], e["remaining"])
            for k in ("supplied", "used", "wastage", "returned"):
                e[k] = round(e[k], 2)
            e["by_order"] = sorted(e["by_order"].values(), key=lambda x: x["order"])
            for bo in e["by_order"]:
                for k in ("supplied", "used", "wastage", "returned"):
                    bo[k] = round(bo[k], 2)
                bo["remaining"] = round(bo["supplied"] - bo["used"] - bo["wastage"] - bo["returned"], 2)
            fabric_tracking.append(e)
        fabric_tracking.sort(key=lambda x: x["fabric"])

        # ---- Customer-supplied ACCESSORY tracking (ALL supplied, even unused) ----
        from apps.store.models import AccessoryStock
        accessory_tracking = []
        for a in AccessoryStock.objects.filter(supplied_by_party=party).select_related("accessory"):
            txns = list(a.transactions.all())
            supplied = sum(float(t.quantity) for t in txns if t.transaction_type == "RECEIPT")
            used = sum(float(t.quantity) for t in txns if t.transaction_type == "ISSUE")
            remaining = round(float(a.available_quantity), 2)
            acc = a.accessory
            label = (acc.name if acc else "—")
            if acc and acc.size_spec:
                label += f" ({acc.size_spec})"
            accessory_tracking.append({
                "accessory": label,
                "type": acc.get_accessory_type_display() if acc else "—",
                "unit": (acc.get_unit_display() if acc else ""),
                "supplied": round(supplied, 2), "used": round(used, 2), "remaining": remaining,
                "status": _status(supplied, used, 0, 0, remaining),
            })
        accessory_tracking.sort(key=lambda x: x["accessory"])

        return Response({
            "order_counts": {"total": total_orders, "completed": completed, "cancelled": cancelled, "pending": pending, "by_status": by_status},
            "bundles_total": assignments.values("bundle").distinct().count(),
            "pieces_issued": assignments.aggregate(p=Sum("issued_quantity"))["p"] or 0,
            "pieces_returned": assignments.aggregate(p=Sum("returned_quantity"))["p"] or 0,
            "pieces_lost": pieces_lost,
            "total_defects": assignments.aggregate(d=Sum("defects"))["d"] or 0,
            "operators": operators,
            "fabric_tracking": fabric_tracking,
            "accessory_tracking": accessory_tracking,
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
