"""Product-wise profitability: revenue and full cost-of-goods attributed to
each product across every order, with by-order / by-customer / by-size /
by-colour breakdowns. No new models -- everything is derived from existing data.

Attribution rule: an order's pooled costs (fabric, accessory, processing,
additional charges) and its invoice revenue are split across the products in
that order by each product's share of the order's produced pieces. Labour is
attributed exactly (each bundle assignment already knows its product)."""
from decimal import Decimal
from collections import defaultdict

from rest_framework.views import APIView
from rest_framework.response import Response

from apps.users.permissions import HasRole


def _f(x):
    return float(x or 0)


def _img(p):
    if getattr(p, "image", None):
        try:
            return p.image.url
        except Exception:
            pass
    return p.image_url or None


def compute(only_product_id=None):
    from apps.master_data.models import Product
    from apps.orders.models import Order
    from apps.operators.models import BundleAssignment
    from apps.operators.services import assignment_labor_cost
    from apps.production.models import ProcessDispatch
    from apps.finance.models import CustomerInvoice, PurchaseOrderItem
    from apps.store.models import OrderAdditionalCharge

    # ---- produced pieces + labour per (order, product); size/colour per product ----
    op_pieces = defaultdict(lambda: defaultdict(int))     # order -> product -> pcs
    op_labour = defaultdict(lambda: defaultdict(Decimal)) # order -> product -> labour
    prod_size = defaultdict(lambda: defaultdict(int))     # product -> size -> pcs
    prod_color = defaultdict(lambda: defaultdict(int))    # product -> colour -> pcs

    for a in (BundleAssignment.objects.filter(status__in=["COMPLETED", "QUALITY_CHECKED"])
              .select_related("bundle__cutting_order__order_item__product", "bundle__cutting_order__order",
                              "bundle__size", "bundle__color")):
        co = a.bundle.cutting_order
        oi = co.order_item if co else None
        if not oi or not oi.product_id or not (co and co.order_id):
            continue
        pid = oi.product_id
        pcs = a.returned_quantity or 0
        op_pieces[co.order_id][pid] += pcs
        op_labour[co.order_id][pid] += assignment_labor_cost(a)
        prod_size[pid][a.bundle.size.name if a.bundle.size_id else "—"] += pcs
        prod_color[pid][a.bundle.color.name if a.bundle.color_id else "—"] += pcs

    # ---- per-order pooled cost + invoice revenue ----
    order_invoice = defaultdict(Decimal)
    for inv in CustomerInvoice.objects.all():
        if inv.order_id:
            order_invoice[inv.order_id] += inv.amount
    order_fabric, order_accessory = defaultdict(Decimal), defaultdict(Decimal)
    for it in (PurchaseOrderItem.objects.filter(purchase_order__related_order__isnull=False, rate__isnull=False)
               .select_related("purchase_order")):
        oid = it.purchase_order.related_order_id
        amt = Decimal(it.received_quantity or 0) * Decimal(it.rate or 0)
        if it.material_type == "FABRIC":
            order_fabric[oid] += amt
        elif it.material_type == "ACCESSORY":
            order_accessory[oid] += amt
    order_processing = defaultdict(Decimal)
    for pd in ProcessDispatch.objects.all():
        if pd.order_id and pd.cost:
            order_processing[pd.order_id] += pd.cost
    order_charges = defaultdict(Decimal)
    for ch in OrderAdditionalCharge.objects.all():
        order_charges[ch.order_id] += ch.amount

    orders = {o.id: o for o in Order.objects.select_related("party").all()}
    products = Product.objects.all()
    if only_product_id:
        products = products.filter(pk=only_product_id)
    products = {p.id: p for p in products}

    agg = {}
    for pid, p in products.items():
        agg[pid] = {
            "id": pid, "code": p.code, "name": p.name, "image": _img(p),
            "product_type": p.product_type, "category": p.category, "is_active": p.is_active,
            "units": 0, "revenue": Decimal("0"),
            "fabric": Decimal("0"), "accessory": Decimal("0"), "labour": Decimal("0"),
            "processing": Decimal("0"), "charges": Decimal("0"),
            "orders": [], "customers": defaultdict(lambda: {"qty": 0, "revenue": Decimal("0"), "cost": Decimal("0"), "orders": set()}),
        }

    # ---- split each order across its products ----
    for oid, prod_pcs in op_pieces.items():
        total = sum(prod_pcs.values())
        if not total:
            continue
        o = orders.get(oid)
        party = o.party.name if (o and o.party_id) else "—"
        onum = o.order_number if o else str(oid)
        inv, fab, acc = order_invoice[oid], order_fabric[oid], order_accessory[oid]
        proc, chg = order_processing[oid], order_charges[oid]
        for pid, pcs in prod_pcs.items():
            if pid not in agg:
                continue
            share = Decimal(pcs) / Decimal(total)
            revenue = inv * share
            fabric = fab * share
            accessory = acc * share
            processing = proc * share
            charges = chg * share
            labour = op_labour[oid][pid]
            cost = fabric + accessory + labour + processing + charges
            g = agg[pid]
            g["units"] += pcs
            g["revenue"] += revenue
            g["fabric"] += fabric
            g["accessory"] += accessory
            g["labour"] += labour
            g["processing"] += processing
            g["charges"] += charges
            g["orders"].append({"order_number": onum, "customer": party, "qty": pcs,
                                "revenue": _f(revenue), "cost": _f(cost), "profit": _f(revenue - cost),
                                "margin": round(_f(revenue - cost) / _f(revenue) * 100, 1) if revenue else 0})
            c = g["customers"][party]
            c["qty"] += pcs; c["revenue"] += revenue; c["cost"] += cost; c["orders"].add(oid)

    # attach size/colour
    for pid, g in agg.items():
        g["by_size"] = dict(prod_size.get(pid, {}))
        g["by_color"] = dict(prod_color.get(pid, {}))
    return agg


def _row(g):
    cogs = g["fabric"] + g["accessory"] + g["labour"] + g["processing"] + g["charges"]
    profit = g["revenue"] - cogs
    return {
        "id": g["id"], "code": g["code"], "name": g["name"], "image": g["image"],
        "product_type": g["product_type"], "category": g["category"], "is_active": g["is_active"],
        "units": g["units"], "revenue": _f(g["revenue"]), "cogs": _f(cogs), "profit": _f(profit),
        "margin": round(_f(profit) / _f(g["revenue"]) * 100, 1) if g["revenue"] else 0,
        "status": "Profitable" if profit > 0 else ("Loss-making" if profit < 0 else "Break-even"),
        "avg_price": round(_f(g["revenue"]) / g["units"], 2) if g["units"] else 0,
        "avg_cost": round(_f(cogs) / g["units"], 2) if g["units"] else 0,
    }


class ProductPnLListView(APIView):
    """GET /api/accounts/product-pnl/ -- every product's revenue, COGS, profit, margin."""
    permission_classes = [HasRole]
    required_roles = ["ADMIN", "ACCOUNTS"]

    def get(self, request):
        rows = [_row(g) for g in compute().values()]
        rows = [r for r in rows if r["units"] or r["revenue"] or r["cogs"]]
        rows.sort(key=lambda r: -r["profit"])
        return Response({
            "summary": {
                "products": len(rows),
                "revenue": round(sum(r["revenue"] for r in rows), 2),
                "cogs": round(sum(r["cogs"] for r in rows), 2),
                "profit": round(sum(r["profit"] for r in rows), 2),
                "margin": round(sum(r["profit"] for r in rows) / sum(r["revenue"] for r in rows) * 100, 1)
                          if sum(r["revenue"] for r in rows) else 0,
            },
            "products": rows,
        })


class ProductPnLDetailView(APIView):
    """GET /api/accounts/product-pnl/<id>/ -- one product's full breakdown."""
    permission_classes = [HasRole]
    required_roles = ["ADMIN", "ACCOUNTS"]

    def get(self, request, pk):
        g = compute(only_product_id=pk).get(int(pk))
        if not g:
            return Response({"detail": "Product not found."}, status=404)
        base = _row(g)
        units = g["units"] or 1
        rev = g["revenue"]
        # by size / colour -> pieces + proportional revenue + profit
        cogs = Decimal(base["cogs"])
        def split(dic):
            out = []
            for k, pcs in sorted(dic.items()):
                r = rev * Decimal(pcs) / Decimal(units)
                c = cogs * Decimal(pcs) / Decimal(units)
                out.append({"key": k, "qty": pcs, "revenue": _f(r), "cost": _f(c), "profit": _f(r - c),
                            "margin": round(_f(r - c) / _f(r) * 100, 1) if r else 0,
                            "profit_per_unit": round(_f(r - c) / pcs, 2) if pcs else 0})
            return out
        customers = []
        for party, c in g["customers"].items():
            profit = c["revenue"] - c["cost"]
            customers.append({"customer": party, "orders": len(c["orders"]), "qty": c["qty"],
                              "revenue": _f(c["revenue"]), "cost": _f(c["cost"]), "profit": _f(profit),
                              "margin": round(_f(profit) / _f(c["revenue"]) * 100, 1) if c["revenue"] else 0})
        customers.sort(key=lambda x: -x["revenue"])
        return Response({
            **base,
            "costs": {
                "fabric": _f(g["fabric"]), "accessory": _f(g["accessory"]), "labour": _f(g["labour"]),
                "processing": _f(g["processing"]), "charges": _f(g["charges"]), "total": _f(cogs),
                "per_unit": {
                    "fabric": round(_f(g["fabric"]) / units, 2), "accessory": round(_f(g["accessory"]) / units, 2),
                    "labour": round(_f(g["labour"]) / units, 2), "processing": round(_f(g["processing"]) / units, 2),
                    "charges": round(_f(g["charges"]) / units, 2), "total": round(_f(cogs) / units, 2),
                },
            },
            "by_order": sorted(g["orders"], key=lambda x: -x["revenue"]),
            "by_customer": customers,
            "by_size": split(g["by_size"]),
            "by_color": split(g["by_color"]),
        })
