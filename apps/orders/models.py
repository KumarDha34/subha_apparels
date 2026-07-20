import nepali_datetime
from django.db import models, transaction
from django.utils import timezone
from apps.master_data.models import TimeStampedModel, Product, Color, Size, FabricType, Party, NEPALI_MONTHS
from apps.store.models import FabricStock


class Order(TimeStampedModel):
    class OrderType(models.TextChoices):
        FIXED_QUANTITY = "FIXED_QUANTITY", "Fixed Quantity"
        RATIO_BASED = "RATIO_BASED", "Ratio Based"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        CONFIRMED = "CONFIRMED", "Confirmed"
        IN_CUTTING = "IN_CUTTING", "In Cutting"
        IN_PRODUCTION = "IN_PRODUCTION", "In Production"
        IN_FINISHING = "IN_FINISHING", "In Finishing"
        DISPATCHED = "DISPATCHED", "Dispatched"
        CANCELLED = "CANCELLED", "Cancelled"

    order_number = models.CharField(max_length=50, unique=True, blank=True)
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="orders")
    order_date = models.DateField()
    order_type = models.CharField(max_length=20, choices=OrderType.choices)
    is_repeat = models.BooleanField(default=False, verbose_name="New Repeat")
    remarks = models.TextField(blank=True)
    cutting_instruction = models.TextField(
        blank=True,
        help_text="Instruction for the Cutting floor, e.g. 'Use only half of each roll for every colour, return the rest'. "
                  "Store issues the full rolls; Cutting follows this note and returns the leftover.",
    )
    total_order_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="orders_created")

    STATUS_SEQUENCE = [Status.DRAFT, Status.CONFIRMED, Status.IN_CUTTING, Status.IN_PRODUCTION, Status.IN_FINISHING, Status.DISPATCHED]

    class Meta:
        ordering = ["-order_date", "-id"]

    def advance_status(self, new_status):
        """Move status forward to `new_status` if it isn't already there or
        further along -- never regresses status and never touches a
        CANCELLED order. Called from downstream departments (Cutting,
        Production) as materials are issued to them, so status always
        reflects the furthest stage the order has reached."""
        if self.status == self.Status.CANCELLED:
            return
        if self.STATUS_SEQUENCE.index(new_status) > self.STATUS_SEQUENCE.index(self.status):
            self.status = new_status
            self.save(update_fields=["status", "updated_at"])

    def save(self, *args, **kwargs):
        if not self.order_number:
            # The Party row lock must stay held for the generate-then-insert
            # sequence as a whole -- releasing it right after picking the
            # next sequence (e.g. by locking inside a nested atomic() that
            # exits before super().save()) would let a second concurrent
            # request read the same "last" row and pick the same number.
            with transaction.atomic():
                party = Party.objects.select_for_update().get(pk=self.party_id)
                self.order_number = self._generate_order_number(party)
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

    def _generate_order_number(self, party):
        """<COMPANY_PREFIX>-<BS_MONTH_CODE>-<SEQUENCE>, e.g. "HU-ASH-001".
        Sequence is scoped per party per BS month (not global), and resets
        to 001 whenever the BS month rolls over. Caller must already hold a
        row lock on `party` for the duration of the transaction."""
        ref_date = self.order_date or timezone.localdate()
        bs = nepali_datetime.date.from_datetime_date(ref_date)
        month_code = NEPALI_MONTHS[bs.month - 1][:3].upper()
        code_prefix = f"{party.code_prefix or 'XX'}-{month_code}-"

        last = (
            Order.objects.filter(party_id=party.id, order_number__startswith=code_prefix)
            .order_by("-id").first()
        )
        try:
            next_seq = int(last.order_number.rsplit("-", 1)[-1]) + 1 if last else 1
        except ValueError:
            next_seq = 1

        while True:
            candidate = f"{code_prefix}{next_seq:03d}"
            if not Order.objects.filter(order_number=candidate).exists():
                return candidate
            next_seq += 1

    def __str__(self):
        return f"{self.order_number} - {self.party}"


class OrderItem(TimeStampedModel):
    """One product line within an order."""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    fabric_type = models.ForeignKey(FabricType, on_delete=models.PROTECT, related_name="order_items")
    approved_average = models.DecimalField(max_digits=8, decimal_places=3, help_text="Approved fabric consumption per piece")
    price_per_piece = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Operator stitching payment per finished piece, set by Merchandising when the order is created. "
                  "Every operator who completes a piece of this order line is paid this rate x pieces returned.",
    )
    inner_required = models.BooleanField(default=False)
    fusing_required = models.BooleanField(default=False)
    resting_needed = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.order.order_number} / {self.product}"


class OrderItemColor(TimeStampedModel):
    """One color within a product item, with the rolls allocated to it."""
    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name="colors")
    color = models.ForeignKey(Color, on_delete=models.PROTECT, related_name="order_item_colors")
    rolls = models.ManyToManyField(FabricStock, blank=True, related_name="order_item_colors")
    half_roll = models.BooleanField(
        default=False,
        help_text="Merchandising's 'use only half of each roll for this colour' flag. Cutting sees it per colour "
                  "and cuts ~half the issued fabric, returning the rest.",
    )

    class Meta:
        unique_together = ("order_item", "color")

    def __str__(self):
        return f"{self.order_item} / {self.color}"


class OrderItemColorSize(TimeStampedModel):
    """One size row within a color. `quantity` is used for FIXED_QUANTITY
    orders, `ratio_part` for RATIO_BASED orders (mutually exclusive,
    enforced in OrderSerializer.validate())."""
    order_item_color = models.ForeignKey(OrderItemColor, on_delete=models.CASCADE, related_name="size_lines")
    size = models.ForeignKey(Size, on_delete=models.PROTECT, related_name="order_size_lines")
    quantity = models.PositiveIntegerField(null=True, blank=True, help_text="Set when order_type = FIXED_QUANTITY")
    ratio_part = models.PositiveIntegerField(null=True, blank=True, help_text="Set when order_type = RATIO_BASED")

    class Meta:
        unique_together = ("order_item_color", "size")
        ordering = ["size__display_order"]

    def __str__(self):
        return f"{self.order_item_color} / {self.size}"
