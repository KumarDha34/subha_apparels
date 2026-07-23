from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.users.permissions import ReadOnlyOrHasRole
from .models import FinishingQualityCheck, Packing, Dispatch, FinishingOperation, FinishingReceipt
from .serializers import (
    FinishingQualityCheckSerializer, PackingSerializer, DispatchSerializer,
    FinishingOperationSerializer, FinishingReceiptSerializer,
)


class FinishingQualityCheckViewSet(viewsets.ModelViewSet):
    queryset = FinishingQualityCheck.objects.select_related("order", "checked_by").all().order_by("-created_at")
    serializer_class = FinishingQualityCheckSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "FINISHING_SUPERVISOR"]
    filterset_fields = ["order"]

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
