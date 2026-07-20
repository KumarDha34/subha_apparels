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
    checked_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="finishing_qc_checks")
    quantity_checked = models.PositiveIntegerField()
    quantity_passed = models.PositiveIntegerField()
    quantity_altered = models.PositiveIntegerField(default=0, help_text="Pieces sent for alteration/rework.")
    quantity_rejected = models.PositiveIntegerField(default=0)
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

    def __str__(self):
        return f"Final QC {self.order} - {self.quantity_passed}/{self.quantity_checked}"


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

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="dispatch")
    dispatched_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="dispatches")
    dispatch_date = models.DateField(null=True, blank=True)
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
