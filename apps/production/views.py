from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import viewsets, views, status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.users.permissions import ReadOnlyOrHasRole
from apps.store.models import AccessoryStockTransaction
from apps.orders.models import Order
from apps.finishing.models import FinishingReceipt
from apps.finishing.serializers import FinishingReceiptSerializer
from apps.users.services import notify_role
from .models import BundleReceipt, ProductionQualityCheck, AccessoryIssue, BundleAccessoryIssue, OperatorAccessoryIssue, ProcessDispatch
from .serializers import (
    BundleReceiptSerializer, ProductionQualityCheckSerializer, AccessoryIssueSerializer,
    BundleAccessoryIssueSerializer, OperatorAccessoryIssueSerializer, ProcessDispatchSerializer,
)


class BundleReceiptViewSet(viewsets.ModelViewSet):
    queryset = BundleReceipt.objects.select_related("bundle", "received_by").all().order_by("-created_at")
    serializer_class = BundleReceiptSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "PRODUCTION_SUPERVISOR"]
    filterset_fields = ["bundle"]


class ProductionQualityCheckViewSet(viewsets.ModelViewSet):
    queryset = ProductionQualityCheck.objects.select_related("bundle", "checked_by").all().order_by("-created_at")
    serializer_class = ProductionQualityCheckSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "PRODUCTION_SUPERVISOR"]
    filterset_fields = ["bundle", "passed"]


class AccessoryIssueViewSet(viewsets.ModelViewSet):
    """Cutting issues accessories to Production for an order -- the accessories
    a bundle needs travel with the cut work. Reads are open to everyone
    authenticated (Production needs to see what's coming their way); only
    Cutting/Admin create the issuance, which deducts accessory stock."""
    queryset = AccessoryIssue.objects.select_related("order", "accessory_stock__accessory", "issued_by").all().order_by("-created_at")
    serializer_class = AccessoryIssueSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "CUTTING_SUPERVISOR"]
    filterset_fields = ["order", "accessory_stock"]
    search_fields = ["issue_number", "order__order_number"]


class BundleAccessoryIssueViewSet(viewsets.ModelViewSet):
    """Production allocating already Store-issued accessory stock down to a
    specific bundle/operator. Reads open to everyone; writes are Production's job."""
    queryset = BundleAccessoryIssue.objects.select_related(
        "bundle", "accessory_issue__accessory_stock__accessory", "operator", "issued_by",
    ).all().order_by("-created_at")
    serializer_class = BundleAccessoryIssueSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "PRODUCTION_SUPERVISOR"]
    filterset_fields = ["bundle", "accessory_issue", "operator"]

    @action(detail=True, methods=["post"])
    def return_unused(self, request, pk=None):
        """Operator hands back unused accessories -- the one place stock
        actually changes here, mirroring CuttingOrderViewSet.return_fabric."""
        bundle_issue = self.get_object()
        quantity = request.data.get("quantity")
        if quantity is None:
            return Response({"detail": "quantity is required."}, status=400)
        quantity = Decimal(str(quantity))
        already_returned = bundle_issue.returned_quantity or 0
        remaining = bundle_issue.issued_quantity - already_returned
        if quantity <= 0 or quantity > remaining:
            return Response({"detail": f"quantity must be between 0 and {remaining} (unreturned)."}, status=400)

        with transaction.atomic():
            accessory_stock = bundle_issue.accessory_issue.accessory_stock
            AccessoryStockTransaction.objects.create(
                accessory_stock=accessory_stock,
                transaction_type=AccessoryStockTransaction.TransactionType.RETURN,
                quantity=quantity,
                reference=bundle_issue.accessory_issue.issue_number,
                remarks=request.data.get("remarks") or f"Returned unused from bundle {bundle_issue.bundle.bundle_number}",
                created_by=request.user,
            )
            accessory_stock.available_quantity += quantity
            accessory_stock.save(update_fields=["available_quantity", "updated_at"])
            bundle_issue.returned_quantity = already_returned + quantity
            bundle_issue.save(update_fields=["returned_quantity", "updated_at"])
        return Response(self.get_serializer(bundle_issue).data)


class OperatorAccessoryIssueViewSet(viewsets.ModelViewSet):
    """Store issues accessories straight to an operator; Production/Store then
    record how much the operator used (and on how many pieces) and hand back
    the unused balance -- so accessory consumption is tracked per operator."""
    queryset = OperatorAccessoryIssue.objects.select_related(
        "operator", "accessory_stock__accessory", "order", "issued_by").all().order_by("-created_at")
    serializer_class = OperatorAccessoryIssueSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "STORE_MANAGER", "PRODUCTION_SUPERVISOR"]
    filterset_fields = ["operator", "accessory_stock", "order"]
    search_fields = ["issue_number", "operator__name", "order__order_number"]

    @action(detail=True, methods=["post"])
    def record_usage(self, request, pk=None):
        """Body: {used_quantity, pieces_covered} -- cumulative totals the
        operator has consumed so far (not increments)."""
        issue = self.get_object()
        try:
            used = Decimal(str(request.data.get("used_quantity")))
            pieces = int(request.data.get("pieces_covered") or 0)
        except Exception:
            return Response({"detail": "used_quantity and pieces_covered are required numbers."}, status=400)
        if used < 0 or used > (issue.issued_quantity - issue.returned_quantity):
            return Response({"detail": f"used_quantity must be between 0 and {issue.issued_quantity - issue.returned_quantity}."}, status=400)
        issue.used_quantity = used
        issue.pieces_covered = pieces
        issue.save(update_fields=["used_quantity", "pieces_covered", "updated_at"])
        return Response(self.get_serializer(issue).data)

    @action(detail=True, methods=["post"])
    def return_unused(self, request, pk=None):
        """Operator hands back unused accessories -- adds them back to stock."""
        issue = self.get_object()
        try:
            qty = Decimal(str(request.data.get("quantity")))
        except Exception:
            return Response({"detail": "quantity is required."}, status=400)
        if qty <= 0 or qty > issue.remaining_quantity:
            return Response({"detail": f"quantity must be between 0 and {issue.remaining_quantity} (remaining)."}, status=400)
        with transaction.atomic():
            stock = issue.accessory_stock
            AccessoryStockTransaction.objects.create(
                accessory_stock=stock, transaction_type=AccessoryStockTransaction.TransactionType.RETURN,
                quantity=qty, reference=issue.issue_number,
                remarks=f"Unused returned by operator {issue.operator.name}", created_by=request.user)
            stock.available_quantity += qty
            stock.save(update_fields=["available_quantity", "updated_at"])
            issue.returned_quantity += qty
            issue.save(update_fields=["returned_quantity", "updated_at"])
        return Response(self.get_serializer(issue).data)


class ProcessDispatchViewSet(viewsets.ModelViewSet):
    """Production sends completed pieces out to a processing department
    (Washing / Printing / Embroidery / Finishing / …) and receives them back,
    tracking quantity + send date + receive date."""
    queryset = ProcessDispatch.objects.select_related("order__party", "vendor", "sent_by", "received_by").all().order_by("-created_at")
    serializer_class = ProcessDispatchSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "PRODUCTION_SUPERVISOR", "FINISHING_SUPERVISOR"]
    filterset_fields = ["order", "department", "status"]
    search_fields = ["dispatch_number", "order__order_number"]

    def perform_create(self, serializer):
        dispatch = serializer.save()
        # Sending to Finishing marks the order as being finished.
        if dispatch.department == ProcessDispatch.Department.FINISHING and dispatch.order:
            dispatch.order.advance_status(Order.Status.IN_FINISHING)

    @action(detail=False, methods=["get"])
    def suggested_quantity(self, request):
        """Suggest how many pieces to send for an order = accepted (returned &
        QC'd) pieces. Query: ?order=<id>."""
        return Response({"suggested_quantity": self._accepted_pieces(request.query_params.get("order"))})

    @staticmethod
    def _accepted_pieces(order_id):
        from apps.operators.models import BundleAssignment
        if not order_id:
            return 0
        return int(BundleAssignment.objects.filter(
            bundle__cutting_order__order_id=order_id,
            status__in=[BundleAssignment.Status.COMPLETED, BundleAssignment.Status.QUALITY_CHECKED],
        ).aggregate(q=Sum("returned_quantity"))["q"] or 0)

    @action(detail=False, methods=["get"])
    def order_summary(self, request):
        """Everything the sender needs when picking an order: party, products,
        accepted pieces, and what's already been sent to each department --
        Query: ?order=<id>."""
        order_id = request.query_params.get("order")
        order = Order.objects.filter(pk=order_id).select_related("party").prefetch_related("items__product", "items__fabric_type").first()
        if not order:
            return Response({"detail": "Order not found."}, status=404)
        accepted = self._accepted_pieces(order_id)
        by_department = {}
        for pd in ProcessDispatch.objects.filter(order_id=order_id):
            e = by_department.setdefault(pd.department, {"sent": 0, "received": 0})
            e["sent"] += pd.quantity_sent
            e["received"] += (pd.quantity_received or 0)
        items = [{"product": f"{it.product.code} — {it.product.name}", "fabric": it.fabric_type.name} for it in order.items.all()]
        return Response({
            "order_number": order.order_number, "party_name": order.party.name if order.party_id else "",
            "order_type": order.order_type, "status": order.status, "items": items,
            "accepted_pieces": accepted, "by_department": by_department,
        })

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        """Receive pieces back from the department.
        Body: {quantity_received, received_date?, loss_reason?}.
        If fewer pieces come back than were sent, `loss_reason` is REQUIRED and
        the receipt is held at PENDING_APPROVAL until an Admin approves it --
        the shortfall isn't accepted (and pieces aren't finalised) before then."""
        dispatch = self.get_object()
        if dispatch.status == ProcessDispatch.Status.RECEIVED:
            return Response({"detail": "Already received back."}, status=400)
        qty = request.data.get("quantity_received")
        if qty is None:
            return Response({"detail": "quantity_received is required."}, status=400)
        qty = int(qty)
        if qty < 0 or qty > dispatch.quantity_sent:
            return Response({"detail": f"quantity_received must be between 0 and {dispatch.quantity_sent} (sent)."}, status=400)

        dispatch.quantity_received = qty
        dispatch.received_date = request.data.get("received_date") or timezone.now().date()
        dispatch.received_by = request.user
        if qty < dispatch.quantity_sent:
            reason = (request.data.get("loss_reason") or "").strip()
            if not reason:
                return Response({"detail": f"{dispatch.quantity_sent - qty} pieces short — a loss_reason is required, "
                                           f"and the shortfall must be approved by an Admin before it's accepted."}, status=400)
            dispatch.loss_reason = reason
            dispatch.loss_status = ProcessDispatch.LossStatus.PENDING
            dispatch.status = ProcessDispatch.Status.PENDING_APPROVAL
        else:
            dispatch.loss_status = ProcessDispatch.LossStatus.NONE
            dispatch.status = ProcessDispatch.Status.RECEIVED
        dispatch.save(update_fields=["quantity_received", "received_date", "received_by",
                                     "loss_reason", "loss_status", "status", "updated_at"])
        return Response(self.get_serializer(dispatch).data)

    @action(detail=True, methods=["post"])
    def approve_loss(self, request, pk=None):
        """Admin-only: approve or reject a pending shortage reason. Approving
        finalises the receipt (RECEIVED); rejecting sends it back so Production
        can re-check the count."""
        if not (request.user.is_superuser or request.user.role == "ADMIN"):
            return Response({"detail": "Only an Admin can approve a process shortage."}, status=403)
        dispatch = self.get_object()
        if dispatch.loss_status != ProcessDispatch.LossStatus.PENDING:
            return Response({"detail": "This dispatch has no pending shortage to review."}, status=400)
        approved = bool(request.data.get("approved"))
        dispatch.loss_reviewed_by = request.user
        dispatch.loss_reviewed_at = timezone.now()
        dispatch.loss_review_notes = request.data.get("notes", "")
        if approved:
            dispatch.loss_status = ProcessDispatch.LossStatus.APPROVED
            dispatch.status = ProcessDispatch.Status.RECEIVED
        else:
            dispatch.loss_status = ProcessDispatch.LossStatus.REJECTED
            dispatch.status = ProcessDispatch.Status.SENT  # re-open for a correct count
        dispatch.save(update_fields=["loss_reviewed_by", "loss_reviewed_at", "loss_review_notes",
                                     "loss_status", "status", "updated_at"])
        return Response(self.get_serializer(dispatch).data)


class SendToFinishingView(views.APIView):
    """POST {order, quantity, remarks?} -- Production's hand-off of
    completed pieces to Finishing. Creates the FinishingReceipt record,
    finally advances Order.status to IN_FINISHING (a dead enum value until
    now), and notifies the Finishing Supervisor."""
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "PRODUCTION_SUPERVISOR"]

    def post(self, request):
        order_id = request.data.get("order")
        quantity = request.data.get("quantity")
        if not order_id or not quantity:
            return Response({"detail": "order and quantity are required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            return Response({"detail": "Order not found."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            receipt = FinishingReceipt.objects.create(
                order=order, quantity_sent=int(quantity), sent_by=request.user,
                remarks=request.data.get("remarks", ""),
            )
            order.advance_status(Order.Status.IN_FINISHING)
        notify_role(
            "FINISHING_SUPERVISOR",
            f"{receipt.quantity_sent} pcs sent from Production for order {order.order_number} -- ready for finishing.",
            link="/finishing/receipts/",
        )
        return Response(FinishingReceiptSerializer(receipt).data, status=status.HTTP_201_CREATED)
