from django.contrib import admin
from .models import Party, Product, ProductComponent, Color, FabricType, Size, Vendor, Accessory

admin.site.register(Party)
admin.site.register(Product)
admin.site.register(ProductComponent)
admin.site.register(Color)
admin.site.register(FabricType)
admin.site.register(Size)
admin.site.register(Vendor)
admin.site.register(Accessory)
