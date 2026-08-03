from django.db import models
from apps.master_data.models import TimeStampedModel
from apps.orders.models import Order


class FinishingReceipt(TimeStampedModel):
    """Production's hand-off of completed pieces to Finishing -- created by
    apps.production's send-to-finishing action, which also finally advances
    Order.status to IN_FINISHING (previously a dead enum value nothing ever set)."""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="finishing_receipts")
    quantity_sent = models.PositiveIntegerField()
    sent_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="finishing_receipts_sent")
    sent_at = models.DateTimeField(auto_now_add=True)
    remarks = models.TextField(blank=True)

    def __str__(self):
        return f"{self.order} -> Finishing x{self.quantity_sent}"


class FinishingOperation(TimeStampedModel):
    """One finishing operation (washing/printing/ironing/embroidery/
    packaging/labeling/other) performed on an order's pieces, with its own
    cost -- either per-piece (cost_per_piece * quantity) or a flat batch
    total_cost entered directly."""

    class OperationType(models.TextChoices):
        WASHING = "WASHING", "Washing"
        PRINTING = "PRINTING", "Printing"
        IRONING = "IRONING", "Ironing"
        EMBROIDERY = "EMBROIDERY", "Embroidery"
        PACKAGING = "PACKAGING", "Packaging"
        LABELING = "LABELING", "Labeling"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        COMPLETED = "COMPLETED", "Completed"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="finishing_operations")
    operation_type = models.CharField(max_length=20, choices=OperationType.choices)
    quantity = models.PositiveIntegerField()
    quantity_rejected = models.PositiveIntegerField(
        default=0, help_text="Pieces damaged/rejected during this specific finishing operation (washing, printing, etc).")
    cost_per_piece = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_outsourced = models.BooleanField(default=False)
    vendor = models.ForeignKey("master_data.Vendor", on_delete=models.SET_NULL, null=True, blank=True, related_name="finishing_operations")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    performed_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(blank=True)
    recorded_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="finishing_operations_recorded")

    def __str__(self):
        return f"{self.get_operation_type_display()} - {self.order} x{self.quantity}"


class FinishingQualityCheck(TimeStampedModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="finishing_qc_checks")
    # QC recorded per colour + size so results carry a full breakdown
    # (e.g. "30 White S passed, 5 White M failed").
    color = models.ForeignKey("master_data.Color", on_delete=models.SET_NULL, null=True, blank=True, related_name="finishing_qc_checks")
    size = models.ForeignKey("master_data.Size", on_delete=models.SET_NULL, null=True, blank=True, related_name="finishing_qc_checks")
    checked_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="finishing_qc_checks")
    quantity_checked = models.PositiveIntegerField()
    quantity_passed = models.PositiveIntegerField()
    quantity_altered = models.PositiveIntegerField(default=0, help_text="Pieces sent for alteration/rework.")
    quantity_rejected = models.PositiveIntegerField(default=0)
    fail_reason = models.TextField(blank=True, help_text="Why the failed pieces failed (per colour+size row).")
    alter_reason = models.TextField(blank=True, help_text="Why the altered pieces need alteration.")
    # Rework loop: of the pieces sent for alteration, how many came back OK
    # (re-inspected pass) vs scrapped after rework.
    quantity_reworked_passed = models.PositiveIntegerField(default=0)
    quantity_reworked_failed = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    checked_date = models.DateField(auto_now_add=True)

    @property
    def alteration_pending(self):
        """Altered pieces not yet re-inspected after rework."""
        return max(self.quantity_altered - self.quantity_reworked_passed - self.quantity_reworked_failed, 0)

    @property
    def final_good(self):
        """Total shippable = first-pass passed + reworked-and-passed."""
        return self.quantity_passed + self.quantity_reworked_passed

    @property
    def allocated_for_rework(self):
        """Altered pieces already handed to an operator for rework."""
        return sum(r.quantity for r in self.rework_assignments.all())

    @property
    def allocatable_rework(self):
        """Altered pieces not yet allocated to any operator for rework."""
        return max(self.quantity_altered - self.allocated_for_rework, 0)

    @property
    def returned_from_rework(self):
        """Reworked pieces an operator has finished and handed back to Finishing."""
        return sum((r.returned_quantity or 0) for r in self.rework_assignments.all()
                   if r.status == ReworkAssignment.Status.COMPLETED)

    @property
    def awaiting_second_qc(self):
        """Reworked-and-returned pieces still to be re-inspected by Finishing."""
        return max(self.returned_from_rework - self.quantity_reworked_passed - self.quantity_reworked_failed, 0)

    def __str__(self):
        return f"Final QC {self.order} - {self.quantity_passed}/{self.quantity_checked}"


class ReworkAssignment(TimeStampedModel):
    """One rework task: Finishing QC sent some altered pieces back to Production,
    and the Production Supervisor allocates them to a specific operator at a
    rate per piece. The operator reworks and returns the pieces (COMPLETED),
    which then go back to Finishing for a second QC. Rework pay is an operator
    earning and a labour cost on the order's P&L."""

    class Status(models.TextChoices):
        ALLOCATED = "ALLOCATED", "Allocated — Operator Reworking"
        COMPLETED = "COMPLETED", "Reworked — Returned to Finishing"

    qc = models.ForeignKey(FinishingQualityCheck, on_delete=models.CASCADE, related_name="rework_assignments")
    operator = models.ForeignKey("operators.Operator", on_delete=models.PROTECT, related_name="rework_assignments")
    quantity = models.PositiveIntegerField(help_text="Altered pieces handed to this operator to rework.")
    rate_per_piece = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    returned_quantity = models.PositiveIntegerField(null=True, blank=True, help_text="Pieces the operator reworked and handed back.")
    paid_quantity = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ALLOCATED)
    allocated_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="rework_allocations")
    completed_at = models.DateTimeField(null=True, blank=True)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def earned_amount(self):
        """Rework labour earned = pieces returned x rate."""
        from decimal import Decimal
        return (self.returned_quantity or 0) * (self.rate_per_piece or Decimal("0"))

    @property
    def paid_amount(self):
        from decimal import Decimal
        return self.paid_quantity * (self.rate_per_piece or Decimal("0"))

    @property
    def pending_pay_quantity(self):
        return max((self.returned_quantity or 0) - self.paid_quantity, 0)

    @property
    def pending_pay_amount(self):
        from decimal import Decimal
        return self.pending_pay_quantity * (self.rate_per_piece or Decimal("0"))

    def __str__(self):
        return f"Rework {self.qc_id} -> {self.operator} x{self.quantity}"


class Packing(TimeStampedModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="packings")
    packed_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="packings")
    quantity_packed = models.PositiveIntegerField()
    carton_count = models.PositiveIntegerField(default=0)
    packed_date = models.DateField(auto_now_add=True)
    remarks = models.TextField(blank=True)

    def __str__(self):
        return f"Packing {self.order} - {self.quantity_packed} pcs"


class Dispatch(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        DISPATCHED = "DISPATCHED", "Dispatched"
        DELIVERED = "DELIVERED", "Delivered"

    class TransportMode(models.TextChoices):
        ROAD = "ROAD", "Road"
        AIR = "AIR", "Air"
        COURIER = "COURIER", "Courier"
        OTHER = "OTHER", "Other"

    # ForeignKey (not OneToOne): an order can be dispatched in several partial
    # shipments, each its own challan, until all good pieces are shipped.
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="dispatches")
    dispatched_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="dispatches")
    dispatch_date = models.DateField(null=True, blank=True)
    challan_number = models.CharField(max_length=100, blank=True, help_text="Delivery challan number.")
    size_breakdown = models.JSONField(default=dict, blank=True, help_text='Pieces dispatched per size, e.g. {"S": 30, "M": 40}.')
    color_breakdown = models.JSONField(default=dict, blank=True, help_text='Pieces dispatched per colour, e.g. {"White": 40, "Black": 30}.')
    tracking_number = models.CharField(max_length=100, blank=True)
    carrier = models.CharField(max_length=150, blank=True)
    mode_of_transport = models.CharField(max_length=20, choices=TransportMode.choices, blank=True)
    quantity_dispatched = models.PositiveIntegerField(null=True, blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    delivery_acknowledged_by = models.CharField(max_length=150, blank=True, help_text="Customer-side name acknowledging receipt.")
    transport_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    remarks = models.TextField(blank=True)

    def __str__(self):
        return f"Dispatch {self.order} - {self.status}"
