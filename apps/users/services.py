from .models import User, Notification


def notify_role(role, message, link=""):
    """Creates one Notification per active user with the given role --
    used at department handoff points (bundle sent to Production, a
    shortage pending review, an order sent to Finishing, etc.)."""
    recipients = User.objects.filter(role=role, is_active=True, is_active_employee=True)
    Notification.objects.bulk_create([
        Notification(recipient=user, message=message, link=link) for user in recipients
    ])


def notify_store_roll_assigned(order, rolls):
    """Tell Store each fabric roll now assigned to `order`. The link deep-links
    into Store > Stock > Fabric with the roll highlighted and the Issue-to-
    Cutting modal pre-filled for the order, so it's a one-click hand-off.
    Works for both paths: rolls picked during order creation, and customer-
    supplied rolls received against an existing order (PO.related_order)."""
    for roll in rolls:
        label = getattr(roll, "roll_number", "") or f"Roll #{roll.id}"
        fab = roll.fabric_type.name if roll.fabric_type_id else ""
        col = roll.color.name if roll.color_id else ""
        notify_role(
            "STORE_MANAGER",
            f"New roll assignment: {label} ({fab}{'/' + col if col else ''}) assigned to Order {order.order_number}.",
            link=f"/store/stock/?action=issue&roll={roll.id}&order={order.id}&highlight=true",
        )
