from django.db import models
from apps.master_data.models import TimeStampedModel, Product
from apps.cutting.models import Bundle
from apps.orders.models import Order


class Operator(TimeStampedModel):
    class OperatorType(models.TextChoices):
        INDIVIDUAL = "INDIVIDUAL", "Individual"
        GROUP = "GROUP", "Group"

    class SkillLevel(models.TextChoices):
        BEGINNER = "BEGINNER", "Beginner"
        INTERMEDIATE = "INTERMEDIATE", "Intermediate"
        EXPERT = "EXPERT", "Expert"

    operator_type = models.CharField(max_length=20, choices=OperatorType.choices)
    name = models.CharField(max_length=200)
    contact = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    skill_level = models.CharField(max_length=20, choices=SkillLevel.choices, blank=True)
    is_active = models.BooleanField(default=True)
    joined_date = models.DateField(null=True, blank=True)
    # Optional link to a login account for operators who use the system themselves.
    user_account = models.OneToOneField("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="operator_profile")

    def __str__(self):
        return f"{self.name} ({self.get_operator_type_display()})"


class OperatorRate(TimeStampedModel):
    class RateType(models.TextChoices):
        PER_BUNDLE = "PER_BUNDLE", "Per Bundle"
        PER_PIECE = "PER_PIECE", "Per Piece"

    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name="rates")
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="operator_rates")
    order = models.ForeignKey(
        Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="operator_rates",
        help_text="Order-specific rate override -- leave Product blank when this is set; it applies to all work on this order regardless of product.",
    )
    rate_type = models.CharField(max_length=20, choices=RateType.choices)
    rate_amount = models.DecimalField(max_digits=10, decimal_places=2)
    effective_date = models.DateField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-effective_date"]

    def __str__(self):
        return f"{self.operator} - {self.rate_type} - {self.rate_amount}"


class BundleAssignment(TimeStampedModel):
    class Status(models.TextChoices):
        ASSIGNED = "ASSIGNED", "Assigned"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        RETURNED = "RETURNED", "Returned — Pending Review"
        COMPLETED = "COMPLETED", "Completed"
        QUALITY_CHECKED = "QUALITY_CHECKED", "Quality Checked"

    class ShortageStatus(models.TextChoices):
        NOT_APPLICABLE = "NOT_APPLICABLE", "No Shortage"
        PENDING_REVIEW = "PENDING_REVIEW", "Pending Admin Review"
        APPROVED = "APPROVED", "Reason Approved"
        REJECTED = "REJECTED", "Reason Rejected"

    bundle = models.ForeignKey(Bundle, on_delete=models.CASCADE, related_name="assignments")
    operator = models.ForeignKey(Operator, on_delete=models.PROTECT, related_name="assignments")
    assigned_date = models.DateField(auto_now_add=True)
    completion_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ASSIGNED)
    issued_quantity = models.PositiveIntegerField(null=True, blank=True, help_text="Pieces handed to the operator; defaults to the bundle's full quantity.")
    returned_quantity = models.PositiveIntegerField(null=True, blank=True, help_text="Pieces the operator actually returned.")
    shortage_reason = models.TextField(blank=True)
    shortage_reason_status = models.CharField(max_length=20, choices=ShortageStatus.choices, default=ShortageStatus.NOT_APPLICABLE)
    shortage_reviewed_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="shortage_reviews")
    shortage_reviewed_at = models.DateTimeField(null=True, blank=True)
    shortage_review_notes = models.TextField(blank=True)
    quality_check_passed = models.BooleanField(null=True, blank=True)
    defects = models.PositiveIntegerField(default=0)
    defect_reason = models.TextField(blank=True, help_text="Required when defects > 0.")
    remarks = models.TextField(blank=True)
    assigned_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="bundle_assignments_made")

    @property
    def shortage_quantity(self):
        if self.issued_quantity is None or self.returned_quantity is None:
            return 0
        return max(self.issued_quantity - self.returned_quantity, 0)

    def __str__(self):
        return f"{self.bundle} -> {self.operator} [{self.status}]"


class OperatorIncome(TimeStampedModel):
    class PaymentStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partially Paid"
        PAID = "PAID", "Paid"

    operator = models.ForeignKey(Operator, on_delete=models.PROTECT, related_name="incomes")
    period_start = models.DateField()
    period_end = models.DateField()
    bundles_completed = models.PositiveIntegerField(default=0)
    pieces_completed = models.PositiveIntegerField(default=0)
    rate_applied = models.DecimalField(max_digits=10, decimal_places=2)
    total_income = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    payment_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-period_end"]

    def __str__(self):
        return f"{self.operator} [{self.period_start} - {self.period_end}] = {self.total_income}"
