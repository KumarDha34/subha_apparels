from .models import User, Notification


def notify_role(role, message, link=""):
    """Creates one Notification per active user with the given role --
    used at department handoff points (bundle sent to Production, a
    shortage pending review, an order sent to Finishing, etc.)."""
    recipients = User.objects.filter(role=role, is_active=True, is_active_employee=True)
    Notification.objects.bulk_create([
        Notification(recipient=user, message=message, link=link) for user in recipients
    ])
