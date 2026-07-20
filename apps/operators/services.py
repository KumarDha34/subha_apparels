"""Shared operator-payment resolution, used both by OperatorIncome.calculate
and the per-order P&L view in apps.finance -- kept in one place so "what an
operator earns" is never computed two different ways that can drift.

Operators are paid strictly on the per-piece rate the Merchandiser sets on
the order line (OrderItem.price_per_piece) when the order is created, times
the pieces the operator actually returned/accepted. The rate is a property
of the *work* (the order), not of the operator -- so any operator who
stitches a given order line earns the same agreed rate per piece."""
from decimal import Decimal
from .models import OperatorRate


def order_piece_rate(assignment):
    """The agreed operator payment per finished piece for this assignment,
    read from the order line (OrderItem.price_per_piece) that the bundle
    belongs to. Returns Decimal('0') when the bundle can't be traced back to
    an order line (e.g. legacy cut with no order_item link)."""
    cutting_order = assignment.bundle.cutting_order
    order_item = cutting_order.order_item if cutting_order and cutting_order.order_item_id else None
    if order_item and order_item.price_per_piece is not None:
        return Decimal(order_item.price_per_piece)
    return Decimal("0")


def assignment_labor_cost(assignment):
    """price_per_piece x pieces the operator returned (accepted output)."""
    pieces = assignment.returned_quantity or 0
    return order_piece_rate(assignment) * Decimal(pieces)


def resolve_operator_rates(operator, product, order, as_of_date):
    """Returns {"PER_BUNDLE": rate_amount_or_None, "PER_PIECE": rate_amount_or_None}.
    Each rate_type is resolved independently, in precedence order:
    1. An order-specific rate (operator+order+rate_type; order-specific
       rates are always created with product=None, so there's no
       product-vs-order ambiguity to resolve).
    2. A product-specific rate (operator+product+rate_type, order=None).
    3. A general fallback rate (operator+rate_type, product=None, order=None).
    Each step filters is_active=True, effective_date<=as_of_date, ordered
    -effective_date then -id (explicit tiebreaker for same-day rows)."""
    result = {}
    for rate_type, _label in OperatorRate.RateType.choices:
        base = OperatorRate.objects.filter(
            operator=operator, rate_type=rate_type, is_active=True, effective_date__lte=as_of_date,
        ).order_by("-effective_date", "-id")
        rate = (
            base.filter(order=order).first() if order else None
        ) or (
            base.filter(product=product, order__isnull=True).first() if product else None
        ) or (
            base.filter(product__isnull=True, order__isnull=True).first()
        )
        result[rate_type] = rate.rate_amount if rate else None
    return result
