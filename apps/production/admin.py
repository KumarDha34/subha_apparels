from django.contrib import admin
from .models import BundleReceipt, ProductionQualityCheck, AccessoryIssue, BundleAccessoryIssue

admin.site.register(BundleReceipt)
admin.site.register(ProductionQualityCheck)
admin.site.register(AccessoryIssue)
admin.site.register(BundleAccessoryIssue)
