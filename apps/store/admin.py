from django.contrib import admin
from .models import FabricStock, StockTransaction, AccessoryStock, AccessoryStockTransaction

admin.site.register(FabricStock)
admin.site.register(StockTransaction)
admin.site.register(AccessoryStock)
admin.site.register(AccessoryStockTransaction)
