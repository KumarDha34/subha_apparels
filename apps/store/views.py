from decimal import Decimal, InvalidOperation
from django.db import transaction as db_transaction
from django.db.models import Sum, Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from apps.users.permissions import ReadOnlyOrHasRole


def movement_annotations(rel="transactions"):
    """Per-stock lifetime totals by movement type, so every stock row shows
    actual received, issued, returned and wastage alongside its live balance."""
    def _sum(kind):
        return Sum(f"{rel}__quantity", filter=Q(**{f"{rel}__transaction_type": kind}))
    return {
        "total_received": _sum("RECEIPT"), "total_issued": _sum("ISSUE"),
        "total_returned": _sum("RETURN"), "total_wastage": _sum("WASTAGE"),
    }
from .models import FabricStock, StockTransaction, AccessoryStock, AccessoryStockTransaction, FinishedGoodsReceipt, OrderAdditionalCharge
from .serializers import (
    FabricStockSerializer, StockTransactionSerializer,
    AccessoryStockSerializer, AccessoryStockTransactionSerializer, FinishedGoodsReceiptSerializer,
    OrderAdditionalChargeSerializer,
)


class OrderAdditionalChargeViewSet(viewsets.ModelViewSet):
    """Extra, non-material order costs (transport, courier, customs, storage,
    sample, testing, penalties, handling). Centralised in Accounts for proper
    financial control -- only Accounts (and Admin) may book them."""
    queryset = OrderAdditionalCharge.objects.select_related("order__party").all()
    serializer_class = OrderAdditionalChargeSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "ACCOUNTS"]
    filterset_fields = ["order", "charge_type"]
    search_fields = ["order__order_number"]


class FinishedGoodsReceiptViewSet(viewsets.ModelViewSet):
    """Store's finished-goods register. Rows are usually created automatically
    when Finishing dispatches an order, but Store can also add/adjust manually."""
    queryset = FinishedGoodsReceipt.objects.select_related("order__party", "received_by").all().order_by("-created_at")
    serializer_class = FinishedGoodsReceiptSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "STORE_MANAGER"]
    filterset_fields = ["order"]
    search_fields = ["order__order_number", "dispatch_reference"]


class FabricStockViewSet(viewsets.ModelViewSet):
    """Current fabric stock. Balances only change through StockTransaction,
    never by editing available_quantity directly."""
    queryset = FabricStock.objects.select_related("fabric_type", "color", "vendor", "supplied_by_party").annotate(**movement_annotations()).order_by("-id")
    serializer_class = FabricStockSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "STORE_MANAGER", "MERCHANDISE"]
    search_fields = ["fabric_type__name", "color__name", "roll_number"]
    filterset_fields = ["fabric_type", "color", "is_active"]

    @action(detail=False, methods=["get"])
    def low_stock(self, request):
        """Out-of-stock items (nothing left) - for restock alerts."""
        qs = self.get_queryset().filter(available_quantity__lte=0, is_active=True)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["post"])
    def add_rolls(self, request):
        """Add fabric held as MULTIPLE separate rolls of the same fabric+colour
        -- e.g. a customer supplies 110m of Black in 5 rolls. Each roll becomes
        its own stock row (its own metres/kg + roll number), so Cutting can
        pick, use and return rolls individually. Body:
        {fabric_type, color, unit?, vendor?, supplied_by_party?, reorder_level?,
         rolls:[{roll_number?, quantity}]}."""
        if not (request.user.is_superuser or request.user.role in ("ADMIN", "STORE_MANAGER")):
            raise PermissionDenied("Only Store can add fabric rolls.")
        d = request.data
        if not d.get("fabric_type") or not d.get("color"):
            return Response({"detail": "fabric_type and color are required."}, status=400)
        rolls = d.get("rolls") or []
        try:
            parsed = [{"roll_number": (r.get("roll_number") or "").strip(), "quantity": Decimal(str(r.get("quantity")))}
                      for r in rolls if str(r.get("quantity") or "").strip()]
        except (InvalidOperation, TypeError):
            return Response({"detail": "Every roll needs a valid quantity."}, status=400)
        parsed = [r for r in parsed if r["quantity"] > 0]
        if not parsed:
            return Response({"detail": "Add at least one roll with a quantity greater than 0."}, status=400)

        created = []
        with db_transaction.atomic():
            for i, r in enumerate(parsed, start=1):
                stock = FabricStock.objects.create(
                    fabric_type_id=d["fabric_type"], color_id=d["color"],
                    unit=d.get("unit") or "METERS", roll_number=r["roll_number"] or f"R{i}",
                    vendor_id=d.get("vendor") or None, supplied_by_party_id=d.get("supplied_by_party") or None,
                    reorder_level=Decimal(str(d.get("reorder_level") or 0)),
                )
                StockTransaction.objects.create(
                    fabric_stock=stock, transaction_type=StockTransaction.TransactionType.RECEIPT,
                    quantity=r["quantity"], reference=r["roll_number"] or f"R{i}",
                    remarks="Roll received into stock", created_by=request.user)
                stock.available_quantity = r["quantity"]
                stock.save(update_fields=["available_quantity", "updated_at"])
                created.append(stock)
        return Response(FabricStockSerializer(created, many=True).data, status=201)


class StockTransactionViewSet(viewsets.ModelViewSet):
    """
    Ledger of stock movement (receipt/issue/wastage/return/adjustment).
    Creating a transaction here atomically updates FabricStock.available_quantity.
    """
    queryset = StockTransaction.objects.select_related("fabric_stock", "created_by").all().order_by("-created_at")
    serializer_class = StockTransactionSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "STORE_MANAGER", "CUTTING_SUPERVISOR"]
    filterset_fields = ["transaction_type", "fabric_stock"]
    search_fields = ["reference", "remarks"]

    def perform_create(self, serializer):
        with db_transaction.atomic():
            serializer.save()


class AccessoryStockViewSet(viewsets.ModelViewSet):
    """Current accessory stock. Mirrors FabricStockViewSet exactly."""
    queryset = AccessoryStock.objects.select_related("accessory", "accessory__color", "vendor", "supplied_by_party").annotate(**movement_annotations()).order_by("-id")
    serializer_class = AccessoryStockSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "STORE_MANAGER", "MERCHANDISE"]
    search_fields = ["accessory__name"]
    filterset_fields = ["accessory", "is_active"]

    @action(detail=False, methods=["get"])
    def low_stock(self, request):
        qs = self.get_queryset().filter(available_quantity__lte=0, is_active=True)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["post"])
    def add_stock(self, request):
        """Receive accessory stock into Store -- e.g. a customer supplies
        5,000 buttons or 40 cones of thread. Creates the AccessoryStock row if
        needed and logs a RECEIPT so received / issued / available stay
        traceable, exactly like fabric. Body:
        {accessory, quantity, supplied_by_party?, vendor?, reorder_level?, remarks?}."""
        if not (request.user.is_superuser or request.user.role in ("ADMIN", "STORE_MANAGER")):
            raise PermissionDenied("Only Store can add accessory stock.")
        d = request.data
        if not d.get("accessory"):
            return Response({"detail": "accessory is required."}, status=400)
        try:
            quantity = Decimal(str(d.get("quantity")))
        except (InvalidOperation, TypeError):
            return Response({"detail": "A valid quantity is required."}, status=400)
        if quantity <= 0:
            return Response({"detail": "Quantity must be greater than 0."}, status=400)

        with db_transaction.atomic():
            stock, _ = AccessoryStock.objects.get_or_create(
                accessory_id=d["accessory"],
                defaults={"available_quantity": Decimal("0")},
            )
            if d.get("supplied_by_party"):
                stock.supplied_by_party_id = d["supplied_by_party"]
            if d.get("vendor"):
                stock.vendor_id = d["vendor"]
            if d.get("reorder_level") not in (None, ""):
                stock.reorder_level = Decimal(str(d["reorder_level"]))
            AccessoryStockTransaction.objects.create(
                accessory_stock=stock, transaction_type=AccessoryStockTransaction.TransactionType.RECEIPT,
                quantity=quantity, reference=d.get("remarks") or "Received into stock",
                remarks=d.get("remarks") or "Accessory received into stock", created_by=request.user)
            stock.available_quantity += quantity
            stock.save()
        # Re-fetch with the movement annotations so the response carries totals.
        stock = self.get_queryset().get(pk=stock.pk)
        return Response(self.get_serializer(stock).data, status=201)


class AccessoryStockTransactionViewSet(viewsets.ModelViewSet):
    """Ledger of accessory stock movement. Mirrors StockTransactionViewSet."""
    queryset = AccessoryStockTransaction.objects.select_related("accessory_stock", "created_by").all().order_by("-created_at")
    serializer_class = AccessoryStockTransactionSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "STORE_MANAGER", "CUTTING_SUPERVISOR"]
    filterset_fields = ["transaction_type", "accessory_stock"]
    search_fields = ["reference", "remarks"]

    def perform_create(self, serializer):
        with db_transaction.atomic():
            serializer.save()
