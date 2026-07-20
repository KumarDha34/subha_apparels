from rest_framework.routers import DefaultRouter
from .views import (
    PartyViewSet, ProductViewSet, ProductComponentViewSet, ColorViewSet,
    FabricTypeViewSet, SizeViewSet, VendorViewSet, AccessoryViewSet,
)

router = DefaultRouter()
router.register("parties", PartyViewSet, basename="party")
router.register("products", ProductViewSet, basename="product")
router.register("product-components", ProductComponentViewSet, basename="product-component")
router.register("colors", ColorViewSet, basename="color")
router.register("fabric-types", FabricTypeViewSet, basename="fabric-type")
router.register("sizes", SizeViewSet, basename="size")
router.register("vendors", VendorViewSet, basename="vendor")
router.register("accessories", AccessoryViewSet, basename="accessory")

urlpatterns = router.urls
