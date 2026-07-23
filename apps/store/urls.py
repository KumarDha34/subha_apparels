from rest_framework.routers import DefaultRouter
from .views import (
    FabricStockViewSet, StockTransactionViewSet,
    AccessoryStockViewSet, AccessoryStockTransactionViewSet, FinishedGoodsReceiptViewSet,
    OrderAdditionalChargeViewSet,
)

router = DefaultRouter()
router.register("fabric-stock", FabricStockViewSet, basename="fabric-stock")
router.register("transactions", StockTransactionViewSet, basename="stock-transaction")
router.register("accessory-stock", AccessoryStockViewSet, basename="accessory-stock")
router.register("accessory-transactions", AccessoryStockTransactionViewSet, basename="accessory-stock-transaction")
router.register("finished-goods", FinishedGoodsReceiptViewSet, basename="finished-goods")
router.register("additional-charges", OrderAdditionalChargeViewSet, basename="order-additional-charge")

urlpatterns = router.urls
