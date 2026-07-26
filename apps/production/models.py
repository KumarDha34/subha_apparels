from django.db import models
from apps.master_data.models import TimeStampedModel
from apps.cutting.models import Bundle
from apps.orders.models import Order
from apps.store.models import AccessoryStock
from apps.operators.models import Operator


class AccessoryIssue(TimeStampedModel):
    """Store's hand-off of accessories (zipper/button/thread/etc.) to
    Production for a specific order. Mirrors CuttingOrder's role for fabric:
    creating this record is the issuance event itself (deducts stock via the
    standard ledger) -- see AccessoryIssueSerializer.create()."""
    issue_number = models.CharField(max_length=50, unique=True, blank=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="accessory_issues")
    accessory_stock = models.ForeignKey(AccessoryStock, on_delete=models.PROTECT, related_name="issues")
    issued_quantity = models.DecimalField(max_digits=12, decimal_places=2)
    issued_date = models.DateField(null=True, blank=True)
    issued_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="accessory_issues_created")
    remarks = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if not self.issue_number:
            from django.utils.crypto import get_random_string
            self.issue_number = f"ACI-{get_random_string(6).upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.issue_number


class BundleAccessoryIssue(TimeStampedModel):
    """Allocates a portion of an already Store-issued, order-level
    AccessoryIssue down to one specific bundle/operator -- does NOT touch
    AccessoryStock.available_quantity a second time (that was already
    decremented once when the order-level AccessoryIssue was created);
    only the `return` action (unused accessories handed back) changes stock,
    exactly mirroring CuttingOrderViewSet.return_fabric."""
    bundle = models.ForeignKey(Bundle, on_delete=models.CASCADE, related_name="accessory_issues")
    accessory_issue = models.ForeignKey(AccessoryIssue, on_delete=models.PROTECT, related_name="bundle_allocations")
    operator = models.ForeignKey(Operator, on_delete=models.SET_NULL, null=True, blank=True, related_name="accessory_issues")
    issued_quantity = models.DecimalField(max_digits=12, decimal_places=2)
    returned_quantity = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    issued_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="bundle_accessory_issues_created")
    issued_at = models.DateTimeField(auto_now_add=True)
    remarks = models.TextField(blank=True)

    def __str__(self):
        return f"{self.accessory_issue} -> {self.bundle} x{self.issued_quantity}"


class BundleReceipt(TimeStampedModel):
    """Production floor's acknowledgement that a cut bundle has physically
    arrived and is ready to be assigned to an operator (see apps.operators)."""

    bundle = models.OneToOneField(Bundle, on_delete=models.CASCADE, related_name="receipt")
    received_date = models.DateField(auto_now_add=True)
    received_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="bundle_receipts")
    remarks = models.TextField(blank=True)

    def __str__(self):
        return f"Received {self.bundle}"


class ProductionQualityCheck(TimeStampedModel):
    """Stage-level QC on the production floor, separate from the operator's
    own bundle-assignment QC in apps.operators."""

    bundle = models.ForeignKey(Bundle, on_delete=models.CASCADE, related_name="production_qc_checks")
    checked_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="production_qc_checks")
    passed = models.BooleanField(default=True)
    defects_found = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    checked_date = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"QC {self.bundle} - {'PASS' if self.passed else 'FAIL'}"


class OperatorAccessoryIssue(TimeStampedModel):
    """Store issues accessories DIRECTLY to an operator for stitching, and
    tracks how much was issued, how much the operator has used (and on how
    many garment pieces), and how much remains -- so accessory consumption is
    accountable per operator, not just per order."""
    issue_number = models.CharField(max_length=50, unique=True, blank=True)
    operator = models.ForeignKey(Operator, on_delete=models.PROTECT, related_name="direct_accessory_issues")
    accessory_stock = models.ForeignKey(AccessoryStock, on_delete=models.PROTECT, related_name="operator_direct_issues")
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="operator_accessory_issues")
    issued_quantity = models.DecimalField(max_digits=12, decimal_places=2)
    used_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pieces_covered = models.PositiveIntegerField(default=0, help_text="Garment pieces the used accessories went into.")
    returned_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    issued_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="operator_accessory_issues_made")
    issued_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def remaining_quantity(self):
        return self.issued_quantity - self.used_quantity - self.returned_quantity

    def save(self, *args, **kwargs):
        if not self.issue_number:
            from django.utils.crypto import get_random_string
            self.issue_number = f"ACO-{get_random_string(6).upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.issue_number} -> {self.operator}"


class ProcessDispatch(TimeStampedModel):
    """Production sends completed pieces out to a processing department
    (Washing / Printing / Embroidery / Finishing / ...) and receives them
    back -- tracking quantity + send date + receive date, so pieces are
    accounted for at every external step, not just inside the factory."""

    class Department(models.TextChoices):
        WASHING = "WASHING", "Washing"
        PRINTING = "PRINTING", "Printing"
        EMBROIDERY = "EMBROIDERY", "Embroidery"
        BUTTON = "BUTTON", "Button"
        FINISHING = "FINISHING", "Finishing"

    class Status(models.TextChoices):
        SENT = "SENT", "Sent — Awaiting Return"
        PENDING_APPROVAL = "PENDING_APPROVAL", "Shortage — Awaiting Admin Approval"
        RECEIVED = "RECEIVED", "Received Back"

    class LossStatus(models.TextChoices):
        NONE = "NONE", "No Shortage"
        PENDING = "PENDING", "Pending Admin Approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    dispatch_number = models.CharField(max_length=50, unique=True, blank=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="process_dispatches")
    department = models.CharField(max_length=20, choices=Department.choices)
    quantity_sent = models.PositiveIntegerField()
    sent_date = models.DateField(null=True, blank=True)
    sent_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="process_dispatches_sent")
    quantity_received = models.PositiveIntegerField(null=True, blank=True)
    received_date = models.DateField(null=True, blank=True)
    received_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="process_dispatches_received")
    # When fewer pieces come back than were sent, the receiver must give a
    # reason; the shortfall isn't accepted until an Admin approves it.
    loss_reason = models.TextField(blank=True)
    loss_status = models.CharField(max_length=20, choices=LossStatus.choices, default=LossStatus.NONE)
    loss_reviewed_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="process_loss_reviews")
    loss_reviewed_at = models.DateTimeField(null=True, blank=True)
    loss_review_notes = models.TextField(blank=True)
    is_outsourced = models.BooleanField(default=False)
    vendor = models.ForeignKey("master_data.Vendor", on_delete=models.SET_NULL, null=True, blank=True, related_name="process_dispatches")
    cost_per_piece = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Outsourced processing rate per piece; total cost = rate x quantity_sent.")
    cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Total processing cost (auto-computed = cost_per_piece x quantity_sent when a per-piece rate is given).")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SENT)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def loss_quantity(self):
        if self.quantity_received is None:
            return 0
        return max(self.quantity_sent - self.quantity_received, 0)

    @classmethod
    def available_to_send(cls, order_id):
        """Pieces on the Production floor free to be sent to a process right now.

        A piece can only go to the next department once it has physically come
        back from wherever it currently is, so the floor pool is:
            accepted-from-production
              - pieces still OUT at any department (sent, not yet received)
              - pieces already lost at a department (received short)
        Sending is capped at this number, and pieces out at (say) Washing are
        NOT re-offered to Printing until Washing returns them."""
        from django.db.models import Sum
        from apps.operators.models import BundleAssignment
        if not order_id:
            return 0
        accepted = int(BundleAssignment.objects.filter(
            bundle__cutting_order__order_id=order_id,
            status__in=[BundleAssignment.Status.COMPLETED, BundleAssignment.Status.QUALITY_CHECKED],
        ).aggregate(q=Sum("returned_quantity"))["q"] or 0)
        out = 0            # sent to a department, not finalised back yet
        received_loss = 0  # came back short — those pieces are gone
        for pd in cls.objects.filter(order_id=order_id):
            if pd.status in (cls.Status.SENT, cls.Status.PENDING_APPROVAL):
                out += pd.quantity_sent
            elif pd.status == cls.Status.RECEIVED:
                received_loss += max(pd.quantity_sent - (pd.quantity_received or 0), 0)
        return max(accepted - out - received_loss, 0)

    def save(self, *args, **kwargs):
        if not self.dispatch_number:
            from django.utils.crypto import get_random_string
            self.dispatch_number = f"PRC-{get_random_string(6).upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.dispatch_number} -> {self.get_department_display()}"
