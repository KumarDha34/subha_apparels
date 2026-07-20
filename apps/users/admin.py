from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Notification


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "get_full_name", "role", "is_active", "is_staff")
    list_filter = ("role", "is_active", "is_active_employee")
    fieldsets = UserAdmin.fieldsets + (
        ("Business Role", {"fields": ("role", "phone", "is_active_employee")}),
    )


admin.site.register(Notification)
