from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    UserViewSet, NotificationViewSet, ActivityLogViewSet,
    PasswordResetRequestViewSet, forgot_password,
)

router = DefaultRouter()
router.register("notifications", NotificationViewSet, basename="notification")
router.register("activity-logs", ActivityLogViewSet, basename="activity-log")
router.register("reset-requests", PasswordResetRequestViewSet, basename="reset-request")
router.register("", UserViewSet, basename="user")

urlpatterns = [
    path("forgot-password/", forgot_password, name="forgot-password"),
] + router.urls
