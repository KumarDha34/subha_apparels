from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from apps.master_data.models import TimeStampedModel


class CustomUserManager(BaseUserManager):
    """
    Email is the login identifier (USERNAME_FIELD = "email"). The inherited
    `username` field is kept only as an internal unique handle - it is
    auto-filled from the email so callers never have to think about it.
    """

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)
        extra_fields.setdefault("username", email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        MERCHANDISE = "MERCHANDISE", "Merchandise"
        STORE_MANAGER = "STORE_MANAGER", "Store Manager"
        CUTTING_SUPERVISOR = "CUTTING_SUPERVISOR", "Cutting Supervisor"
        PRODUCTION_SUPERVISOR = "PRODUCTION_SUPERVISOR", "Production Supervisor"
        FINISHING_SUPERVISOR = "FINISHING_SUPERVISOR", "Finishing Supervisor"
        ACCOUNTS = "ACCOUNTS", "Accounts"
        OPERATOR = "OPERATOR", "Operator"

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.MERCHANDISE)
    phone = models.CharField(max_length=20, blank=True)
    is_active_employee = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []  # `createsuperuser` will only prompt for email + password

    objects = CustomUserManager()

    def __str__(self):
        return f"{self.get_full_name() or self.email} ({self.get_role_display()})"


class Notification(TimeStampedModel):
    """In-app notification, created by `apps.users.services.notify_role()`
    at department handoff points (bundle sent to Production, shortage
    pending review, order sent to Finishing, etc.)."""
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    message = models.CharField(max_length=255)
    link = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.recipient}: {self.message}"


class ActivityLog(TimeStampedModel):
    """Audit trail: who did what, and when. Written automatically by
    ActivityLogMiddleware for every successful mutating API request. user_name
    and role are denormalised so the log stays readable even if the user is
    later renamed or removed."""
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="activity_logs")
    user_name = models.CharField(max_length=200, blank=True)
    role = models.CharField(max_length=32, blank=True)
    action = models.CharField(max_length=200)
    department = models.CharField(max_length=40, blank=True)
    method = models.CharField(max_length=10, blank=True)
    path = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user_name}: {self.action}"


class PasswordResetRequest(TimeStampedModel):
    """A self-service 'forgot password' request. Since the system has no email
    gateway, requests are handled by an Admin from the Users page (admin sets a
    new temporary password and relays it to the employee)."""
    email = models.EmailField()
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="reset_requests")
    handled = models.BooleanField(default=False)
    handled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="reset_requests_handled")
    handled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Reset request: {self.email} ({'handled' if self.handled else 'pending'})"