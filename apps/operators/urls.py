from rest_framework.routers import DefaultRouter
from .views import OperatorViewSet, OperatorRateViewSet, BundleAssignmentViewSet, OperatorIncomeViewSet

router = DefaultRouter()
router.register("operators", OperatorViewSet, basename="operator")
router.register("rates", OperatorRateViewSet, basename="operator-rate")
router.register("assignments", BundleAssignmentViewSet, basename="bundle-assignment")
router.register("income", OperatorIncomeViewSet, basename="operator-income")

urlpatterns = router.urls
