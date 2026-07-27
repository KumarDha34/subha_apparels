"""Admin financial dashboard endpoint.

Gives the Admin the same financial picture as the Accounts dashboard (identical
income / expense / net-profit / cash totals) PLUS full drill-downs (per-order,
per-supplier, per-operator), department cost rollups, per-order & per-product
profitability, a receivable/payable cash position, and system-wide KPIs -- all
in one call so the Admin Overview never has to fan out to a dozen endpoints.
"""
from collections import defaultdict
from decimal import Decimal
from django.db.models import Sum
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.users.permissions import HasRole
from apps.orders.models import Order
from apps.operators.models import OperatorIncome, BundleAssignment
from apps.operators.services import assignment_labor_cost
from .models import Invoice, PurchaseOrderItem, IncomeRecord, ExpenseRecord, CustomerInvoice
from . import product_pnl


def _f(v):
    return round(float(v or 0), 2)


def _order_cost(order):
    """Per-order cost breakdown, identical in spirit to OrderPnLView: only
    order-specific / customer-supplied material spend is attributed (bulk stock
    is shared inventory), labour matches operator pay, plus processing,
    transport and per-order extra charges."""
    from apps.finishing.models import Dispatch
    from apps.production.models import ProcessDispatch
    from apps.store.models import OrderAdditionalCharge

    mitems = list(PurchaseOrderItem.objects.filter(purchase_order__related_order=order, rate__isnull=False))
    fabric = sum((i.received_quantity * i.rate for i in mitems if i.material_type == "FABRIC"), Decimal("0"))
    accessory = sum((i.received_quantity * i.rate for i in mitems if i.material_type == "ACCESSORY"), Decimal("0"))
    labor = Decimal("0")
    for a in BundleAssignment.objects.filter(
        bundle__cutting_order__order=order,
        status__in=[BundleAssignment.Status.COMPLETED, BundleAssignment.Status.QUALITY_CHECKED],
    ):
        labor += assignment_labor_cost(a)
    # Rework labour (altered pieces reworked by an operator) adds to labour.
    from apps.finishing.models import ReworkAssignment
    for ra in ReworkAssignment.objects.filter(qc__order=order, status=ReworkAssignment.Status.COMPLETED):
        labor += (ra.returned_quantity or 0) * (ra.rate_per_piece or Decimal("0"))
    processing = sum((pd.cost for pd in ProcessDispatch.objects.filter(order=order) if pd.cost), Decimal("0"))
    disp = Dispatch.objects.filter(order=order).first()
    transport = disp.transport_cost if disp and disp.transport_cost else Decimal("0")
    charges = sum((c.amount for c in OrderAdditionalCharge.objects.filter(order=order)), Decimal("0"))
    total = fabric + accessory + labor + processing + transport + charges
    income = IncomeRecord.objects.filter(order=order).aggregate(t=Sum("amount"))["t"] or Decimal("0")
    return {
        "fabric": fabric, "accessory": accessory, "labor": labor, "processing": processing,
        "transport": transport, "charges": charges, "total": total, "income": income,
        "profit": income - total,
    }


class AdminFinancialView(APIView):
    """GET /api/accounts/admin-dashboard/  (Admin only)."""
    permission_classes = [HasRole]
    required_roles = ["ADMIN"]

    def get(self, request):
        # ---- headline totals (mirror AccountsSummaryView so the two agree) ----
        order_income = float(IncomeRecord.objects.aggregate(t=Sum("amount"))["t"] or 0)
        raw_materials = float(Invoice.objects.aggregate(t=Sum("subtotal"))["t"] or 0)
        supplier_extra = 0.0
        for inv in Invoice.objects.exclude(additional_costs__isnull=True):
            supplier_extra += sum((inv.additional_costs or {}).values())
        operator_paid = float(OperatorIncome.objects.filter(payment_status="PAID").aggregate(t=Sum("total_income"))["t"] or 0)
        other_exp = float(ExpenseRecord.objects.aggregate(t=Sum("amount"))["t"] or 0)
        total_expenses = raw_materials + supplier_extra + operator_paid + other_exp
        net_profit = order_income - total_expenses

        # ---- income breakdown, each type drilled down by order ----
        income_breakdown = {}
        for code, label in IncomeRecord.IncomeType.choices:
            recs = IncomeRecord.objects.filter(income_type=code).select_related("order")
            by_order = defaultdict(float)
            for r in recs:
                key = r.order.order_number if r.order_id else "— (unlinked)"
                by_order[key] += float(r.amount)
            income_breakdown[code] = {
                "label": label,
                "amount": round(sum(by_order.values()), 2),
                "orders": sorted(({"order": k, "amount": round(v, 2)} for k, v in by_order.items()),
                                 key=lambda x: -x["amount"]),
            }

        # ---- expense breakdown ----
        # raw materials, split fabric/accessory and grouped by supplier(+order)
        fabric_by_supplier, accessory_by_supplier = defaultdict(float), defaultdict(float)
        for i in PurchaseOrderItem.objects.filter(rate__isnull=False).select_related("purchase_order__vendor", "purchase_order__related_order"):
            po = i.purchase_order
            supplier = po.vendor.company_name if po.vendor_id else "—"
            order_no = po.related_order.order_number if po.related_order_id else "General stock"
            value = float(i.received_quantity * i.rate)
            bucket = fabric_by_supplier if i.material_type == "FABRIC" else accessory_by_supplier
            bucket[(supplier, order_no)] += value

        def _supplier_rows(bucket):
            agg = defaultdict(lambda: {"amount": 0.0, "orders": defaultdict(float)})
            for (supplier, order_no), v in bucket.items():
                agg[supplier]["amount"] += v
                agg[supplier]["orders"][order_no] += v
            return sorted(({"supplier": s, "amount": round(d["amount"], 2),
                            "orders": sorted(({"order": o, "amount": round(a, 2)} for o, a in d["orders"].items()), key=lambda x: -x["amount"])}
                           for s, d in agg.items()), key=lambda x: -x["amount"])

        fabric_rows, accessory_rows = _supplier_rows(fabric_by_supplier), _supplier_rows(accessory_by_supplier)
        fabric_total = round(sum(r["amount"] for r in fabric_rows), 2)
        accessory_total = round(sum(r["amount"] for r in accessory_rows), 2)

        # operator payments (PAID), grouped by operator -> order
        op_by_operator = defaultdict(lambda: {"amount": 0.0, "pieces": 0, "orders": defaultdict(lambda: {"amount": 0.0, "pieces": 0})})
        for oi in OperatorIncome.objects.filter(payment_status="PAID").select_related("operator"):
            name = oi.operator.name if oi.operator_id else "—"
            amt = float(oi.total_income or 0)
            pcs = int(oi.bundles_completed or 0)
            op_by_operator[name]["amount"] += amt
            op_by_operator[name]["pieces"] += pcs
        operator_rows = sorted(({"operator": n, "amount": round(d["amount"], 2), "pieces": d["pieces"]}
                                for n, d in op_by_operator.items()), key=lambda x: -x["amount"])

        # other expenses grouped by type/category
        other_rows = defaultdict(float)
        for e in ExpenseRecord.objects.all():
            cat = e.get_category_display() if e.category else "Other"
            other_rows[cat] += float(e.amount or 0)
        other_list = sorted(({"label": k, "amount": round(v, 2)} for k, v in other_rows.items()), key=lambda x: -x["amount"])

        expense_breakdown = {
            "raw_materials": {
                "amount": round(fabric_total + accessory_total, 2),
                "fabric": {"amount": fabric_total, "by_supplier": fabric_rows},
                "accessories": {"amount": accessory_total, "by_supplier": accessory_rows},
            },
            "operator_payments": {"amount": round(operator_paid, 2), "by_operator": operator_rows},
            "supplier_extra": {"amount": round(supplier_extra, 2)},
            "other_expenses": {"amount": round(other_exp, 2), "items": other_list},
        }

        # ---- per-order profitability + department costs (one pass) ----
        dept = {"store_fabric": 0.0, "store_accessory": 0.0, "production_labor": 0.0,
                "production_processing": 0.0, "finishing_transport": 0.0}
        orders_rows = []
        for order in Order.objects.exclude(status="CANCELLED").select_related("party"):
            c = _order_cost(order)
            if not (c["total"] or c["income"]):
                continue
            dept["store_fabric"] += float(c["fabric"])
            dept["store_accessory"] += float(c["accessory"])
            dept["production_labor"] += float(c["labor"])
            dept["production_processing"] += float(c["processing"])
            dept["finishing_transport"] += float(c["transport"])
            revenue, cost = _f(c["income"]), _f(c["total"])
            orders_rows.append({
                "order": order.order_number, "party": order.party.name if order.party_id else "—",
                "revenue": revenue, "cost": cost, "profit": round(revenue - cost, 2),
                "margin": round((revenue - cost) / revenue * 100, 1) if revenue else None,
                "status": order.status,
            })
        orders_rows.sort(key=lambda r: r["profit"])
        department_costs = {
            "store": {"total": round(dept["store_fabric"] + dept["store_accessory"], 2),
                      "fabric": round(dept["store_fabric"], 2), "accessories": round(dept["store_accessory"], 2)},
            "cutting": {"total": 0.0},
            "production": {"total": round(dept["production_labor"] + dept["production_processing"], 2),
                           "operator_payments": round(dept["production_labor"], 2),
                           "processing": round(dept["production_processing"], 2)},
            "finishing": {"total": round(dept["finishing_transport"], 2),
                          "transport": round(dept["finishing_transport"], 2)},
        }

        # ---- per-product profitability (reuse product P&L compute) ----
        product_rows = [product_pnl._row(g) for g in product_pnl.compute().values()]
        product_rows = [r for r in product_rows if r["units"] or r["revenue"] or r["cogs"]]
        product_rows.sort(key=lambda r: -r["profit"])
        products = [{"product": f'{r["name"]}', "code": r["code"], "units": r["units"],
                     "revenue": r["revenue"], "cogs": r["cogs"], "profit": r["profit"], "margin": r["margin"]}
                    for r in product_rows]

        # ---- cash position: receivable by party, payable by supplier ----
        from apps.master_data.models import Party, Vendor
        receivable = []
        for p in Party.objects.all():
            billed = float(CustomerInvoice.objects.filter(order__party=p).aggregate(s=Sum("amount"))["s"] or 0)
            if not billed:
                billed = float(Order.objects.filter(party=p).exclude(status="CANCELLED").aggregate(s=Sum("total_order_amount"))["s"] or 0)
            received = float(IncomeRecord.objects.filter(order__party=p).aggregate(s=Sum("amount"))["s"] or 0)
            out = round(max(billed - received, 0), 2)
            if out > 0:
                receivable.append({"party": p.name, "amount": out})
        receivable.sort(key=lambda x: -x["amount"])
        payable = []
        for v in Vendor.objects.all():
            invs = list(Invoice.objects.filter(vendor=v))
            billed = float(sum((iv.total_amount for iv in invs), Decimal("0")))
            paid = 0.0
            for iv in invs:
                last = iv.payment_records.order_by("-id").first()
                paid += float(last.paid_amount) if last else 0.0
            due = round(max(billed - paid, 0), 2)
            if due > 0:
                payable.append({"supplier": v.company_name, "amount": due})
        payable.sort(key=lambda x: -x["amount"])
        total_receivable = round(sum(r["amount"] for r in receivable), 2)
        total_payable = round(sum(p["amount"] for p in payable), 2)

        # ---- system-wide KPIs ----
        kpis = self._kpis()

        return Response({
            "totals": {
                "total_income": round(order_income, 2),
                "total_expenses": round(total_expenses, 2),
                "net_profit": round(net_profit, 2),
                "cash_position": round(net_profit, 2),
            },
            "income_breakdown": income_breakdown,
            "expense_breakdown": expense_breakdown,
            "department_costs": department_costs,
            "orders": orders_rows,
            "products": products,
            "cash_position": {
                "receivable": {"total": total_receivable, "by_party": receivable},
                "payable": {"total": total_payable, "by_supplier": payable},
                "net": round(total_receivable - total_payable, 2),
            },
            "kpis": kpis,
        })

    def _kpis(self):
        from apps.finishing.models import FinishingQualityCheck
        from apps.cutting.models import CuttingOrder
        from apps.operators.models import Operator
        from django.contrib.auth import get_user_model

        assigns = list(BundleAssignment.objects.all())
        issued = sum(int(a.issued_quantity or 0) for a in assigns)
        returned_done = sum(int(a.returned_quantity or 0) for a in assigns
                            if a.status in (BundleAssignment.Status.COMPLETED, BundleAssignment.Status.QUALITY_CHECKED))
        defects = sum(int(getattr(a, "defects", 0) or 0) for a in assigns)
        eff = round((sum(int(a.returned_quantity or 0) for a in assigns) - defects) / issued * 100, 1) if issued else None

        used = float(CuttingOrder.objects.aggregate(s=Sum("fabric_used_quantity"))["s"] or 0)
        waste = float(CuttingOrder.objects.aggregate(s=Sum("wastage_quantity"))["s"] or 0)
        wastage_pct = round(waste / (used + waste) * 100, 1) if (used + waste) else 0

        fin_rejected = int(FinishingQualityCheck.objects.aggregate(s=Sum("quantity_rejected"))["s"] or 0)
        User = get_user_model()

        total_orders = Order.objects.exclude(status="CANCELLED").count()
        dispatched = Order.objects.filter(status__in=Order.DISPATCHED_OR_BEYOND).count()
        cancelled = Order.objects.filter(status="CANCELLED").count()
        in_progress = Order.objects.filter(status__in=[
            Order.Status.CONFIRMED, Order.Status.IN_CUTTING, Order.Status.IN_PRODUCTION, Order.Status.IN_FINISHING,
        ]).count()

        return {
            "production": {
                "pieces_produced": returned_done,
                "efficiency": eff,
                "wastage_pct": wastage_pct,
                "pending_dispatch": Order.objects.filter(status=Order.Status.IN_FINISHING).count(),
            },
            "quality_people": {
                "rejects": defects + fin_rejected,
                "active_operators": Operator.objects.filter(is_active=True).count(),
                "employees": User.objects.count(),
            },
            "pipeline": {
                "total_orders": total_orders, "dispatched": dispatched,
                "in_progress": in_progress, "cancelled": cancelled,
            },
        }
