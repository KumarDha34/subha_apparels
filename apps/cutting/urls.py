from rest_framework.routers import DefaultRouter
from .views import CuttingOrderViewSet, CuttingPieceViewSet, BundleViewSet, MarkerViewSet

router = DefaultRouter()
router.register("cutting-orders", CuttingOrderViewSet, basename="cutting-order")
router.register("pieces", CuttingPieceViewSet, basename="cutting-piece")
router.register("bundles", BundleViewSet, basename="bundle")
router.register("markers", MarkerViewSet, basename="marker")

urlpatterns = router.urls
