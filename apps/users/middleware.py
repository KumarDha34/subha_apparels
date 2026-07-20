"""Automatic activity logging.

Records one ActivityLog row for every successful *mutating* API request
(POST/PUT/PATCH/DELETE). Because this project authenticates with JWTs (which
DRF resolves inside the view, not in Django's session middleware), the
middleware decodes the bearer token itself to find the acting user.
"""
from django.utils import timezone

# Path segment -> human noun.
RESOURCE_NOUNS = {
    "orders": "order",
    "cutting-orders": "cutting order", "pieces": "cutting pieces", "bundles": "bundle", "markers": "marker",
    "receipts": "bundle receipt", "quality-checks": "quality check",
    "accessory-issues": "accessory issue", "bundle-accessory-issues": "accessory allocation",
    "assignments": "bundle assignment", "operators": "operator", "rates": "operator rate", "income": "operator income",
    "purchase-orders": "purchase order", "invoices": "invoice", "payments": "payment",
    "expenses": "expense", "fabric-stock": "fabric stock", "accessory-stock": "accessory stock",
    "transactions": "stock transaction", "operations": "finishing operation", "dispatch": "dispatch",
    "parties": "party", "products": "product", "colors": "color", "sizes": "size",
    "fabric-types": "fabric type", "accessories": "accessory", "vendors": "vendor",
    "product-components": "product component", "": "user", "send-to-finishing": "hand-off to finishing",
}
# Action suffix (a trailing non-numeric path segment) -> verb phrase.
ACTION_VERBS = {
    "confirm": "Confirmed", "cancel": "Cancelled", "receive": "Received", "pay": "Paid",
    "record_cut": "Recorded the cut for", "start_cutting": "Started cutting", "approve_override": "Reviewed cut override for",
    "return_fabric": "Returned fabric for", "send_to_production": "Sent to Production", "start": "Started",
    "return": "Returned", "return_bundle": "Returned", "quality_check": "Quality-checked",
    "review_shortage": "Reviewed shortage for", "reassign": "Reassigned", "calculate": "Calculated income for",
    "mark_paid": "Marked paid", "add-cost": "Added a cost to", "return_unused": "Returned unused",
    "change_password": "Changed their password", "admin_reset_password": "Reset a password",
}
# App segment -> department label.
DEPARTMENTS = {
    "orders": "Merchandising", "master": "Master Data", "store": "Store", "cutting": "Cutting",
    "operators": "Production", "production": "Production", "finishing": "Finishing",
    "accounts": "Accounts", "users": "Admin",
}

SKIP_PREFIXES = ("/api/auth/", "/api/users/notifications/", "/api/activity-logs")


def _describe(method, path):
    parts = [p for p in path.replace("/api/", "", 1).split("/") if p]
    if not parts:
        return "Performed an action", ""
    department = DEPARTMENTS.get(parts[0], "")
    # Nested resource lives at parts[1] for module apps (store/cutting/…), else parts[0].
    resource_seg = parts[1] if len(parts) > 1 and parts[0] in DEPARTMENTS and parts[0] != "orders" else parts[0]
    noun = RESOURCE_NOUNS.get(resource_seg, resource_seg.replace("-", " "))

    last = parts[-1]
    if last and not last.isdigit() and last in ACTION_VERBS:
        verb = ACTION_VERBS[last]
        # verbs that already read as a full sentence
        if last in ("change_password",):
            return verb, department
        return f"{verb} {noun}".strip(), department

    verb = {"POST": "Created", "PUT": "Updated", "PATCH": "Updated", "DELETE": "Deleted"}.get(method, "Changed")
    return f"{verb} {noun}", department


class ActivityLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._log(request, response)
        except Exception:
            pass  # logging must never break the request
        return response

    def _log(self, request, response):
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return
        if not request.path.startswith("/api/"):
            return
        if not (200 <= getattr(response, "status_code", 500) < 300):
            return
        if any(request.path.startswith(p) for p in SKIP_PREFIXES):
            return

        from rest_framework_simplejwt.authentication import JWTAuthentication
        result = JWTAuthentication().authenticate(request)
        if not result:
            return
        user, _ = result

        from .models import ActivityLog
        action, department = _describe(request.method, request.path)
        ActivityLog.objects.create(
            user=user, user_name=(user.get_full_name() or user.username), role=user.role,
            action=action, department=department, method=request.method, path=request.path[:255],
        )
