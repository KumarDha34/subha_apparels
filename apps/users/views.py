from django.utils import timezone
from rest_framework import viewsets, generics, status
from rest_framework.decorators import action, api_view, permission_classes as perm_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework_simplejwt.views import TokenObtainPairView
from django_filters.rest_framework import DjangoFilterBackend
from .models import User, Notification, ActivityLog, PasswordResetRequest
from .permissions import IsAdmin
from .services import notify_role
from .serializers import (
    UserSerializer, UserCreateSerializer, ChangePasswordSerializer,
    CustomTokenObtainPairSerializer, NotificationSerializer,
    ActivityLogSerializer, PasswordResetRequestSerializer, AdminSetPasswordSerializer,
)


class CustomTokenObtainPairView(TokenObtainPairView):
    """POST username/password -> access, refresh, role, full_name, user_id."""
    serializer_class = CustomTokenObtainPairSerializer


class UserViewSet(viewsets.ModelViewSet):
    """
    Admin-only user & role management.
    Every employee (Store Manager, Cutting Supervisor, Accounts, Operator, etc.)
    is created here with a role that drives their permissions everywhere else.
    """
    queryset = User.objects.all().order_by("username")
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["role", "is_active", "is_active_employee"]
    permission_classes = [IsAuthenticated, IsAdmin]

    def get_serializer_class(self):
        if self.action == "create":
            return UserCreateSerializer
        return UserSerializer

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def me(self, request):
        return Response(UserSerializer(request.user).data)

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated])
    def change_password(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not user.check_password(serializer.validated_data["old_password"]):
            return Response({"old_password": "Incorrect password."}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(serializer.validated_data["new_password"])
        user.save()
        return Response({"detail": "Password updated successfully."})

    @action(detail=True, methods=["post"])
    def admin_reset_password(self, request, pk=None):
        """Admin sets a new password for any user (used to resolve a forgotten
        password) and marks that user's pending reset requests handled."""
        target = self.get_object()
        serializer = AdminSetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target.set_password(serializer.validated_data["new_password"])
        target.save()
        PasswordResetRequest.objects.filter(user=target, handled=False).update(
            handled=True, handled_by=request.user, handled_at=timezone.now())
        PasswordResetRequest.objects.filter(email__iexact=target.email, handled=False).update(
            handled=True, handled_by=request.user, handled_at=timezone.now())
        return Response({"detail": f"Password reset for {target.get_full_name() or target.username}."})


class ActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin-only audit trail with search + ordering + pagination."""
    queryset = ActivityLog.objects.all()
    serializer_class = ActivityLogSerializer
    permission_classes = [IsAuthenticated, IsAdmin]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["role", "department", "user"]
    search_fields = ["user_name", "action", "department", "role"]
    ordering_fields = ["created_at", "user_name", "department"]
    ordering = ["-created_at"]


class PasswordResetRequestViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin-only list of self-service password-reset requests."""
    queryset = PasswordResetRequest.objects.select_related("user").all()
    serializer_class = PasswordResetRequestSerializer
    permission_classes = [IsAuthenticated, IsAdmin]
    filterset_fields = ["handled"]


@api_view(["POST"])
@perm_classes([AllowAny])
def forgot_password(request):
    """Public: records a password-reset request and pings Admins. Responds
    generically either way so it can't be used to probe which emails exist."""
    email = (request.data.get("email") or "").strip()
    if email:
        user = User.objects.filter(email__iexact=email).first()
        PasswordResetRequest.objects.create(email=email, user=user)
        if user:
            notify_role("ADMIN", f"{user.get_full_name() or user.username} ({email}) requested a password reset.",
                        link="/users/")
    return Response({"detail": "If that account exists, an administrator has been notified to reset your password."})


class NotificationViewSet(viewsets.ModelViewSet):
    """Always self-scoped to the logged-in user -- no role gating, everyone
    just sees and manages their own notifications."""
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["is_read"]

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)

    @action(detail=False, methods=["get"])
    def my(self, request):
        qs = self.filter_queryset(self.get_queryset())
        return Response(self.get_serializer(qs, many=True).data)

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.is_read = True
        notification.save(update_fields=["is_read", "updated_at"])
        return Response(self.get_serializer(notification).data)

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        self.get_queryset().filter(is_read=False).update(is_read=True)
        return Response({"detail": "All notifications marked read."})
