"""Shared operator-payment resolution, used both by OperatorIncome.calculate
and the per-order P&L view in apps.finance -- kept in one place so "what an
operator earns" is never computed two different ways that can drift.

Operators are paid strictly on the per-piece rate Production sets on the
bundle assignment (BundleAssignment.rate_per_piece) when it allocates the
bundle to the operator, times the pieces the operator actually
returned/accepted. The rate is agreed per allocation, so two operators
working the same order can be paid different per-piece rates."""
from decimal import Decimal


def order_piece_rate(assignment):
    """The agreed operator payment per finished piece for this assignment,
    set by Production at allocation time (BundleAssignment.rate_per_piece).
    Returns Decimal('0') when no rate was recorded on the assignment."""
    if assignment.rate_per_piece is not None:
        return Decimal(assignment.rate_per_piece)
    return Decimal("0")


def assignment_labor_cost(assignment):
    """rate_per_piece x pieces the operator returned (accepted output)."""
    pieces = assignment.returned_quantity or 0
    return order_piece_rate(assignment) * Decimal(pieces)


def order_piece_breakdown(order_id, cap_total=None):
    """Size/colour breakdown of the pieces an order produced (accepted operator
    output), for Finishing's receive + QC screens. Returns totals plus a
    colour×size grid, computed from the completed bundle assignments.

    `cap_total` reconciles the breakdown to the quantity Finishing actually
    received (e.g. Production stitched 723 but only 720 came back from washing).
    When it is set and lower than what was produced, the process loss is spread
    across the largest colour/size cells so the grid, by_size, by_color and
    total all sum to the received figure -- the QC screen then works on the 720
    physically in hand, not the 723 that were originally stitched."""
    from collections import defaultdict
    from .models import BundleAssignment
    cell, meta = defaultdict(int), {}
    if order_id:
        qs = BundleAssignment.objects.filter(
            bundle__cutting_order__order_id=order_id,
            status__in=[BundleAssignment.Status.COMPLETED, BundleAssignment.Status.QUALITY_CHECKED],
            returned_quantity__isnull=False,
        ).select_related("bundle__color", "bundle__size")
        for a in qs:
            b = a.bundle
            key = (b.color_id, b.size_id)
            cell[key] += a.returned_quantity or 0
            meta[key] = (b.color.name if b.color_id else "—", b.size.name if b.size_id else "—")

    produced_total = sum(cell.values())
    process_loss = 0
    if cap_total is not None and 0 <= cap_total < produced_total:
        process_loss = produced_total - cap_total
        remaining = process_loss
        # Deduct the loss one piece at a time from the largest cells first,
        # cycling until it's fully accounted for.
        keys = sorted(cell.keys(), key=lambda k: cell[k], reverse=True)
        while remaining > 0 and any(cell[k] > 0 for k in keys):
            for k in keys:
                if remaining == 0:
                    break
                if cell[k] > 0:
                    cell[k] -= 1
                    remaining -= 1

    by_size, by_color = defaultdict(int), defaultdict(int)
    for (cid, sid), q in cell.items():
        cname, sname = meta[(cid, sid)]
        by_size[sname] += q
        by_color[cname] += q
    grid = [{"color_id": cid, "size_id": sid, "color": meta[(cid, sid)][0],
             "size": meta[(cid, sid)][1], "quantity": q}
            for (cid, sid), q in cell.items() if q > 0]
    grid.sort(key=lambda r: (r["color"], r["size"]))
    return {"total": sum(by_size.values()), "produced": produced_total,
            "process_loss": process_loss, "by_size": dict(by_size),
            "by_color": dict(by_color), "grid": grid}
