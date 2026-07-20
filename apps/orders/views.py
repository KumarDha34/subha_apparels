from django.db.models import Sum
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.users.permissions import ReadOnlyOrHasRole
from .models import Order, OrderItemColorSize
from .serializers import OrderSerializer


def compute_order_loss(order):
    """Where an order's pieces were lost, phase by phase:
       Cutting (ordered vs bundled) -> Production (per operator: issued vs
       returned) -> Finishing (per operation: washing/printing/… rejects, plus
       final QC). All computed live from the source records."""
    from apps.operators.models import BundleAssignment
    from apps.cutting.models import Bundle, CuttingOrder
    from apps.finishing.models import FinishingReceipt, FinishingQualityCheck, Dispatch
    from apps.production.models import ProcessDispatch

    DONE = [BundleAssignment.Status.COMPLETED, BundleAssignment.Status.QUALITY_CHECKED]

    # ---- Cutting ----
    # Cutting "loss" (ordered but never bundled) is only meaningful once
    # cutting is finished -- i.e. the order has moved on to Production or
    # beyond. Before that, unbundled pieces are simply not-yet-cut, not lost.
    seq = Order.STATUS_SEQUENCE
    reached = seq.index(order.status) if order.status in seq else -1
    past_cutting = reached >= seq.index(Order.Status.IN_PRODUCTION)

    ordered = None
    if order.order_type == Order.OrderType.FIXED_QUANTITY:
        ordered = OrderItemColorSize.objects.filter(
            order_item_color__order_item__order=order).aggregate(s=Sum("quantity"))["s"] or 0
    bundled = Bundle.objects.filter(cutting_order__order=order).aggregate(s=Sum("quantity"))["s"] or 0
    fabric_wastage = float(CuttingOrder.objects.filter(order=order).aggregate(w=Sum("wastage_quantity"))["w"] or 0)
    cutting_lost = max(ordered - bundled, 0) if (ordered is not None and past_cutting) else None

    # ---- Production (per operator) ----
    accepted = BundleAssignment.objects.filter(bundle__cutting_order__order=order, status__in=DONE)
    prod_issued = accepted.aggregate(s=Sum("issued_quantity"))["s"] or 0
    prod_returned = accepted.aggregate(s=Sum("returned_quantity"))["s"] or 0
    prod_defects = accepted.aggregate(s=Sum("defects"))["s"] or 0
    production_lost = max(prod_issued - prod_returned, 0)
    by_operator = []
    for row in (accepted.values("operator__name")
                .annotate(issued=Sum("issued_quantity"), returned=Sum("returned_quantity"), defects=Sum("defects"))
                .order_by("operator__name")):
        iss = row["issued"] or 0
        ret = row["returned"] or 0
        by_operator.append({
            "operator": row["operator__name"], "issued": iss, "returned": ret,
            "lost": max(iss - ret, 0), "defects": row["defects"] or 0,
        })

    # ---- Finishing / external processing (Washing / Printing / … ) ----
    received = FinishingReceipt.objects.filter(order=order).aggregate(s=Sum("quantity_sent"))["s"] or 0
    by_operation = []
    process_loss = 0
    for pd in (ProcessDispatch.objects.filter(order=order).order_by("department", "created_at")):
        loss = pd.loss_quantity
        process_loss += loss
        by_operation.append({
            "operation": pd.get_department_display(), "quantity": pd.quantity_sent,
            "received": pd.quantity_received, "rejected": loss,
        })
    final_qc_rejected = FinishingQualityCheck.objects.filter(order=order).aggregate(s=Sum("quantity_rejected"))["s"] or 0
    finishing_lost = process_loss + final_qc_rejected

    dispatch = Dispatch.objects.filter(order=order).first()
    dispatched = dispatch.quantity_dispatched if (dispatch and dispatch.quantity_dispatched) else None
    good_pieces = dispatched if dispatched is not None else max(prod_returned - finishing_lost, 0)
    total_lost = (cutting_lost or 0) + production_lost + finishing_lost

    return {
        "order": order.id, "order_number": order.order_number,
        "party_name": order.party.name if order.party_id else "",
        "status": order.status, "order_type": order.order_type,
        "ordered_pieces": ordered,
        "fabric_wastage_m": fabric_wastage,
        "cutting": {"ordered": ordered, "bundled": bundled, "lost": cutting_lost},
        "production": {
            "issued": prod_issued, "returned": prod_returned, "lost": production_lost,
            "defects": prod_defects, "by_operator": by_operator,
        },
        "finishing": {
            "received": received, "by_operation": by_operation,
            "final_qc_rejected": final_qc_rejected, "lost": finishing_lost,
        },
        "total_lost": total_lost, "good_pieces": good_pieces,
    }


class OrderViewSet(viewsets.ModelViewSet):
    """Merchandise creates & manages orders; everyone downstream reads them."""
    queryset = (
        Order.objects.select_related("party")
        .prefetch_related(
            "items__product", "items__fabric_type",
            "items__colors__color", "items__colors__rolls",
            "items__colors__size_lines__size",
        )
        .all()
    )
    serializer_class = OrderSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "MERCHANDISE"]
    filterset_fields = ["status", "order_type", "party", "is_repeat"]
    search_fields = ["order_number", "party__name"]

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        order = self.get_object()
        if order.status != Order.Status.DRAFT:
            return Response({"detail": "Only DRAFT orders can be confirmed."}, status=400)
        order.status = Order.Status.CONFIRMED
        order.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        if order.status == Order.Status.CANCELLED:
            return Response({"detail": "Order is already cancelled."}, status=400)
        order.status = Order.Status.CANCELLED
        order.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["get"], url_path="loss-breakdown")
    def loss_breakdown(self, request, pk=None):
        """Full per-phase piece-loss breakdown for one order — cutting,
        production (per operator), and finishing (per washing/printing/etc.)."""
        return Response(compute_order_loss(self.get_object()))

    @action(detail=False, methods=["get"], url_path="loss-summary")
    def loss_summary(self, request):
        """One row per (non-cancelled) order with the loss at each phase —
        powers the admin dashboard's piece-loss table."""
        rows = []
        for order in self.get_queryset().exclude(status=Order.Status.CANCELLED):
            d = compute_order_loss(order)
            rows.append({
                "order": d["order"], "order_number": d["order_number"], "party_name": d["party_name"],
                "status": d["status"], "ordered_pieces": d["ordered_pieces"],
                "cutting_lost": d["cutting"]["lost"], "production_lost": d["production"]["lost"],
                "production_defects": d["production"]["defects"], "finishing_lost": d["finishing"]["lost"],
                "total_lost": d["total_lost"], "good_pieces": d["good_pieces"],
            })
        return Response(rows)

    @action(detail=True, methods=["get"])
    def traceability(self, request, pk=None):
        """The full quantity waterfall for this order, computed live (no
        denormalized storage): given to operators -> returned -> lost ->
        sent to finishing -> finishing completed/rejected -> dispatched."""
        from apps.operators.models import BundleAssignment
        from apps.finishing.models import FinishingReceipt, FinishingOperation, FinishingQualityCheck, Dispatch

        order = self.get_object()
        assignments = BundleAssignment.objects.filter(bundle__cutting_order__order=order)
        rejected = assignments.filter(shortage_reason_status=BundleAssignment.ShortageStatus.REJECTED)
        pieces_issued = assignments.aggregate(p=Sum("issued_quantity"))["p"] or 0
        pieces_returned = assignments.aggregate(p=Sum("returned_quantity"))["p"] or 0
        pieces_lost = (
            (rejected.aggregate(i=Sum("issued_quantity"))["i"] or 0)
            - (rejected.aggregate(r=Sum("returned_quantity"))["r"] or 0)
        )
        sent_to_finishing = FinishingReceipt.objects.filter(order=order).aggregate(q=Sum("quantity_sent"))["q"] or 0
        finishing_completed = (
            FinishingOperation.objects.filter(order=order, status=FinishingOperation.Status.COMPLETED)
            .aggregate(q=Sum("quantity"))["q"] or 0
        )
        finishing_rejected = (
            FinishingQualityCheck.objects.filter(order=order).aggregate(q=Sum("quantity_rejected"))["q"] or 0
        )
        dispatch = Dispatch.objects.filter(order=order).first()
        dispatched = dispatch.quantity_dispatched if dispatch and dispatch.quantity_dispatched else 0

        return Response({
            "order_number": order.order_number,
            "pieces_issued_to_operators": pieces_issued,
            "pieces_returned": pieces_returned,
            "pieces_lost": pieces_lost,
            "pieces_sent_to_finishing": sent_to_finishing,
            "pieces_finishing_completed": finishing_completed,
            "pieces_finishing_rejected": finishing_rejected,
            "pieces_dispatched": dispatched,
        })
