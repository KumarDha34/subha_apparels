from decimal import Decimal
from datetime import timedelta
from django.db import transaction as db_transaction
from django.db.models import Sum, Count, F
from django.utils import timezone
from rest_framework import viewsets, status, serializers
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.users.permissions import ReadOnlyOrHasRole, HasRole
from apps.operators.models import OperatorIncome, BundleAssignment
from apps.operators.services import assignment_labor_cost
from apps.orders.models import Order
from . import services
from .models import PurchaseOrder, PurchaseOrderItem, Invoice, PaymentRecord, IncomeRecord, ExpenseRecord, Quotation, CustomerInvoice
from .serializers import (
    PurchaseOrderSerializer, InvoiceSerializer, AddCostSerializer,
    PaymentRecordSerializer, IncomeRecordSerializer, ExpenseRecordSerializer, QuotationSerializer,
    CustomerInvoiceSerializer,
)

ACCOUNTS_ROLES = ["ADMIN", "ACCOUNTS", "STORE_MANAGER"]


class CustomerInvoiceViewSet(viewsets.ModelViewSet):
    """Sales invoices raised manually to customers (usually after dispatch),
    created by Accounts like quotations. Supports partial payments."""
    queryset = CustomerInvoice.objects.select_related("order__party").all()
    serializer_class = CustomerInvoiceSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "ACCOUNTS"]
    filterset_fields = ["order", "payment_status"]
    search_fields = ["invoice_number", "order__order_number"]

    @action(detail=True, methods=["post"], url_path="add-cost")
    def add_cost(self, request, pk=None):
        """Body: {label, amount}. Bill the customer an extra cost incurred while
        producing/completing the order, AFTER the invoice was raised. The charge
        is added to the invoice total (so the balance due grows) and recorded in
        `additional_costs` for a line-by-line breakdown. A fully-paid invoice
        re-opens as PARTIALLY_PAID with the new balance due."""
        inv = self.get_object()
        label = (request.data.get("label") or "").strip() or "Additional Cost"
        try:
            amount = Decimal(str(request.data.get("amount")))
        except Exception:
            return Response({"detail": "A valid amount is required."}, status=400)
        if amount <= 0:
            return Response({"detail": "Amount must be greater than zero."}, status=400)
        costs = inv.additional_costs or {}
        costs[label] = float(costs.get(label, 0)) + float(amount)
        inv.additional_costs = costs
        inv.amount = (inv.amount or Decimal("0")) + amount
        inv.save()  # re-derives payment_status against the new, higher total
        return Response(self.get_serializer(inv).data)

    @action(detail=True, methods=["post"])
    def record_payment(self, request, pk=None):
        """Body: {amount}. Adds a (partial) payment; status recomputes."""
        inv = self.get_object()
        try:
            amount = Decimal(str(request.data.get("amount")))
        except Exception:
            return Response({"detail": "A valid amount is required."}, status=400)
        if amount <= 0 or amount > inv.due_amount:
            return Response({"detail": f"amount must be between 0 and {inv.due_amount} (due)."}, status=400)
        inv.paid_amount += amount
        inv.save()  # save() re-derives payment_status

        # Single source of truth: every invoice payment books an IncomeRecord
        # linked to the order + invoice, so it flows straight into the accounts
        # dashboard, party ledger, order P&L and the sales report. A payment that
        # fully settles the invoice is FINAL; a partial one is an ADVANCE.
        fully_paid = inv.payment_status == CustomerInvoice.PaymentStatus.PAID
        IncomeRecord.objects.create(
            order=inv.order,
            customer_invoice=inv,
            income_type=(IncomeRecord.IncomeType.FINAL if fully_paid else IncomeRecord.IncomeType.ADVANCE),
            amount=amount,
            received_date=request.data.get("payment_date") or timezone.localdate(),
            payment_method=request.data.get("payment_method", ""),
            reference=request.data.get("reference", ""),
            remarks=f"Payment against sales invoice {inv.invoice_number}"
                    + (f" (order {inv.order.order_number})" if inv.order_id else ""),
            recorded_by=request.user,
        )
        # Once the buyer has fully settled, the order's financial cycle closes.
        if fully_paid and inv.order_id:
            inv.order.advance_status(inv.order.Status.PAID)
        return Response(self.get_serializer(inv).data)


class QuotationViewSet(viewsets.ModelViewSet):
    """Customer price quotes: DRAFT -> SENT -> ACCEPTED -> CONVERTED (or
    REJECTED / EXPIRED). Accounts/Merchandising manage them."""
    queryset = Quotation.objects.select_related("party", "product", "converted_order").all()
    serializer_class = QuotationSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "ACCOUNTS", "MERCHANDISE"]
    filterset_fields = ["status", "party", "product"]
    search_fields = ["quote_number", "party__name", "product__code", "product__name"]

    def get_queryset(self):
        # Auto-expire past-validity quotes that were never accepted/converted.
        today = timezone.localdate()
        Quotation.objects.filter(
            valid_till__lt=today, status__in=[Quotation.Status.DRAFT, Quotation.Status.SENT],
        ).update(status=Quotation.Status.EXPIRED)
        return super().get_queryset()

    def _transition(self, request, allowed_from, new_status):
        quote = self.get_object()
        if quote.status not in allowed_from:
            return Response({"detail": f"A {quote.get_status_display()} quotation can't move to {new_status}."}, status=400)
        quote.status = new_status
        quote.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(quote).data)

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        return self._transition(request, [Quotation.Status.DRAFT], Quotation.Status.SENT)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        return self._transition(request, [Quotation.Status.SENT], Quotation.Status.ACCEPTED)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._transition(request, [Quotation.Status.SENT, Quotation.Status.DRAFT], Quotation.Status.REJECTED)

    @action(detail=True, methods=["post"])
    def convert(self, request, pk=None):
        """Create a DRAFT Order from an ACCEPTED quotation (party, product,
        price/piece and quoted quantity carried over) and mark it CONVERTED.
        Merchandising then completes the fabric / colour / size detail on the
        new order. Returns the new order's id + number so the UI can jump to it."""
        from apps.orders.models import OrderItem, OrderItemColor, OrderItemColorSize
        from apps.master_data.models import FabricType, Color, Size
        quote = self.get_object()
        if quote.status != Quotation.Status.ACCEPTED:
            return Response({"detail": "Only an ACCEPTED quotation can be converted to an order."}, status=400)
        if quote.converted_order_id:
            return Response({"detail": "This quotation has already been converted."}, status=400)

        fabric = FabricType.objects.filter(is_active=True).first()
        color = Color.objects.filter(is_active=True).first()
        size = Size.objects.filter(is_active=True).first() if hasattr(Size, "is_active") else Size.objects.first()
        if not (fabric and color and size):
            return Response({"detail": "Set up at least one fabric type, colour and size before converting quotes."}, status=400)

        with db_transaction.atomic():
            order = Order.objects.create(
                party=quote.party, order_date=timezone.localdate(),
                order_type=Order.OrderType.FIXED_QUANTITY,
                remarks=f"Created from quotation {quote.quote_number}.",
                total_order_amount=quote.amount, created_by=request.user,
            )
            item = OrderItem.objects.create(
                order=order, product=quote.product, fabric_type=fabric,
                approved_average=Decimal("1.000"),
            )
            oic = OrderItemColor.objects.create(order_item=item, color=color)
            OrderItemColorSize.objects.create(order_item_color=oic, size=size, quantity=quote.quantity)
            quote.converted_order = order
            quote.status = Quotation.Status.CONVERTED
            quote.save(update_fields=["converted_order", "status", "updated_at"])
        return Response({
            "detail": f"Order {order.order_number} created from {quote.quote_number}.",
            "order_id": order.id, "order_number": order.order_number,
            "quotation": self.get_serializer(quote).data,
        }, status=201)


class CanReceivePurchaseOrder(BasePermission):
    """Receiving physically moves stock -- Store's job, not Accounts'."""
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (u.is_superuser or u.role in ("ADMIN", "STORE_MANAGER")))


class ReceiveLineSerializer(serializers.Serializer):
    item_id = serializers.IntegerField()
    received_quantity = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))
    rate = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0"))


class ReceivePurchaseOrderSerializer(serializers.Serializer):
    items = ReceiveLineSerializer(many=True)


class RecordPaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    payment_method = serializers.ChoiceField(choices=PaymentRecord.PaymentMethod.choices)
    payment_date = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.select_related("vendor", "party", "related_order").prefetch_related("items").all().order_by("-created_at")
    serializer_class = PurchaseOrderSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ACCOUNTS_ROLES
    filterset_fields = ["receipt_status", "po_type", "vendor"]
    search_fields = ["po_number", "vendor__company_name"]

    @action(detail=True, methods=["post"], permission_classes=[CanReceivePurchaseOrder])
    def receive(self, request, pk=None):
        po = self.get_object()
        if po.po_type == PurchaseOrder.POType.CUSTOMER_SUPPLIED:
            return Response({"detail": "Customer-supplied purchases are received automatically at creation."}, status=400)
        if po.receipt_status == PurchaseOrder.ReceiptStatus.RECEIVED:
            return Response({"detail": "This purchase order has already been fully received."}, status=400)

        payload = ReceivePurchaseOrderSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        lines = payload.validated_data["items"]

        items_by_id = {i.id: i for i in po.items.all()}
        for line in lines:
            item = items_by_id.get(line["item_id"])
            if not item:
                return Response({"detail": f"Item {line['item_id']} does not belong to this purchase order."}, status=400)
            remaining = item.quantity - item.received_quantity
            if line["received_quantity"] > remaining:
                return Response(
                    {"detail": f"Cannot receive {line['received_quantity']} for '{item.item_name}': only {remaining} remaining."},
                    status=400,
                )

        with db_transaction.atomic():
            for line in lines:
                if line["received_quantity"] <= 0:
                    continue
                services.apply_receipt(items_by_id[line["item_id"]], line["received_quantity"], line["rate"], po, request.user)
            services.recompute_receipt_status(po)
            services.sync_invoice(po)

        po.refresh_from_db()
        return Response(PurchaseOrderSerializer(po, context={"request": request}).data)


class InvoiceViewSet(viewsets.ModelViewSet):
    """Invoices auto-generate their total from subtotal + tax + additional costs."""
    queryset = Invoice.objects.select_related("purchase_order", "vendor").all().order_by("-created_at")
    serializer_class = InvoiceSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "ACCOUNTS"]
    filterset_fields = ["payment_status", "vendor", "purchase_order"]
    search_fields = ["invoice_number", "vendor__company_name"]

    @action(detail=True, methods=["post"], url_path="add-cost")
    def add_cost(self, request, pk=None):
        invoice = self.get_object()
        serializer = AddCostSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        key = serializer.validated_data["key"]
        amount = serializer.validated_data["amount"]
        with db_transaction.atomic():
            costs = invoice.additional_costs or {}
            costs[key] = float(costs.get(key, 0)) + float(amount)
            invoice.additional_costs = costs
            invoice.save()                          # recomputes total_amount
            # Total went up -> re-derive status. A previously PAID bill becomes
            # PARTIALLY_PAID with the new balance due; Record Payment reappears.
            services.sync_invoice_status(invoice)
        invoice.refresh_from_db()
        return Response(self.get_serializer(invoice).data)

    @action(detail=True, methods=["post"], url_path="pay")
    def pay(self, request, pk=None):
        invoice = self.get_object()
        if invoice.payment_status == Invoice.PaymentStatus.PAID:
            return Response({"detail": "This invoice is already fully paid."}, status=400)
        serializer = RecordPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        try:
            with db_transaction.atomic():
                services.record_payment(invoice, d["amount"], d["payment_method"], d["payment_date"], d.get("notes", ""), request.user)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        invoice.refresh_from_db()
        return Response(self.get_serializer(invoice).data)


class PaymentRecordViewSet(viewsets.ModelViewSet):
    queryset = PaymentRecord.objects.select_related("purchase_order", "invoice").all().order_by("-created_at")
    serializer_class = PaymentRecordSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "ACCOUNTS"]
    filterset_fields = ["payment_status", "payment_method", "invoice"]


class IncomeRecordViewSet(viewsets.ModelViewSet):
    queryset = IncomeRecord.objects.select_related("order").all().order_by("-received_date")
    serializer_class = IncomeRecordSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "ACCOUNTS"]
    filterset_fields = ["income_type", "order"]


class ExpenseRecordViewSet(viewsets.ModelViewSet):
    queryset = ExpenseRecord.objects.select_related("order").all().order_by("-expense_date")
    serializer_class = ExpenseRecordSerializer
    permission_classes = [ReadOnlyOrHasRole]
    required_roles = ["ADMIN", "ACCOUNTS"]
    filterset_fields = ["category", "order"]


class AccountsSummaryView(APIView):
    """
    GET /api/accounts/summary/
    The single "Accounts Dashboard" endpoint: total income, total expenses,
    net profit, breakdowns, and pending payments - mirrors the accounts
    summary dashboard in the spec.
    """
    permission_classes = [HasRole]
    required_roles = ["ADMIN", "ACCOUNTS"]

    def get(self, request):
        order_income = IncomeRecord.objects.aggregate(t=Sum("amount"))["t"] or 0
        raw_materials = Invoice.objects.aggregate(t=Sum("subtotal"))["t"] or 0
        additional_costs_total = 0
        for invoice in Invoice.objects.exclude(additional_costs__isnull=True):
            additional_costs_total += sum((invoice.additional_costs or {}).values())
        operator_payments = OperatorIncome.objects.filter(payment_status="PAID").aggregate(t=Sum("total_income"))["t"] or 0
        other_expenses = ExpenseRecord.objects.aggregate(t=Sum("amount"))["t"] or 0

        total_income = order_income
        total_expenses = float(raw_materials) + float(additional_costs_total) + float(operator_payments) + float(other_expenses)
        net_profit = float(total_income) - total_expenses

        # Computed per-invoice from its LATEST payment snapshot (not summed
        # across every PaymentRecord row) -- an invoice can accumulate many
        # payment installments over time, and only the most recent one
        # reflects the current outstanding balance.
        pending_to_suppliers = 0
        pending_to_suppliers_count = 0
        for invoice in Invoice.objects.exclude(payment_status=Invoice.PaymentStatus.PAID):
            latest = invoice.payment_records.order_by("-id").first()
            due = latest.due_amount if latest else invoice.total_amount
            if due > 0:
                pending_to_suppliers += due
                pending_to_suppliers_count += 1
        pending_to_operators = OperatorIncome.objects.filter(payment_status="PENDING").aggregate(t=Sum("total_income"))["t"] or 0
        pending_to_operators_count = OperatorIncome.objects.filter(payment_status="PENDING").count()

        income_breakdown = {
            choice_value: float(
                IncomeRecord.objects.filter(income_type=choice_value).aggregate(t=Sum("amount"))["t"] or 0
            )
            for choice_value, _ in IncomeRecord.IncomeType.choices
        }
        expense_breakdown = {
            "raw_materials": float(raw_materials),
            "additional_costs": float(additional_costs_total),
            "operator_payments": float(operator_payments),
            "other_expenses": float(other_expenses),
        }

        return Response({
            "total_income": total_income,
            "total_expenses": total_expenses,
            "net_profit": net_profit,
            "income_breakdown": income_breakdown,
            "expense_breakdown": expense_breakdown,
            "pending_payments": {
                "to_suppliers": {"amount": float(pending_to_suppliers), "count": pending_to_suppliers_count},
                "to_operators": {"amount": float(pending_to_operators), "count": pending_to_operators_count},
                "total": float(pending_to_suppliers) + float(pending_to_operators),
            },
        })


class OrderPnLView(APIView):
    """
    GET /api/accounts/orders/{id}/pnl/
    Full per-order cost/income breakdown: fabric+accessory cost (from
    ORDER_SPECIFIC/CUSTOMER_SUPPLIED POs tied to this order via
    PurchaseOrder.related_order -- BULK-purchased general stock is
    intentionally excluded, since that's shared inventory, not order-
    specific spend), labor cost (via the same assignment_labor_cost
    helper OperatorIncome.calculate uses, so the two never drift -- each
    operator is paid the bundle assignment's rate_per_piece x pieces returned), finishing
    cost, transport cost, income received, and profit/loss.
    """
    permission_classes = [HasRole]
    required_roles = ["ADMIN", "ACCOUNTS"]

    def get(self, request, pk=None):
        from apps.finishing.models import Dispatch
        from apps.production.models import ProcessDispatch

        try:
            order = Order.objects.get(pk=pk)
        except Order.DoesNotExist:
            return Response({"detail": "Order not found."}, status=404)

        material_items = PurchaseOrderItem.objects.filter(
            purchase_order__related_order=order, rate__isnull=False,
        )
        fabric_cost = sum(
            (i.received_quantity * i.rate for i in material_items.filter(material_type="FABRIC")), Decimal("0")
        )
        accessory_cost = sum(
            (i.received_quantity * i.rate for i in material_items.filter(material_type="ACCESSORY")), Decimal("0")
        )

        labor_cost = Decimal("0")
        assignments = BundleAssignment.objects.filter(
            bundle__cutting_order__order=order,
            status__in=[BundleAssignment.Status.COMPLETED, BundleAssignment.Status.QUALITY_CHECKED],
        ).select_related("bundle__cutting_order__order_item")
        for assignment in assignments:
            # Operators are paid the assignment's rate_per_piece x pieces returned.
            labor_cost += assignment_labor_cost(assignment)

        # Processing cost, broken out per department (Washing/Printing/Embroidery/Finishing).
        from collections import defaultdict
        process_costs = defaultdict(Decimal)
        for pd in ProcessDispatch.objects.filter(order=order):
            if pd.cost:
                process_costs[pd.department] += pd.cost
        finishing_cost = sum(process_costs.values(), Decimal("0"))

        dispatch = Dispatch.objects.filter(order=order).first()
        transport_cost = (dispatch.transport_cost if dispatch and dispatch.transport_cost else Decimal("0"))

        # Extra, non-material charges (transport, courier, customs, storage,
        # sample, testing, penalties, handling), broken out per charge type.
        from apps.store.models import OrderAdditionalCharge
        charge_costs = defaultdict(Decimal)
        for ch in OrderAdditionalCharge.objects.filter(order=order):
            charge_costs[ch.charge_type] += ch.amount
        additional_charges = sum(charge_costs.values(), Decimal("0"))

        total_cost = fabric_cost + accessory_cost + labor_cost + finishing_cost + transport_cost + additional_charges

        income_received = IncomeRecord.objects.filter(order=order).aggregate(t=Sum("amount"))["t"] or Decimal("0")
        profit_loss = income_received - total_cost
        margin_pct = round(float(profit_loss) / float(income_received) * 100, 1) if income_received else None

        return Response({
            "order_number": order.order_number,
            "costs": {
                "fabric_cost": float(fabric_cost),
                "accessory_cost": float(accessory_cost),
                "labor_cost": float(labor_cost),
                "finishing_cost": float(finishing_cost),
                "transport_cost": float(transport_cost),
                "additional_charges": float(additional_charges),
                "total_cost": float(total_cost),
            },
            # Per-department processing costs and per-type additional charges,
            # so the invoice can show a complete line-by-line cost breakdown.
            "process_costs": {k: float(v) for k, v in process_costs.items()},
            "charge_costs": {k: float(v) for k, v in charge_costs.items()},
            "income_received": float(income_received),
            "profit_loss": float(profit_loss),
            "margin_pct": margin_pct,
            "note": "Fabric/accessory cost only includes Order-Specific and Customer-Supplied purchases tied to this order -- Bulk-purchased general stock is shared inventory and isn't attributed to any single order.",
        })


class PartyStatementView(APIView):
    """GET /api/accounts/party-statement/?party=<id>  (Admin / Accounts)
    A full statement of account for one buyer: a running-balance ledger (each
    sales invoice is a debit, each payment received a credit), a periodic
    summary, an ageing analysis of outstanding invoices, and a payment history.
    Everything rolls up from CustomerInvoice + IncomeRecord -- the same records
    the invoice screen and dashboard use."""
    permission_classes = [HasRole]
    required_roles = ["ADMIN", "ACCOUNTS"]

    def _all_parties(self):
        from apps.master_data.models import Party
        from apps.orders.models import Order
        rows = []
        for p in Party.objects.all():
            billed = float(CustomerInvoice.objects.filter(order__party=p).aggregate(s=Sum("amount"))["s"] or 0)
            if not billed:
                billed = float(Order.objects.filter(party=p).exclude(status="CANCELLED").aggregate(s=Sum("total_order_amount"))["s"] or 0)
            received = float(IncomeRecord.objects.filter(order__party=p).aggregate(s=Sum("amount"))["s"] or 0)
            rows.append({"id": p.id, "name": p.name, "billed": round(billed, 2), "received": round(received, 2),
                         "outstanding": round(max(billed - received, 0), 2)})
        rows.sort(key=lambda r: -r["outstanding"])
        return rows

    def get(self, request):
        from apps.master_data.models import Party
        pid = request.query_params.get("party")
        if not pid:
            return Response({"parties": self._all_parties()})
        try:
            party = Party.objects.get(pk=pid)
        except (Party.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "Party not found."}, status=404)

        from apps.orders.models import Order
        invoices = list(CustomerInvoice.objects.filter(order__party=party).select_related("order"))
        payments = list(IncomeRecord.objects.filter(order__party=party).select_related("order"))

        # Ledger: each order's billed value is a debit (receivable up), each
        # payment received is a credit (receivable down). The billed value is
        # the sales invoice when one exists, else the order's own value.
        inv_by_order = {}
        for inv in invoices:
            cur = inv_by_order.setdefault(inv.order_id, {"amount": 0.0, "number": None, "date": None})
            cur["amount"] += float(inv.amount); cur["number"] = inv.invoice_number; cur["date"] = str(inv.invoice_date)

        entries = []
        for o in Order.objects.filter(party=party).exclude(status="CANCELLED"):
            info = inv_by_order.get(o.id)
            billed = info["amount"] if info else float(o.total_order_amount or 0)
            if billed <= 0:
                continue
            entries.append({
                "date": info["date"] if info else str(o.order_date),
                "voucher": info["number"] if info else o.order_number,
                "particulars": (f"Sales Invoice — {o.order_number}" if info else f"Order Value — {o.order_number}"),
                "debit": round(billed, 2), "credit": 0.0, "_o": 0})
        for ir in payments:
            method = ir.get_payment_method_display() if ir.payment_method else "Payment"
            label = f"Payment received — {method}" + (f" ({ir.reference})" if ir.reference else "")
            entries.append({"date": str(ir.received_date), "voucher": ir.reference or f"RCPT-{ir.id}",
                            "particulars": label, "debit": 0.0, "credit": float(ir.amount), "_o": 1})
        entries.sort(key=lambda e: (e["date"], e["_o"]))
        balance = 0.0
        for e in entries:
            balance += e["debit"] - e["credit"]
            e["balance"] = round(balance, 2)
            e.pop("_o", None)

        total_debit = round(sum(e["debit"] for e in entries), 2)
        total_credit = round(sum(e["credit"] for e in entries), 2)
        closing = round(total_debit - total_credit, 2)

        # Ageing of still-outstanding invoices, by age of the (due or invoice) date.
        today = timezone.localdate()
        ageing = {"0-30": 0.0, "31-60": 0.0, "61-90": 0.0, "90+": 0.0}
        for inv in invoices:
            due = float(inv.due_amount)
            if due <= 0:
                continue
            base = inv.due_date or inv.invoice_date
            days = (today - base).days
            bucket = "0-30" if days <= 30 else "31-60" if days <= 60 else "61-90" if days <= 90 else "90+"
            ageing[bucket] = round(ageing[bucket] + due, 2)

        pay_history = [{"date": str(ir.received_date), "reference": ir.reference or "—",
                        "method": (ir.get_payment_method_display() if ir.payment_method else "—"),
                        "amount": float(ir.amount)}
                       for ir in sorted(payments, key=lambda r: str(r.received_date))]

        return Response({
            "party": {
                "name": party.name, "code": party.code_prefix or "—",
                "contact_person": party.contact_person or "—", "phone": party.phone or "—",
                "email": party.email or "—", "address": party.address or "—",
                "pan_vat": party.pan_vat or "—", "credit_terms": party.credit_terms or "—",
                "credit_limit": float(party.credit_limit or 0),
            },
            "entries": entries,
            "summary": {"opening": 0.0, "total_debit": total_debit, "total_credit": total_credit, "closing": closing},
            "ageing": ageing,
            "payments": pay_history,
            "as_of": str(today),
        })


class SupplierStatementView(APIView):
    """GET /api/accounts/supplier-statement/                 -> all suppliers summary
    GET /api/accounts/supplier-statement/?supplier=<id>  -> one supplier's statement

    Mirror of PartyStatementView for the payables side: each purchase bill is a
    debit (payable up), each payment installment a credit (payable down). Rolls
    up from Invoice + PaymentRecord -- the same records the Supplier Bills screen
    uses. PaymentRecord stores the CUMULATIVE paid amount, so each installment is
    the difference from the previous row for that bill."""
    permission_classes = [HasRole]
    required_roles = ["ADMIN", "ACCOUNTS"]

    def _all_suppliers(self):
        from apps.master_data.models import Vendor
        rows = []
        for v in Vendor.objects.all():
            invs = list(Invoice.objects.filter(vendor=v))
            billed = float(sum((i.total_amount for i in invs), Decimal("0")))
            paid = 0.0
            for inv in invs:
                last = inv.payment_records.order_by("-id").first()
                paid += float(last.paid_amount) if last else 0.0
            if not invs:
                continue
            rows.append({"id": v.id, "name": v.company_name, "invoices": len(invs),
                         "billed": round(billed, 2), "paid": round(paid, 2),
                         "payable": round(max(billed - paid, 0), 2)})
        rows.sort(key=lambda r: -r["payable"])
        return rows

    def get(self, request):
        from apps.master_data.models import Vendor
        vid = request.query_params.get("supplier")
        if not vid:
            return Response({"suppliers": self._all_suppliers()})
        try:
            vendor = Vendor.objects.get(pk=vid)
        except (Vendor.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "Supplier not found."}, status=404)

        invoices = list(Invoice.objects.filter(vendor=vendor).order_by("invoice_date"))
        today = timezone.localdate()
        entries, pay_history = [], []
        total_billed = total_paid = 0.0
        ageing = {"0-30": 0.0, "31-60": 0.0, "61-90": 0.0, "90+": 0.0}
        for inv in invoices:
            total = float(inv.total_amount)
            total_billed += total
            entries.append({"date": str(inv.invoice_date), "voucher": inv.invoice_number or f"BILL-{inv.id}",
                            "particulars": f"Purchase Bill — {inv.invoice_number or inv.id}",
                            "debit": round(total, 2), "credit": 0.0, "_o": 0})
            prev = 0.0
            for pr in inv.payment_records.order_by("id"):
                inst = float(pr.paid_amount) - prev
                prev = float(pr.paid_amount)
                if inst <= 0:
                    continue
                total_paid += inst
                method = pr.get_payment_method_display() if getattr(pr, "payment_method", None) else "Payment"
                entries.append({"date": str(pr.payment_date), "voucher": inv.invoice_number or f"BILL-{inv.id}",
                                "particulars": f"Payment made — {method}", "debit": 0.0, "credit": round(inst, 2), "_o": 1})
                pay_history.append({"date": str(pr.payment_date), "reference": inv.invoice_number or f"BILL-{inv.id}",
                                    "method": method, "amount": round(inst, 2)})
            due = max(total - prev, 0)
            if due > 0:
                base = inv.due_date or inv.invoice_date
                days = (today - base).days
                bucket = "0-30" if days <= 30 else "31-60" if days <= 60 else "61-90" if days <= 90 else "90+"
                ageing[bucket] = round(ageing[bucket] + due, 2)

        entries.sort(key=lambda e: (e["date"], e["_o"]))
        balance = 0.0
        for e in entries:
            balance += e["debit"] - e["credit"]
            e["balance"] = round(balance, 2)
            e.pop("_o", None)
        closing = round(total_billed - total_paid, 2)

        return Response({
            "supplier": {
                "name": vendor.company_name, "contact_person": vendor.contact_person or "—",
                "phone": vendor.phone or "—", "email": vendor.email or "—",
                "address": vendor.address or "—", "gst": vendor.gst_number or "—",
                "payment_terms": vendor.get_payment_terms_display() if vendor.payment_terms else "—",
            },
            "entries": entries,
            "summary": {"opening": 0.0, "total_debit": round(total_billed, 2),
                        "total_credit": round(total_paid, 2), "closing": closing},
            "ageing": ageing,
            "payments": sorted(pay_history, key=lambda x: x["date"]),
            "as_of": str(today),
        })


class ManagementKPIView(APIView):
    """
    GET /api/accounts/kpi/  (Admin only)
    The whole business on one screen: financial health, production &
    efficiency, quality & people, order pipeline, per-style labour, and a
    short "needs attention" list. Every figure rolls up from the same detail
    models the department pages use -- nothing here is hard-coded.
    """
    permission_classes = [HasRole]
    required_roles = ["ADMIN"]

    def get(self, request):
        from apps.finishing.models import FinishingQualityCheck
        from apps.production.models import ProcessDispatch
        from apps.cutting.models import CuttingOrder
        from apps.operators.models import Operator, BundleAssignment
        from apps.store.models import FabricStock

        today = timezone.localdate()
        F0 = lambda x: float(x or 0)
        DONE = [BundleAssignment.Status.COMPLETED, BundleAssignment.Status.QUALITY_CHECKED]

        # ---------------- Financial health ----------------
        # This system captures buyer money via IncomeRecord (there is no
        # separate selling-price field on an order), so "revenue" here is the
        # income actually booked from buyers -- the same basis the Accounts
        # summary uses -- not a notional order value.
        income_received = IncomeRecord.objects.aggregate(t=Sum("amount"))["t"] or 0
        income_record_count = IncomeRecord.objects.count()

        raw_materials = Invoice.objects.aggregate(t=Sum("subtotal"))["t"] or 0
        additional_costs_total = 0.0
        for inv in Invoice.objects.exclude(additional_costs__isnull=True):
            additional_costs_total += sum((inv.additional_costs or {}).values())
        operator_accrued = OperatorIncome.objects.aggregate(t=Sum("total_income"))["t"] or 0
        operator_paid = OperatorIncome.objects.aggregate(t=Sum("paid_amount"))["t"] or 0
        finishing_cost = ProcessDispatch.objects.aggregate(t=Sum("cost"))["t"] or 0
        other_expenses = ExpenseRecord.objects.aggregate(t=Sum("amount"))["t"] or 0

        total_expenses = (F0(raw_materials) + additional_costs_total + F0(operator_accrued)
                          + F0(finishing_cost) + F0(other_expenses))
        net_profit = F0(income_received) - total_expenses
        margin_pct = round(net_profit / F0(income_received) * 100, 1) if income_received else None

        # Cash actually moved: money received in vs. money actually paid out.
        supplier_paid = 0.0
        for inv in Invoice.objects.all():
            latest = inv.payment_records.order_by("-id").first()
            supplier_paid += F0(latest.paid_amount) if latest else 0.0
        cash_out = supplier_paid + F0(operator_paid) + F0(other_expenses)
        net_cash_position = F0(income_received) - cash_out

        # ---------------- Production & efficiency ----------------
        all_asg = BundleAssignment.objects.all()
        issued = all_asg.aggregate(t=Sum("issued_quantity"))["t"] or 0
        returned = all_asg.aggregate(t=Sum("returned_quantity"))["t"] or 0
        defects = all_asg.aggregate(t=Sum("defects"))["t"] or 0
        pieces_produced = BundleAssignment.objects.filter(status__in=DONE).aggregate(t=Sum("returned_quantity"))["t"] or 0
        efficiency_pct = round((returned - defects) / issued * 100, 1) if issued else None

        cut = CuttingOrder.objects.aggregate(
            w=Sum("wastage_quantity"), used=Sum("fabric_used_quantity"), issued=Sum("fabric_issued_quantity"),
        )
        wastage_base = F0(cut["used"]) + F0(cut["w"])
        wastage_pct = round(F0(cut["w"]) / wastage_base * 100, 1) if wastage_base else None

        orders_total = Order.objects.exclude(status=Order.Status.CANCELLED).count()
        orders_pending_dispatch = Order.objects.exclude(
            status__in=Order.DISPATCHED_OR_BEYOND + [Order.Status.CANCELLED]
        ).count()

        # ---------------- Quality & people ----------------
        finishing_rejects = FinishingQualityCheck.objects.aggregate(t=Sum("quantity_rejected"))["t"] or 0
        total_rejects = int(defects) + int(finishing_rejects)
        top_reason_row = (
            BundleAssignment.objects.filter(defects__gt=0).exclude(defect_reason="")
            .values("defect_reason").annotate(n=Sum("defects")).order_by("-n").first()
        )
        top_reject_reason = top_reason_row["defect_reason"] if top_reason_row else "—"
        top_reject_pieces = int(top_reason_row["n"]) if top_reason_row else 0

        employees = Operator.objects.count()
        active_operators = (
            BundleAssignment.objects.filter(returned_quantity__isnull=False)
            .values("operator").distinct().count()
        )

        # ---------------- Order pipeline ----------------
        total_orders_all = Order.objects.count()
        dispatched = Order.objects.filter(status__in=Order.DISPATCHED_OR_BEYOND).count()
        cancelled = Order.objects.filter(status=Order.Status.CANCELLED).count()
        in_progress = orders_total - dispatched
        fulfilment_rate = round(dispatched / total_orders_all * 100) if total_orders_all else 0

        # ---------------- Labour by style ----------------
        style_map = {}
        for a in BundleAssignment.objects.filter(status__in=DONE).select_related(
            "bundle__cutting_order__order_item__product"
        ):
            oi = a.bundle.cutting_order.order_item if a.bundle.cutting_order else None
            if not oi or not oi.product_id:
                continue
            d = style_map.setdefault(oi.product_id, {
                "style": f"{oi.product.code} — {oi.product.name}", "pieces": 0, "labor": Decimal("0"),
            })
            qty = a.returned_quantity or 0
            d["pieces"] += qty
            d["labor"] += Decimal(a.rate_per_piece or 0) * qty
        by_style = sorted(style_map.values(), key=lambda r: r["pieces"], reverse=True)[:8]
        by_style = [{
            "style": r["style"], "pieces": r["pieces"], "labor_cost": float(r["labor"]),
            "avg_rate": round(float(r["labor"]) / r["pieces"], 2) if r["pieces"] else 0,
        } for r in by_style]

        # ---------------- Needs attention ----------------
        attention = []
        cutoff = today - timedelta(days=14)
        for o in (Order.objects.exclude(status__in=Order.DISPATCHED_OR_BEYOND + [Order.Status.CANCELLED])
                  .filter(order_date__lte=cutoff).select_related("party").order_by("order_date")[:5]):
            attention.append({
                "level": "danger",
                "text": f"{o.order_number} ({o.party.name}) is overdue — placed {o.order_date}, still {o.get_status_display().lower()}.",
            })
        low_stock = FabricStock.objects.filter(available_quantity__lte=0, is_active=True).count()
        if low_stock:
            attention.append({"level": "warning", "text": f"{low_stock} fabric stock item(s) out of stock — restock soon."})
        shortage_reviews = BundleAssignment.objects.filter(
            shortage_reason_status=BundleAssignment.ShortageStatus.PENDING_REVIEW).count()
        if shortage_reviews:
            attention.append({"level": "warning", "text": f"{shortage_reviews} bundle shortage reason(s) awaiting your review."})
        overdue_invoices = Invoice.objects.exclude(payment_status=Invoice.PaymentStatus.PAID).filter(
            due_date__lt=today).count()
        if overdue_invoices:
            attention.append({"level": "danger", "text": f"{overdue_invoices} supplier invoice(s) overdue for payment."})
        pending_operator_pay = OperatorIncome.objects.filter(payment_status="PENDING").count()
        if pending_operator_pay:
            attention.append({"level": "info", "text": f"{pending_operator_pay} operator income statement(s) pending payment."})
        if not attention:
            attention.append({"level": "success", "text": "Nothing needs urgent attention — every pipeline is clear."})

        return Response({
            "as_of": today,
            "financial": {
                "revenue_received": F0(income_received), "income_record_count": income_record_count,
                "total_expenses": total_expenses,
                "net_profit": net_profit, "margin_pct": margin_pct,
                "net_cash_position": net_cash_position,
            },
            "production": {
                "pieces_produced": int(pieces_produced),
                "efficiency_pct": efficiency_pct,
                "wastage_pct": wastage_pct,
                "orders_pending_dispatch": orders_pending_dispatch,
                "orders_total": orders_total,
            },
            "quality_people": {
                "total_rejects": total_rejects,
                "stitching_rejects": int(defects), "finishing_rejects": int(finishing_rejects),
                "top_reject_reason": top_reject_reason, "top_reject_pieces": top_reject_pieces,
                "employees": employees, "active_operators": active_operators,
            },
            "pipeline": {
                "total_orders": total_orders_all, "dispatched": dispatched,
                "in_progress": max(in_progress, 0), "cancelled": cancelled,
                "fulfilment_rate": fulfilment_rate,
            },
            "by_style": by_style,
            "attention": attention,
        })
