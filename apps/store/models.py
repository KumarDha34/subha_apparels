from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator
from apps.master_data.models import TimeStampedModel, FabricType, Color, Accessory


class Unit(models.TextChoices):
    # A roll is NOT a unit -- every physical roll is its own stock row whose
    # quantity is measured in a real unit (metres / kg). Two 100 m rolls of the
    # same colour are two rows of 100 METERS each, not "2 ROLLS".
    METERS = "METERS", "Meters"
    YARDS = "YARDS", "Yards"
    KILOGRAMS = "KILOGRAMS", "Kilograms"
    GRAMS = "GRAMS", "Grams"


class FabricStock(TimeStampedModel):
    """
    One row per distinct fabric (type + color + width) - holds the running
    available quantity. StockTransaction rows are the ledger; this is the
    cached current balance for fast lookups.
    """
    fabric_type = models.ForeignKey(FabricType, on_delete=models.PROTECT, related_name="stocks")
    color = models.ForeignKey(Color, on_delete=models.PROTECT, related_name="stocks")
    width = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, help_text="Fabric width (inches)")
    unit = models.CharField(max_length=20, choices=Unit.choices, default=Unit.METERS)
    roll_number = models.CharField(max_length=100, blank=True)
    available_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reorder_level = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vendor = models.ForeignKey("master_data.Vendor", on_delete=models.SET_NULL, null=True, blank=True, related_name="fabric_stocks")
    supplied_by_party = models.ForeignKey(
        "master_data.Party", on_delete=models.SET_NULL, null=True, blank=True, related_name="supplied_fabric_stocks",
        help_text="Set when this stock originated from a customer-supplied purchase, so it can be traced back to that customer.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=["fabric_type", "color"])]

    def __str__(self):
        return f"{self.fabric_type} / {self.color} - {self.available_quantity} {self.unit}"

    @property
    def is_low_stock(self):
        # "Low" simply means out of stock (nothing left).
        return self.available_quantity <= 0


class StockTransaction(TimeStampedModel):
    """Ledger of everything that moves fabric stock: receipts, issues,
    wastage, returns, and manual adjustments."""

    class TransactionType(models.TextChoices):
        RECEIPT = "RECEIPT", "Receipt (from Merchandise/Purchase)"
        ISSUE = "ISSUE", "Issue (to Cutting)"
        WASTAGE = "WASTAGE", "Wastage"
        RETURN = "RETURN", "Return"
        ADJUSTMENT = "ADJUSTMENT", "Manual Adjustment"

    fabric_stock = models.ForeignKey(FabricStock, on_delete=models.CASCADE, related_name="transactions")
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    reference = models.CharField(max_length=100, blank=True, help_text="PO number, cutting order number, etc.")
    remarks = models.TextField(blank=True)
    transaction_date = models.DateField(auto_now_add=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="stock_transactions")

    def __str__(self):
        return f"{self.transaction_type} - {self.quantity} ({self.fabric_stock})"


class AccessoryStock(TimeStampedModel):
    """One row per Accessory (the Accessory record itself is already the
    SKU - type+name+size_spec+color - so unlike FabricStock there's no
    extra roll/width dimension needed)."""
    accessory = models.OneToOneField(Accessory, on_delete=models.PROTECT, related_name="stock")
    available_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reorder_level = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vendor = models.ForeignKey("master_data.Vendor", on_delete=models.SET_NULL, null=True, blank=True, related_name="accessory_stocks")
    supplied_by_party = models.ForeignKey(
        "master_data.Party", on_delete=models.SET_NULL, null=True, blank=True, related_name="supplied_accessory_stocks",
        help_text="Set when this stock originated from a customer-supplied purchase, so it can be traced back to that customer.",
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.accessory} - {self.available_quantity}"

    @property
    def is_low_stock(self):
        # "Low" simply means out of stock (nothing left).
        return self.available_quantity <= 0


class FinishedGoodsReceipt(TimeStampedModel):
    """Completed garments handed to Store's finished-goods area. Created
    automatically when Finishing records a Dispatch, so Store keeps a running
    record of every finished order -- what was produced, how many, and where
    it was dispatched -- closing the loop from raw fabric to shipped goods."""
    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="finished_goods_receipts")
    quantity = models.PositiveIntegerField(default=0)
    dispatch_reference = models.CharField(max_length=100, blank=True, help_text="Dispatch tracking number / challan.")
    received_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="finished_goods_received")
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Finished Goods {self.order_id} x{self.quantity}"


class AccessoryStockTransaction(TimeStampedModel):
    """Ledger of everything that moves accessory stock -- mirrors
    StockTransaction exactly, kept as a separate model (not a generalized/
    polymorphic one) since CuttingOrder.fabric_issued FKs directly to
    FabricStock and generalizing would ripple into that."""

    class TransactionType(models.TextChoices):
        RECEIPT = "RECEIPT", "Receipt (from Purchase)"
        ISSUE = "ISSUE", "Issue (to Cutting/Production)"
        WASTAGE = "WASTAGE", "Wastage"
        RETURN = "RETURN", "Return"
        ADJUSTMENT = "ADJUSTMENT", "Manual Adjustment"

    accessory_stock = models.ForeignKey(AccessoryStock, on_delete=models.CASCADE, related_name="transactions")
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    reference = models.CharField(max_length=100, blank=True, help_text="PO number, etc.")
    remarks = models.TextField(blank=True)
    transaction_date = models.DateField(auto_now_add=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="accessory_stock_transactions")

    def __str__(self):
        return f"{self.transaction_type} - {self.quantity} ({self.accessory_stock})"
