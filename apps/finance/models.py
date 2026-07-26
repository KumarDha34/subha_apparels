from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator
from apps.master_data.models import TimeStampedModel, Vendor
from apps.orders.models import Order


class Quotation(TimeStampedModel):
    """A price quote given to a customer before an order is confirmed.
    Flows DRAFT -> SENT -> ACCEPTED -> CONVERTED (to an Order); can also be
    REJECTED or EXPIRED. Quote numbers are sequential (Q-1001, Q-1002, ...)."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SENT = "SENT", "Sent"
        ACCEPTED = "ACCEPTED", "Accepted"
        REJECTED = "REJECTED", "Rejected"
        CONVERTED = "CONVERTED", "Converted to Order"
        EXPIRED = "EXPIRED", "Expired"

    quote_number = models.CharField(max_length=20, unique=True, blank=True)
    party = models.ForeignKey("master_data.Party", on_delete=models.PROTECT, related_name="quotations")
    product = models.ForeignKey("master_data.Product", on_delete=models.PROTECT, related_name="quotations")
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    rate_per_piece = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    valid_till = models.DateField()
    terms = models.TextField(blank=True, help_text="Payment and delivery terms.")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    converted_order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="source_quotation")
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="quotations_created")

    class Meta:
        ordering = ["-created_at"]

    @property
    def amount(self):
        return Decimal(self.quantity) * self.rate_per_piece

    def save(self, *args, **kwargs):
        if not self.quote_number:
            last = Quotation.objects.order_by("-id").first()
            try:
                nxt = int(last.quote_number.split("-")[1]) + 1 if last and last.quote_number else 1001
            except (ValueError, IndexError):
                nxt = 1001
            self.quote_number = f"Q-{nxt}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quote_number} — {self.party}"


class PurchaseOrder(TimeStampedModel):
    class POType(models.TextChoices):
        ORDER_SPECIFIC = "ORDER_SPECIFIC", "Order Specific"
        BULK = "BULK", "Bulk"
        CUSTOMER_SUPPLIED = "CUSTOMER_SUPPLIED", "Customer Supplied"

    class ReceiptStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED", "Partially Received"
        RECEIVED = "RECEIVED", "Received"

    po_number = models.CharField(max_length=50, unique=True, blank=True)
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, null=True, blank=True, related_name="purchase_orders")
    party = models.ForeignKey("master_data.Party", on_delete=models.PROTECT, null=True, blank=True, related_name="purchase_orders_supplied")
    related_order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="purchase_orders")
    po_type = models.CharField(max_length=20, choices=POType.choices, default=POType.BULK)
    po_date = models.DateField()
    receipt_status = models.CharField(max_length=20, choices=ReceiptStatus.choices, default=ReceiptStatus.PENDING)
    remarks = models.TextField(blank=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="purchase_orders_created")

    def save(self, *args, **kwargs):
        if not self.po_number:
            self.po_number = self._generate_po_number()
        super().save(*args, **kwargs)

    def _generate_po_number(self):
        from django.utils.crypto import get_random_string
        while True:
            candidate = f"PO-{get_random_string(6).upper()}"
            if not PurchaseOrder.objects.filter(po_number=candidate).exists():
                return candidate

    def __str__(self):
        return self.po_number


class PurchaseOrderItem(TimeStampedModel):
    """One line within a purchase order -- either Fabric (fabric_type +
    color) or Accessory. `rate` is intentionally nullable with no default:
    price is never captured at PO-creation time, only during receiving
    (see apps.finance.services.apply_receipt)."""

    class MaterialType(models.TextChoices):
        FABRIC = "FABRIC", "Fabric"
        ACCESSORY = "ACCESSORY", "Accessory"

    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="items")
    material_type = models.CharField(max_length=20, choices=MaterialType.choices)
    item_name = models.CharField(max_length=200, blank=True)
    fabric_type = models.ForeignKey("master_data.FabricType", on_delete=models.PROTECT, null=True, blank=True, related_name="purchase_order_items")
    color = models.ForeignKey("master_data.Color", on_delete=models.PROTECT, null=True, blank=True, related_name="purchase_order_items")
    accessory = models.ForeignKey("master_data.Accessory", on_delete=models.PROTECT, null=True, blank=True, related_name="purchase_order_items")
    quantity = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    no_of_rolls = models.PositiveIntegerField(
        default=1,
        help_text="For fabric: how many physical rolls this quantity arrives in. A customer supplying "
                  "5 rolls of White 110 m each is quantity=550, no_of_rolls=5 -> 5 separate stock rolls.",
    )
    unit = models.CharField(max_length=30, blank=True)
    rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    received_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    @property
    def total(self):
        return self.quantity * self.rate if self.rate is not None else None

    def save(self, *args, **kwargs):
        if not self.item_name:
            if self.material_type == self.MaterialType.ACCESSORY and self.accessory:
                self.item_name = str(self.accessory)
            elif self.fabric_type:
                self.item_name = f"{self.fabric_type} / {self.color}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.item_name} x{self.quantity}"


class CustomerInvoice(TimeStampedModel):
    """A sales invoice raised manually to a customer for a (usually dispatched)
    order -- created by Accounts, like a quotation. Separate from the vendor
    `Invoice` (which is auto-generated from purchases)."""

    class PaymentStatus(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partially Paid"
        PAID = "PAID", "Paid"

    invoice_number = models.CharField(max_length=20, unique=True, blank=True)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="customer_invoices")
    invoice_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    # Extra costs incurred while producing/completing the order and billed on
    # to the customer AFTER the invoice was raised (e.g. extra transport, rush
    # handling, rework). {label: amount}; each entry is also folded into
    # `amount`, so `amount` is always the current total the customer owes.
    additional_costs = models.JSONField(
        default=dict, blank=True,
        help_text="Post-invoice extra charges billed to the customer, {label: amount}. Folded into `amount`.",
    )
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    due_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(blank=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="customer_invoices_created")

    class Meta:
        ordering = ["-created_at"]

    @property
    def due_amount(self):
        return self.amount - self.paid_amount

    @property
    def additional_total(self):
        return sum((Decimal(str(v)) for v in (self.additional_costs or {}).values()), Decimal("0"))

    @property
    def base_amount(self):
        """The original invoice value before any post-invoice extra charges."""
        return (self.amount or Decimal("0")) - self.additional_total

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            last = CustomerInvoice.objects.order_by("-id").first()
            try:
                nxt = int(last.invoice_number.split("-")[1]) + 1 if last and last.invoice_number else 2001
            except (ValueError, IndexError):
                nxt = 2001
            self.invoice_number = f"CINV-{nxt}"
        # keep status in sync with paid amount
        if self.paid_amount <= 0:
            self.payment_status = self.PaymentStatus.UNPAID
        elif self.paid_amount >= self.amount:
            self.payment_status = self.PaymentStatus.PAID
        else:
            self.payment_status = self.PaymentStatus.PARTIALLY_PAID
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.invoice_number} — {self.order_id}"


class Invoice(TimeStampedModel):
    class PaymentStatus(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partially Paid"
        PAID = "PAID", "Paid"

    invoice_number = models.CharField(max_length=50, unique=True, blank=True)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="invoices")
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="invoices")
    invoice_date = models.DateField()
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    additional_costs = models.JSONField(
        blank=True, null=True,
        help_text='e.g. {"transportation": 1500, "customs": 2000, "documentation": 0, "other": 500}',
    )
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    due_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        from decimal import Decimal
        if not self.invoice_number:
            from django.utils.crypto import get_random_string
            self.invoice_number = f"INV-{get_random_string(6).upper()}"
        # additional_costs is JSON, so its values come back as float, not
        # Decimal -- Python refuses to mix the two in arithmetic below.
        additional_total = sum((Decimal(str(v)) for v in (self.additional_costs or {}).values()), Decimal("0"))
        self.total_amount = (self.subtotal or 0) + (self.tax_amount or 0) + additional_total
        super().save(*args, **kwargs)

    def __str__(self):
        return self.invoice_number


class PaymentRecord(TimeStampedModel):
    class PaymentStatus(models.TextChoices):
        PAID = "PAID", "Paid"
        UNPAID = "UNPAID", "Unpaid"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partially Paid"
        DUE = "DUE", "Due"
        OVERDUE = "OVERDUE", "Overdue"

    class PaymentMethod(models.TextChoices):
        CASH = "CASH", "Cash"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"
        CHEQUE = "CHEQUE", "Cheque"
        ONLINE = "ONLINE", "Online"

    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="payment_records")
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payment_records")
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    due_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    invoice_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    payment_date = models.DateField(null=True, blank=True)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="payments_recorded")

    def save(self, *args, **kwargs):
        self.due_amount = (self.total_amount or 0) - (self.paid_amount or 0)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.invoice} - {self.payment_status}"


class IncomeRecord(TimeStampedModel):
    """Client-side money IN: advance payments, final payments, other income.
    Payments recorded against a CustomerInvoice auto-create one of these (see
    finance.views.CustomerInvoiceViewSet.record_payment), so every income
    figure across the system -- dashboard, party ledger, order P&L and the
    sales report -- reads from this single source of truth."""

    class IncomeType(models.TextChoices):
        ADVANCE = "ADVANCE", "Advance Payment"
        FINAL = "FINAL", "Final Payment"
        OTHER = "OTHER", "Other Income"

    class PaymentMethod(models.TextChoices):
        CASH = "CASH", "Cash"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"
        CHEQUE = "CHEQUE", "Cheque"
        ONLINE = "ONLINE", "Online"

    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="income_records")
    customer_invoice = models.ForeignKey(
        "CustomerInvoice", on_delete=models.SET_NULL, null=True, blank=True, related_name="income_records",
        help_text="The sales invoice this payment was recorded against (audit link).",
    )
    income_type = models.CharField(max_length=20, choices=IncomeType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    received_date = models.DateField()
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, blank=True)
    reference = models.CharField(max_length=100, blank=True, help_text="Cheque/transaction/UTR number for the audit trail.")
    remarks = models.TextField(blank=True)
    recorded_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="income_records")

    def __str__(self):
        return f"{self.income_type} - {self.amount}"


class ExpenseRecord(TimeStampedModel):
    """Money OUT that isn't tied to a PO/Invoice or operator payment
    (rent, electricity, water, misc operational expenses)."""

    class ExpenseCategory(models.TextChoices):
        RENT = "RENT", "Rent"
        UTILITIES = "UTILITIES", "Utilities"
        SALARY = "SALARY", "Staff Salary"
        MAINTENANCE = "MAINTENANCE", "Maintenance"
        OTHER = "OTHER", "Other"

    category = models.CharField(max_length=20, choices=ExpenseCategory.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    expense_date = models.DateField()
    order = models.ForeignKey(
        Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="expense_records",
        help_text="Optional -- attribute this expense to one order (e.g. a one-off courier cost) when relevant.",
    )
    remarks = models.TextField(blank=True)
    recorded_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="expense_records")

    def __str__(self):
        return f"{self.category} - {self.amount}"
