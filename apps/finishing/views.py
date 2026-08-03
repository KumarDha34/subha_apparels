from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.users.permissions import ReadOnlyOrHasRole
from .models import FinishingQualityCheck, Packing, Dispatch, FinishingOperation, FinishingReceipt, ReworkAssignment
from .serializers import (
    FinishingQualityCheckSerializer, PackingSerializer, DispatchSerializer,
    FinishingOperationSerializer, FinishingReceiptSerializer, ReworkAssignmentSerializer,
)


class FinishingQualityCheckViewSet(viewsets.ModelViewSet):
    queryset = FinishingQualityCheck.objects.select_related("order", "checked_by").all().order_by("-created_at")
    serializer_class = FinishingQualityCheckSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "FINISHING_SUPERVISOR"]
    filterset_fields = ["order"]

    def get_permissions(self):
        # Altered pieces are reworked on the Production floor, so a Production
        # Supervisor is also allowed to record the rework outcome.
        if getattr(self, "action", None) == "record_rework":
            self.required_roles = ["ADMIN", "FINISHING_SUPERVISOR", "PRODUCTION_SUPERVISOR"]
        return super().get_permissions()

    @action(detail=False, methods=["get"])
    def breakdown(self, request):
        """Size/colour breakdown for the QC grid, reconciled to what Finishing
        actually received. Query: ?order=<id>. If pieces were lost in a process
        (e.g. washing 723 -> 720), the breakdown is capped at the received 720
        so QC works on the pieces physically in hand, not the produced total.
        Returns total (received), produced, process_loss, by_size, by_color, grid."""
        from apps.operators.services import order_piece_breakdown
        from apps.production.models import ProcessDispatch
        order_id = request.query_params.get("order")
        cap = None
        if order_id:
            fin = (ProcessDispatch.objects
                   .filter(order_id=order_id, department=ProcessDispatch.Department.FINISHING,
                           status=ProcessDispatch.Status.RECEIVED, quantity_received__isnull=False)
                   .order_by("-received_date", "-id").first())
            if fin is not None:
                cap = fin.quantity_received
        return Response(order_piece_breakdown(order_id, cap_total=cap))

    @action(detail=True, methods=["post"])
    def record_rework(self, request, pk=None):
        """Close the alteration loop: of the pieces sent for alteration, record
        how many passed re-inspection after rework and how many were scrapped.
        Body: {passed, failed}. Can be called repeatedly until every altered
        piece is accounted for."""
        qc = self.get_object()
        try:
            passed = int(request.data.get("passed") or 0)
            failed = int(request.data.get("failed") or 0)
        except (TypeError, ValueError):
            return Response({"detail": "passed and failed must be numbers."}, status=400)
        if passed < 0 or failed < 0:
            return Response({"detail": "passed and failed can't be negative."}, status=400)
        if passed + failed > qc.alteration_pending:
            return Response({"detail": f"Only {qc.alteration_pending} altered piece(s) are still pending rework."}, status=400)
        qc.quantity_reworked_passed += passed
        qc.quantity_reworked_failed += failed
        qc.save(update_fields=["quantity_reworked_passed", "quantity_reworked_failed", "updated_at"])
        return Response(self.get_serializer(qc).data)


class ReworkAssignmentViewSet(viewsets.ModelViewSet):
    """The Production-side rework loop: allocate altered pieces to an operator
    at a rate/piece, then record completion when the operator returns them."""
    queryset = ReworkAssignment.objects.select_related(
        "qc__order", "qc__color", "qc__size", "operator", "allocated_by").all().order_by("-created_at")
    serializer_class = ReworkAssignmentSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "PRODUCTION_SUPERVISOR"]
    filterset_fields = ["qc", "operator", "status", "qc__order"]

    def get_permissions(self):
        # Accounts pays operators, so it may record a rework payment.
        if getattr(self, "action", None) == "pay":
            self.required_roles = ["ADMIN", "ACCOUNTS", "PRODUCTION_SUPERVISOR"]
        return super().get_permissions()

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """Operator has reworked the pieces and handed them back to Finishing.
        Body: {returned_quantity}. The pieces now await a second QC. Defaults to
        the full allocated quantity."""
        ra = self.get_object()
        if ra.status == ReworkAssignment.Status.COMPLETED:
            return Response({"detail": "This rework task is already completed."}, status=400)
        qty = request.data.get("returned_quantity")
        qty = ra.quantity if qty is None else int(qty)
        if qty <= 0 or qty > ra.quantity:
            return Response({"detail": f"returned_quantity must be between 1 and {ra.quantity} (allocated)."}, status=400)
        ra.returned_quantity = qty
        ra.status = ReworkAssignment.Status.COMPLETED
        ra.completed_at = timezone.now()
        ra.save(update_fields=["returned_quantity", "status", "completed_at", "updated_at"])
        return Response(self.get_serializer(ra).data)

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        """Record a rework payment to the operator. Body: {quantity?} (defaults
        to all still-unpaid returned pieces)."""
        ra = self.get_object()
        if ra.status != ReworkAssignment.Status.COMPLETED:
            return Response({"detail": "Rework must be completed before it can be paid."}, status=400)
        pending = ra.pending_pay_quantity
        qty = request.data.get("quantity")
        qty = pending if qty is None else int(qty)
        if qty <= 0 or qty > pending:
            return Response({"detail": f"quantity must be between 1 and {pending} (unpaid returned pieces)."}, status=400)
        ra.paid_quantity += qty
        ra.save(update_fields=["paid_quantity", "updated_at"])
        return Response(self.get_serializer(ra).data)


class PackingViewSet(viewsets.ModelViewSet):
    queryset = Packing.objects.select_related("order", "packed_by").all().order_by("-created_at")
    serializer_class = PackingSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "FINISHING_SUPERVISOR"]
    filterset_fields = ["order"]


class DispatchViewSet(viewsets.ModelViewSet):
    queryset = Dispatch.objects.select_related("order", "dispatched_by").all().order_by("-created_at")
    serializer_class = DispatchSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "FINISHING_SUPERVISOR"]
    filterset_fields = ["status", "order"]

    @action(detail=False, methods=["get"])
    def availability(self, request):
        """GET ?order=<id>. What's available to dispatch RIGHT NOW, by size and
        by colour: QC-passed minus already-dispatched. The dispatch form uses
        this to auto-fill and to validate live as the user types."""
        from apps.orders.models import Order
        order = Order.objects.filter(pk=request.query_params.get("order")).first()
        if not order:
            return Response({"detail": "Order not found."}, status=404)
        avail = DispatchSerializer.available_by_dimension(order)
        total_available, final_good, already = DispatchSerializer.available_to_dispatch(order)
        return Response({
            "order_number": order.order_number,
            "total_available": total_available, "final_good": final_good, "already_dispatched": already,
            **avail,
        })


class FinishingOperationViewSet(viewsets.ModelViewSet):
    queryset = FinishingOperation.objects.select_related("order", "vendor", "recorded_by").all().order_by("-created_at")
    serializer_class = FinishingOperationSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "FINISHING_SUPERVISOR"]
    filterset_fields = ["order", "operation_type", "status", "is_outsourced"]


class FinishingReceiptViewSet(viewsets.ModelViewSet):
    """Read-only from Finishing's side -- Production creates these via its
    own send-to-finishing action (apps.production), Finishing just sees them."""
    queryset = FinishingReceipt.objects.select_related("order", "sent_by").all().order_by("-created_at")
    serializer_class = FinishingReceiptSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "PRODUCTION_SUPERVISOR"]
    filterset_fields = ["order"]
