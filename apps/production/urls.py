from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    BundleReceiptViewSet, ProductionQualityCheckViewSet, AccessoryIssueViewSet,
    BundleAccessoryIssueViewSet, OperatorAccessoryIssueViewSet, ProcessDispatchViewSet, SendToFinishingView,
)

router = DefaultRouter()
router.register("receipts", BundleReceiptViewSet, basename="bundle-receipt")
router.register("quality-checks", ProductionQualityCheckViewSet, basename="production-qc")
router.register("accessory-issues", AccessoryIssueViewSet, basename="accessory-issue")
router.register("bundle-accessory-issues", BundleAccessoryIssueViewSet, basename="bundle-accessory-issue")
router.register("operator-accessory-issues", OperatorAccessoryIssueViewSet, basename="operator-accessory-issue")
router.register("process-dispatches", ProcessDispatchViewSet, basename="process-dispatch")

urlpatterns = router.urls + [
    path("send-to-finishing/", SendToFinishingView.as_view(), name="send-to-finishing"),
]
