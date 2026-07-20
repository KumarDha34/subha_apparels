from rest_framework.routers import DefaultRouter
from .views import (
    FinishingQualityCheckViewSet, PackingViewSet, DispatchViewSet,
    FinishingOperationViewSet, FinishingReceiptViewSet,
)

router = DefaultRouter()
router.register("quality-checks", FinishingQualityCheckViewSet, basename="finishing-qc")
router.register("packing", PackingViewSet, basename="packing")
router.register("dispatch", DispatchViewSet, basename="dispatch")
router.register("operations", FinishingOperationViewSet, basename="finishing-operation")
router.register("receipts", FinishingReceiptViewSet, basename="finishing-receipt")

urlpatterns = router.urls
