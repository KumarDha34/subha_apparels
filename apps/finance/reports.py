"""Admin reporting hub. Each report builder returns a self-describing payload
{title, description, columns, rows, summary} so a single generic frontend page
can render any of them. Everything is computed live from the database."""
from decimal import Decimal
from django.db.models import Sum, Count, F
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.users.permissions import IsAdmin


def _m(x):
    return float(x or 0)


def col(key, label, type=None):
    c = {"key": key, "label": label}
    if type:
        c["type"] = type
    return c


# ---------------------------------------------------------------- builders
def r_orders_products():
    from apps.orders.models import Order
    rows = []
    for o in Order.objects.select_related("party").prefetch_related("items__product", "items__colors__size_lines"):
        items = list(o.items.all())
        products = " · ".join(sorted({it.product.code for it in items if it.product_id}))
        qty = sum((sl.quantity or 0) for it in items for c in it.colors.all() for sl in c.size_lines.all())
        rows.append({"order": o.order_number, "party": o.party.name if o.party_id else "—",
                     "products": products or "—", "type": o.order_type.replace("_", " ").title(),
                     "qty": qty if o.order_type == "FIXED_QUANTITY" else "ratio",
                     "status": o.status, "date": str(o.order_date), "value": _m(o.total_order_amount)})
    return dict(title="Orders & Products", description="Every order with its products, quantity and value.",
                columns=[col("order", "Order"), col("party", "Party"), col("products", "Products"), col("type", "Type"),
                         col("qty", "Qty"), col("value", "Order Value", "money"), col("status", "Status", "badge"), col("date", "Date")],
                rows=rows)


def _product_rows():
    from apps.master_data.models import Product
    from apps.orders.models import OrderItemColorSize
    from apps.operators.models import BundleAssignment
    rows = []
    for p in Product.objects.all():
        ordered = OrderItemColorSize.objects.filter(order_item_color__order_item__product=p).aggregate(s=Sum("quantity"))["s"] or 0
        order_count = p.order_items.values("order").distinct().count()
        produced = BundleAssignment.objects.filter(
            bundle__cutting_order__order_item__product=p, status__in=["COMPLETED", "QUALITY_CHECKED"]
        ).aggregate(s=Sum("returned_quantity"))["s"] or 0
        rows.append({"code": p.code, "name": p.name, "description": p.description or "—",
                     "orders": order_count, "ordered": int(ordered), "produced": int(produced),
                     "remaining": max(int(ordered) - int(produced), 0),
                     "image_url": (p.image.url if p.image else p.image_url) or "", "measurements": p.measurement_chart or [],
                     "status": "ACTIVE" if p.is_active else "INACTIVE"})
    return rows


def r_style_master():
    return dict(title="Style Master", description="All product styles with codes and status.",
                columns=[col("code", "Code"), col("name", "Style Name"), col("description", "Description"),
                         col("orders", "Orders"), col("status", "Status", "badge")],
                rows=_product_rows())


def r_product_overview():
    rows = _product_rows()
    return dict(title="Product Overview", description="Per-style order and production volume — ordered, completed and remaining. Click Details for the image and measurement chart.",
                summary=[{"label": "Products", "value": len(rows)},
                         {"label": "Total Ordered", "value": sum(r["ordered"] for r in rows)},
                         {"label": "Total Produced", "value": sum(r["produced"] for r in rows), "kind": "success"},
                         {"label": "Total Remaining", "value": sum(r["remaining"] for r in rows), "kind": "warning"}],
                columns=[col("code", "Code"), col("name", "Style"), col("orders", "Orders"),
                         col("ordered", "Pieces Ordered"), col("produced", "Completed"), col("remaining", "Remaining"),
                         col("status", "Status", "badge")],
                rows=rows)


def r_product_gallery():
    rows = _product_rows()
    return dict(title="Product Gallery", description="Every style with its reference image and size-wise measurement chart.",
                layout="gallery",
                columns=[col("code", "Code"), col("name", "Style"), col("orders", "Orders"), col("produced", "Produced"), col("status", "Status", "badge")],
                rows=rows)


def r_product_pnl():
    from apps.operators.models import BundleAssignment
    from apps.operators.services import assignment_labor_cost
    agg = {}
    for a in BundleAssignment.objects.filter(status__in=["COMPLETED", "QUALITY_CHECKED"]).select_related("bundle__cutting_order__order_item__product"):
        oi = a.bundle.cutting_order.order_item if a.bundle.cutting_order else None
        if not oi or not oi.product_id:
            continue
        g = agg.setdefault(oi.product_id, {"code": oi.product.code, "name": oi.product.name, "pieces": 0, "labor": Decimal("0")})
        g["pieces"] += a.returned_quantity or 0
        g["labor"] += assignment_labor_cost(a)
    rows = [{"code": g["code"], "name": g["name"], "pieces": g["pieces"], "labor": float(g["labor"]),
             "avg": round(float(g["labor"]) / g["pieces"], 2) if g["pieces"] else 0} for g in agg.values()]
    return dict(title="Product P&L", description="Pieces produced and operator labour cost per style.",
                summary=[{"label": "Total Pieces", "value": sum(r["pieces"] for r in rows)},
                         {"label": "Total Labour", "value": sum(r["labor"] for r in rows), "kind": "warning"}],
                columns=[col("code", "Code"), col("name", "Style"), col("pieces", "Pieces"),
                         col("labor", "Operator Labour", "money"), col("avg", "Avg Rate/pc", "money")],
                rows=sorted(rows, key=lambda r: -r["pieces"]))


def r_cutting_entry():
    from apps.cutting.models import CuttingOrder
    rows = []
    for c in CuttingOrder.objects.select_related("order__party", "order_item__product", "fabric_issued__color", "fabric_issued__fabric_type"):
        rows.append({"cutting": c.cutting_number, "order": c.order.order_number if c.order_id else "—",
                     "party": c.order.party.name if c.order_id and c.order.party_id else "—",
                     "product": c.order_item.product.code if c.order_item_id else "—",
                     "fabric": f"{getattr(c.fabric_issued.fabric_type,'name','?')}/{getattr(c.fabric_issued.color,'name','?')}" if c.fabric_issued_id else "—",
                     "issued": _m(c.fabric_issued_quantity), "used": _m(c.fabric_used_quantity), "wastage": _m(c.wastage_quantity),
                     "pieces": c.total_pieces_cut or 0, "status": c.status})
    return dict(title="Cutting Entry", description="Every cutting order and its output.",
                columns=[col("cutting", "Cutting #"), col("order", "Order"), col("party", "Party"), col("product", "Product"),
                         col("fabric", "Fabric/Color"), col("issued", "Issued m"), col("used", "Used m"),
                         col("wastage", "Wastage m"), col("pieces", "Pieces"), col("status", "Status", "badge")],
                rows=rows)


def r_stitching_entry():
    from apps.operators.models import BundleAssignment
    from apps.operators.services import assignment_labor_cost
    rows = []
    for a in BundleAssignment.objects.select_related("bundle__cutting_order__order", "operator").order_by("-created_at"):
        co = a.bundle.cutting_order
        rows.append({"bundle": a.bundle.bundle_number, "operator": a.operator.name,
                     "order": co.order.order_number if (co and co.order_id) else "—",
                     "issued": a.issued_quantity or 0, "returned": a.returned_quantity if a.returned_quantity is not None else "—",
                     "defects": a.defects or 0, "status": a.status, "earned": float(assignment_labor_cost(a))})
    return dict(title="Stitching Entry", description="Every bundle stitched by operators.",
                columns=[col("bundle", "Bundle"), col("operator", "Operator"), col("order", "Order"),
                         col("issued", "Issued"), col("returned", "Returned"), col("defects", "Defects"),
                         col("status", "Status", "badge"), col("earned", "Earned", "money")],
                rows=rows)


def r_finishing_entry():
    from apps.finishing.models import FinishingQualityCheck
    from apps.production.models import ProcessDispatch
    rows = []
    for pd in ProcessDispatch.objects.select_related("order").order_by("-created_at"):
        rows.append({"ref": pd.dispatch_number, "order": pd.order.order_number if pd.order_id else "—",
                     "dept": pd.get_department_display(), "sent": pd.quantity_sent,
                     "received": pd.quantity_received if pd.quantity_received is not None else "—",
                     "loss": pd.loss_quantity, "status": pd.status})
    return dict(title="Finishing Entry", description="Processing dispatches (washing / printing / embroidery / finishing) and their returns.",
                columns=[col("ref", "Ref #"), col("order", "Order"), col("dept", "Department"), col("sent", "Sent"),
                         col("received", "Received"), col("loss", "Loss"), col("status", "Status", "badge")],
                rows=rows)


def r_store_entry():
    from apps.store.models import StockTransaction
    rows = []
    for t in StockTransaction.objects.select_related("fabric_stock__color", "fabric_stock__fabric_type").order_by("-created_at")[:400]:
        fs = t.fabric_stock
        rows.append({"date": str(t.transaction_date), "type": t.transaction_type,
                     "fabric": f"{getattr(fs.fabric_type,'name','?')}/{getattr(fs.color,'name','?')}" if fs else "—",
                     "qty": _m(t.quantity), "reference": t.reference or "—"})
    return dict(title="Store Entry", description="Fabric stock ledger — receipts, issues, wastage, returns.",
                columns=[col("date", "Date"), col("type", "Type", "badge"), col("fabric", "Fabric/Color"),
                         col("qty", "Quantity"), col("reference", "Reference")],
                rows=rows)


def r_operator_overview():
    from apps.operators.models import Operator, BundleAssignment
    from apps.operators.services import assignment_labor_cost
    rows = []
    for op in Operator.objects.all():
        asg = list(op.assignments.all())
        issued = sum((a.issued_quantity or 0) for a in asg)
        returned = sum((a.returned_quantity or 0) for a in asg)
        defects = sum((a.defects or 0) for a in asg)
        earned = sum((assignment_labor_cost(a) for a in asg if a.status in ("COMPLETED", "QUALITY_CHECKED")), Decimal("0"))
        rows.append({"id": op.id, "operator": op.name, "skill": op.skill_level or "—", "bundles": len(asg),
                     "issued": issued, "returned": returned, "defects": defects,
                     "efficiency": round((returned - defects) / issued * 100, 1) if issued else 0,
                     "earned": float(earned), "status": "ACTIVE" if op.is_active else "INACTIVE"})
    return dict(title="Operator Overview", description="Every operator's workload, efficiency and earnings. Click a name for the full profile.",
                row_action="operator",
                columns=[col("operator", "Operator", "operator"), col("skill", "Skill"), col("bundles", "Bundles"),
                         col("issued", "Issued"), col("returned", "Returned"), col("defects", "Defects"),
                         col("efficiency", "Efficiency", "pct"), col("earned", "Earned", "money"), col("status", "Status", "badge")],
                rows=rows)


def r_quality_report():
    from apps.orders.models import Order
    from apps.operators.models import BundleAssignment
    from apps.finishing.models import FinishingQualityCheck
    rows = []
    for o in Order.objects.select_related("party").exclude(status="CANCELLED"):
        defects = BundleAssignment.objects.filter(bundle__cutting_order__order=o).aggregate(s=Sum("defects"))["s"] or 0
        qc = FinishingQualityCheck.objects.filter(order=o).aggregate(c=Sum("quantity_checked"), p=Sum("quantity_passed"), a=Sum("quantity_altered"), r=Sum("quantity_rejected"))
        checked = qc["c"] or 0
        rejected = qc["r"] or 0
        rows.append({"order": o.order_number, "party": o.party.name if o.party_id else "—",
                     "defects": int(defects), "checked": int(checked), "passed": int(qc["p"] or 0),
                     "altered": int(qc["a"] or 0), "rejected": int(rejected),
                     "reject_pct": round(rejected / checked * 100, 1) if checked else 0})
    return dict(title="Quality Report", description="Stitching defects and finishing QC (pass / alter / fail) per order.",
                summary=[{"label": "Stitching Defects", "value": sum(r["defects"] for r in rows), "kind": "warning"},
                         {"label": "Finishing Rejects", "value": sum(r["rejected"] for r in rows), "kind": "danger"}],
                columns=[col("order", "Order"), col("party", "Party"), col("defects", "Stitch Defects"),
                         col("checked", "QC Checked"), col("passed", "Passed"), col("altered", "Altered"),
                         col("rejected", "Failed"), col("reject_pct", "Reject %", "pct")],
                rows=rows)


def r_fabric_wastage():
    from apps.cutting.models import CuttingOrder
    rows = []
    for c in CuttingOrder.objects.select_related("order", "fabric_issued__color", "fabric_issued__fabric_type"):
        used = _m(c.fabric_used_quantity)
        w = _m(c.wastage_quantity)
        base = used + w
        rows.append({"cutting": c.cutting_number, "order": c.order.order_number if c.order_id else "—",
                     "fabric": f"{getattr(c.fabric_issued.fabric_type,'name','?')}/{getattr(c.fabric_issued.color,'name','?')}" if c.fabric_issued_id else "—",
                     "issued": _m(c.fabric_issued_quantity), "used": used, "wastage": w,
                     "wastage_pct": round(w / base * 100, 1) if base else 0})
    tot_w = sum(r["wastage"] for r in rows)
    tot_u = sum(r["used"] for r in rows)
    return dict(title="Fabric Wastage", description="Wastage per cutting order and overall.",
                summary=[{"label": "Total Wastage (m)", "value": round(tot_w, 1), "kind": "warning"},
                         {"label": "Overall Wastage %", "value": (round(tot_w / (tot_u + tot_w) * 100, 1) if (tot_u + tot_w) else 0), "kind": "warning"}],
                columns=[col("cutting", "Cutting #"), col("order", "Order"), col("fabric", "Fabric/Color"),
                         col("issued", "Issued m"), col("used", "Used m"), col("wastage", "Wastage m"), col("wastage_pct", "Wastage %", "pct")],
                rows=rows)


def r_dispatch_balance():
    from apps.orders.models import Order, OrderItemColorSize
    from apps.finishing.models import Dispatch
    from apps.finance.models import IncomeRecord
    from apps.store.models import FinishedGoodsReceipt
    rows = []
    for o in Order.objects.select_related("party").exclude(status="CANCELLED"):
        ordered = OrderItemColorSize.objects.filter(order_item_color__order_item__order=o).aggregate(s=Sum("quantity"))["s"] or 0
        d = Dispatch.objects.filter(order=o).first()
        dispatched = (d.quantity_dispatched or 0) if d else 0
        in_store = FinishedGoodsReceipt.objects.filter(order=o).aggregate(s=Sum("quantity"))["s"] or 0
        income = IncomeRecord.objects.filter(order=o).aggregate(s=Sum("amount"))["s"] or 0
        rows.append({"order": o.order_number, "party": o.party.name if o.party_id else "—",
                     "ordered": int(ordered), "dispatched": int(dispatched), "in_store": int(in_store),
                     "balance": max(int(ordered) - int(dispatched), 0), "value": _m(o.total_order_amount),
                     "received": _m(income), "receivable": max(_m(o.total_order_amount) - _m(income), 0),
                     "status": o.status})
    return dict(title="Dispatch & Balance", description="Ordered vs dispatched pieces, finished goods logged into Store, and money received vs receivable.",
                columns=[col("order", "Order"), col("party", "Party"), col("ordered", "Ordered"), col("dispatched", "Dispatched"),
                         col("in_store", "In Store (Finished)"),
                         col("balance", "Balance Pcs"), col("value", "Order Value", "money"), col("received", "Received", "money"),
                         col("receivable", "Receivable", "money"), col("status", "Status", "badge")],
                rows=rows)


def r_party_ledger():
    from apps.master_data.models import Party
    from apps.orders.models import Order
    from apps.finance.models import IncomeRecord, CustomerInvoice
    detail_cols = [{"key": "order", "label": "Order"}, {"key": "date", "label": "Date"},
                   {"key": "value", "label": "Order Value", "type": "money"}, {"key": "received", "label": "Received", "type": "money"},
                   {"key": "outstanding", "label": "Outstanding", "type": "money"}, {"key": "status", "label": "Status"}]

    def order_billed(o):
        # The billed value is the sales invoice(s) raised for the order; fall
        # back to the order's own amount when it hasn't been invoiced yet.
        inv = CustomerInvoice.objects.filter(order=o).aggregate(s=Sum("amount"))["s"]
        return _m(inv) if inv else _m(o.total_order_amount)

    rows = []
    for p in Party.objects.all():
        orders = Order.objects.filter(party=p).exclude(status="CANCELLED").order_by("-order_date")
        received = IncomeRecord.objects.filter(order__party=p).aggregate(s=Sum("amount"))["s"] or 0
        detail, value = [], 0.0
        for o in orders:
            o_value = order_billed(o)
            value += o_value
            recv = IncomeRecord.objects.filter(order=o).aggregate(s=Sum("amount"))["s"] or 0
            detail.append({"order": o.order_number, "date": str(o.order_date), "value": o_value,
                           "received": _m(recv), "outstanding": max(o_value - _m(recv), 0), "status": o.status})
        rows.append({"id": p.id, "party": p.name, "orders": orders.count(), "value": value,
                     "received": _m(received), "outstanding": max(value - _m(received), 0),
                     "detail": detail, "detail_title": f"Orders for {p.name}", "detail_columns": detail_cols})
    return dict(title="Party Ledger", description="Per-buyer order value, money received and outstanding receivable. Click Details for every order.",
                summary=[{"label": "Total Receivable", "value": sum(r["outstanding"] for r in rows), "kind": "danger"}],
                columns=[col("party", "Party"), col("orders", "Orders"), col("value", "Order Value", "money"),
                         col("received", "Received", "money"), col("outstanding", "Outstanding", "money")],
                rows=rows)


def r_supplier_ledger():
    from apps.master_data.models import Vendor
    from apps.finance.models import Invoice
    rows = []
    detail_cols = [{"key": "invoice", "label": "Invoice"}, {"key": "date", "label": "Date"},
                   {"key": "total", "label": "Total", "type": "money"}, {"key": "paid", "label": "Paid", "type": "money"},
                   {"key": "due", "label": "Due", "type": "money"}, {"key": "status", "label": "Status"}]
    for v in Vendor.objects.all():
        invs = Invoice.objects.filter(vendor=v).order_by("-invoice_date")
        total = invs.aggregate(s=Sum("total_amount"))["s"] or 0
        paid = 0.0
        detail = []
        for inv in invs:
            latest = inv.payment_records.order_by("-id").first()
            ip = _m(latest.paid_amount) if latest else 0.0
            paid += ip
            detail.append({"invoice": inv.invoice_number, "date": str(inv.invoice_date), "total": _m(inv.total_amount),
                           "paid": ip, "due": max(_m(inv.total_amount) - ip, 0), "status": inv.payment_status})
        rows.append({"vendor": v.company_name, "invoices": invs.count(), "billed": _m(total),
                     "paid": paid, "due": max(_m(total) - paid, 0),
                     "detail": detail, "detail_title": f"Invoices from {v.company_name}", "detail_columns": detail_cols})
    return dict(title="Supplier Ledger", description="Per-supplier billed, paid and outstanding payable.",
                summary=[{"label": "Total Payable", "value": sum(r["due"] for r in rows), "kind": "danger"}],
                columns=[col("vendor", "Supplier"), col("invoices", "Invoices"), col("billed", "Billed", "money"),
                         col("paid", "Paid", "money"), col("due", "Due", "money")],
                rows=rows)


def r_purchase_bills():
    from apps.finance.models import Invoice
    detail_cols = [{"key": "material", "label": "Material"}, {"key": "qty", "label": "Qty"},
                   {"key": "rate", "label": "Rate", "type": "money"}, {"key": "total", "label": "Total", "type": "money"}]
    rows = []
    for inv in Invoice.objects.select_related("vendor", "purchase_order").order_by("-created_at"):
        detail = []
        if inv.purchase_order_id:
            for it in inv.purchase_order.items.all():
                detail.append({"material": it.item_name or "—", "qty": _m(it.quantity),
                               "rate": _m(it.rate), "total": _m(it.total)})
        rows.append({"invoice": inv.invoice_number, "vendor": inv.vendor.company_name if inv.vendor_id else "—",
                     "po": inv.purchase_order.po_number if inv.purchase_order_id else "—", "date": str(inv.invoice_date),
                     "total": _m(inv.total_amount), "status": inv.payment_status,
                     "detail": detail, "detail_title": "Bill line items", "detail_columns": detail_cols})
    return dict(title="Purchase Bills", description="Supplier invoices raised from received purchases.",
                columns=[col("invoice", "Invoice #"), col("vendor", "Supplier"), col("po", "PO #"),
                         col("date", "Date"), col("total", "Total", "money"), col("status", "Status", "badge")],
                rows=rows)


def r_invoices():
    d = r_purchase_bills()
    d["title"] = "Invoices"
    d["description"] = "All supplier invoices."
    return d


def r_quotations():
    from .models import Quotation
    rows = []
    for q in Quotation.objects.select_related("party", "product"):
        rows.append({"quote": q.quote_number, "party": q.party.name if q.party_id else "—",
                     "style": f"{q.product.code} — {q.product.name}" if q.product_id else "—",
                     "qty": q.quantity, "rate": _m(q.rate_per_piece), "value": _m(q.amount),
                     "valid_till": str(q.valid_till), "status": q.status})
    return dict(title="Quotations", description="Customer price quotes and their status.",
                columns=[col("quote", "Quote No."), col("party", "Buyer"), col("style", "Style"),
                         col("qty", "Qty"), col("rate", "Rate", "money"), col("value", "Amount", "money"),
                         col("valid_till", "Valid Till"), col("status", "Status", "badge")],
                rows=rows)


def r_employee_master():
    from apps.users.models import User
    from apps.operators.models import Operator
    rows = []
    for u in User.objects.all():
        rows.append({"name": u.get_full_name() or u.username, "kind": u.get_role_display(),
                     "contact": u.phone or u.email or "—", "status": "ACTIVE" if u.is_active else "INACTIVE"})
    for op in Operator.objects.all():
        rows.append({"name": op.name, "kind": f"Operator ({op.skill_level or '—'})",
                     "contact": op.contact or op.email or "—", "status": "ACTIVE" if op.is_active else "INACTIVE"})
    return dict(title="Employee Master", description="All logins and operators on record.",
                columns=[col("name", "Name"), col("kind", "Role / Type"), col("contact", "Contact"), col("status", "Status", "badge")],
                rows=rows)


def r_sales_pnl_cash():
    from apps.finance.models import IncomeRecord, Invoice, ExpenseRecord
    from apps.operators.models import OperatorIncome
    from apps.production.models import ProcessDispatch
    income = _m(IncomeRecord.objects.aggregate(s=Sum("amount"))["s"])
    raw = _m(Invoice.objects.aggregate(s=Sum("subtotal"))["s"])
    labour = _m(OperatorIncome.objects.aggregate(s=Sum("total_income"))["s"])
    finishing = _m(ProcessDispatch.objects.aggregate(s=Sum("cost"))["s"])
    overheads = _m(ExpenseRecord.objects.aggregate(s=Sum("amount"))["s"])
    expenses = raw + labour + finishing + overheads
    net = income - expenses
    operator_paid = _m(OperatorIncome.objects.aggregate(s=Sum("paid_amount"))["s"])
    supplier_paid = 0.0
    for inv in Invoice.objects.all():
        latest = inv.payment_records.order_by("-id").first()
        supplier_paid += _m(latest.paid_amount) if latest else 0.0
    cash = income - (supplier_paid + operator_paid + overheads)
    rows = [
        {"item": "Revenue received (buyers)", "amount": income},
        {"item": "Raw materials (fabric/accessories)", "amount": -raw},
        {"item": "Operator labour", "amount": -labour},
        {"item": "Finishing / processing", "amount": -finishing},
        {"item": "Overheads (rent/utilities/…)", "amount": -overheads},
        {"item": "Net profit / loss", "amount": net},
    ]
    return dict(title="Sales, P&L & Cash", description="Revenue, costs, profit and cash position.",
                summary=[{"label": "Revenue", "value": income, "kind": "success", "money": True},
                         {"label": "Expenses", "value": expenses, "money": True},
                         {"label": "Net Profit", "value": net, "kind": ("success" if net >= 0 else "danger"), "money": True},
                         {"label": "Cash Position", "value": cash, "kind": ("success" if cash >= 0 else "danger"), "money": True}],
                columns=[col("item", "Item"), col("amount", "Amount", "money")],
                rows=rows)


def r_activity_log():
    from apps.users.models import ActivityLog
    rows = [{"when": a.created_at.strftime("%Y-%m-%d %H:%M"), "who": a.user_name, "role": a.role,
             "department": a.department or "—", "action": a.action}
            for a in ActivityLog.objects.all()[:500]]
    return dict(title="Activity Log", description="Who did what, across every department.",
                columns=[col("when", "When"), col("who", "Who"), col("role", "Role"), col("department", "Department"), col("action", "Activity")],
                rows=rows)


def r_piece_loss():
    """Every piece accounted for: cut → operator → each process department →
    finishing QC → finally received, and exactly where the losses happened."""
    from apps.orders.models import Order
    from apps.cutting.models import CuttingOrder
    from apps.operators.models import BundleAssignment
    from apps.production.models import ProcessDispatch
    from apps.finishing.models import FinishingQualityCheck
    from apps.store.models import FinishedGoodsReceipt
    rows = []
    for o in Order.objects.select_related("party").exclude(status="CANCELLED"):
        cut = CuttingOrder.objects.filter(order=o).aggregate(s=Sum("total_pieces_cut"))["s"] or 0
        aq = BundleAssignment.objects.filter(
            bundle__cutting_order__order=o, returned_quantity__isnull=False)
        issued = aq.aggregate(s=Sum("issued_quantity"))["s"] or 0
        returned = aq.aggregate(s=Sum("returned_quantity"))["s"] or 0
        op_loss = max(int(issued) - int(returned), 0)
        dept = {"WASHING": 0, "PRINTING": 0, "EMBROIDERY": 0, "FINISHING": 0}
        for pd in ProcessDispatch.objects.filter(order=o):
            dept[pd.department] = dept.get(pd.department, 0) + pd.loss_quantity
        qc_reject = FinishingQualityCheck.objects.filter(order=o).aggregate(s=Sum("quantity_rejected"))["s"] or 0
        final = FinishedGoodsReceipt.objects.filter(order=o).aggregate(s=Sum("quantity"))["s"] or 0
        total_loss = op_loss + sum(dept.values()) + int(qc_reject)
        rows.append({"order": o.order_number, "party": o.party.name if o.party_id else "—",
                     "cut": int(cut), "operator_loss": op_loss, "washing": dept["WASHING"],
                     "printing": dept["PRINTING"], "embroidery": dept["EMBROIDERY"], "finishing_loss": dept["FINISHING"],
                     "qc_reject": int(qc_reject), "total_loss": total_loss, "final": int(final), "status": o.status})
    return dict(title="Piece Loss Tracking",
                description="Pieces cut vs finally received, and where every lost piece went — operator shortfall, washing, printing, embroidery, finishing, and QC rejects.",
                summary=[{"label": "Total Cut", "value": sum(r["cut"] for r in rows)},
                         {"label": "Total Lost", "value": sum(r["total_loss"] for r in rows), "kind": "warning"},
                         {"label": "Final Received", "value": sum(r["final"] for r in rows), "kind": "success"}],
                columns=[col("order", "Order"), col("party", "Party"), col("cut", "Cut"),
                         col("operator_loss", "Operator"), col("washing", "Washing"), col("printing", "Printing"),
                         col("embroidery", "Embroidery"), col("finishing_loss", "Finishing"), col("qc_reject", "QC Reject"),
                         col("total_loss", "Total Lost"), col("final", "Final Recv"), col("status", "Status", "badge")],
                rows=rows)


REPORTS = {
    "orders-products": r_orders_products, "style-master": r_style_master, "product-overview": r_product_overview,
    "piece-loss": r_piece_loss,
    "product-gallery": r_product_gallery, "product-pnl": r_product_pnl, "cutting-entry": r_cutting_entry,
    "stitching-entry": r_stitching_entry, "finishing-entry": r_finishing_entry, "store-entry": r_store_entry,
    "operator-overview": r_operator_overview, "quality-report": r_quality_report, "fabric-wastage": r_fabric_wastage,
    "dispatch-balance": r_dispatch_balance, "party-ledger": r_party_ledger, "supplier-ledger": r_supplier_ledger,
    "purchase-bills": r_purchase_bills, "invoices": r_invoices, "quotations": r_quotations,
    "employee-master": r_employee_master, "sales-pnl-cash": r_sales_pnl_cash, "activity-log": r_activity_log,
}


# Finance reports the Accounts role may open from its own dashboard.
ACCOUNTS_KEYS = {"quotations", "invoices", "party-ledger", "purchase-bills", "supplier-ledger", "sales-pnl-cash"}


class AdminReportView(APIView):
    """GET /api/accounts/report/?key=<report-key>. Admin sees every report;
    Accounts sees the finance-facing ones from its own dashboard."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        key = request.query_params.get("key")
        role = getattr(request.user, "role", None)
        is_admin = request.user.is_superuser or role == "ADMIN"
        if not is_admin and not (role == "ACCOUNTS" and key in ACCOUNTS_KEYS):
            return Response({"detail": "You don't have permission to view this report."}, status=403)
        builder = REPORTS.get(key)
        if not builder:
            return Response({"detail": "Unknown report.", "available": sorted(REPORTS)}, status=400)
        return Response(builder())
