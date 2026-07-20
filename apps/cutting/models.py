from django.db import models
from apps.master_data.models import TimeStampedModel, Color, Size, FabricType, ProductComponent
from apps.orders.models import Order, OrderItem
from apps.store.models import FabricStock


class Marker(TimeStampedModel):
    """A reusable fabric-consumption figure for a given style/ratio/fabric
    combination -- lets the Cutting Master pick a known efficiency instead
    of re-deriving it by hand for every Ratio-order cutting order. The
    ratio itself always comes from the order's own OrderItemColorSize.ratio_part;
    a Marker only supplies the meters-per-complete-set number."""
    marker_number = models.CharField(max_length=50, unique=True, blank=True)
    name = models.CharField(max_length=150)
    fabric_type = models.ForeignKey(FabricType, on_delete=models.SET_NULL, null=True, blank=True, related_name="markers")
    avg_consumption_per_set = models.DecimalField(max_digits=8, decimal_places=3, help_text="Meters of fabric per one complete ratio set")
    remarks = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.marker_number:
            from django.utils.crypto import get_random_string
            self.marker_number = f"MKR-{get_random_string(6).upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.marker_number} - {self.name}"


class CuttingOrder(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        FABRIC_ISSUED = "FABRIC_ISSUED", "Fabric Issued"
        RECEIVED = "RECEIVED", "Received"
        CUTTING = "CUTTING", "Cutting In Progress"
        COMPLETED = "COMPLETED", "Completed"

    class AverageStatus(models.TextChoices):
        PENDING = "PENDING", "Not Cut Yet"
        CUT = "CUT", "Cut"
        DONT_CUT = "DONT_CUT", "Don't Cut — Over Consumption"
        NOT_APPLICABLE = "NOT_APPLICABLE", "No Approved Average To Check"

    cutting_number = models.CharField(max_length=50, unique=True, blank=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="cutting_orders", null=True, blank=True)
    order_item = models.ForeignKey(
        OrderItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="cutting_orders",
        help_text="Auto-derived from the fabric roll's OrderItemColor link when possible.",
    )
    fabric_issued = models.ForeignKey(FabricStock, on_delete=models.PROTECT, related_name="cutting_orders")
    fabric_issued_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fabric_used_quantity = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    wastage_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_pieces_cut = models.PositiveIntegerField(null=True, blank=True)
    actual_average = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    average_status = models.CharField(max_length=20, choices=AverageStatus.choices, default=AverageStatus.PENDING)
    average_override_approved = models.BooleanField(default=False)
    average_override_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="cutting_overrides")
    average_override_at = models.DateTimeField(null=True, blank=True)
    average_override_remarks = models.TextField(blank=True)
    returned_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    returned_at = models.DateTimeField(null=True, blank=True)
    returned_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="cutting_fabric_returns")
    received_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="cutting_orders_received")
    marker = models.ForeignKey(Marker, on_delete=models.SET_NULL, null=True, blank=True, related_name="cutting_orders")
    ratio_sets_cut = models.PositiveIntegerField(null=True, blank=True, help_text="Set only for Ratio-order cuts.")
    layer_length = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, help_text="Length of one fabric layer in the lay (m).")
    no_of_layers = models.PositiveIntegerField(null=True, blank=True, help_text="Total fabric layers spread & cut across all lays recorded.")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    cutting_date = models.DateField(null=True, blank=True)
    supervisor = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="cutting_orders")
    remarks = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if not self.cutting_number:
            from django.utils.crypto import get_random_string
            self.cutting_number = f"CUT-{get_random_string(6).upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.cutting_number

    @property
    def remaining_quantity(self):
        return self.fabric_issued_quantity - (self.fabric_used_quantity or 0) - (self.wastage_quantity or 0) - self.returned_quantity


class CuttingPiece(TimeStampedModel):
    """Cut pieces recorded by color and size, before bundling. `component`
    is null for products with no defined ProductComponents (identical to
    pre-component behavior); when set, one row exists per color+size+component
    so a bundle can be validated against every component's matching quantity."""
    cutting_order = models.ForeignKey(CuttingOrder, on_delete=models.CASCADE, related_name="pieces")
    color = models.ForeignKey(Color, on_delete=models.PROTECT, related_name="cutting_pieces")
    size = models.ForeignKey(Size, on_delete=models.PROTECT, related_name="cutting_pieces")
    component = models.ForeignKey(ProductComponent, on_delete=models.SET_NULL, null=True, blank=True, related_name="cutting_pieces")
    quantity = models.PositiveIntegerField()

    class Meta:
        unique_together = ("cutting_order", "color", "size", "component")

    def __str__(self):
        return f"{self.cutting_order} - {self.color}/{self.size} x{self.quantity}"


class Bundle(TimeStampedModel):
    """Pieces grouped by color+size into a bundle for the production floor.
    Assignment to an operator is tracked in the operators app."""

    class Status(models.TextChoices):
        CREATED = "CREATED", "Created"
        RECEIVED = "RECEIVED", "Received by Production"
        ASSIGNED = "ASSIGNED", "Assigned"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        COMPLETED = "COMPLETED", "Completed"
        QUALITY_CHECKED = "QUALITY_CHECKED", "Quality Checked"

    bundle_number = models.CharField(max_length=50, unique=True, blank=True)
    cutting_order = models.ForeignKey(CuttingOrder, on_delete=models.CASCADE, related_name="bundles")
    color = models.ForeignKey(Color, on_delete=models.PROTECT, related_name="bundles")
    size = models.ForeignKey(Size, on_delete=models.PROTECT, related_name="bundles")
    quantity = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED)
    sent_to_production_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="bundles_sent")

    def save(self, *args, **kwargs):
        if not self.bundle_number:
            from django.utils.crypto import get_random_string
            self.bundle_number = f"BDL-{get_random_string(6).upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.bundle_number
