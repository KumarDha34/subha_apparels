from django.contrib import admin
from .models import FinishingQualityCheck, Packing, Dispatch, FinishingOperation, FinishingReceipt

admin.site.register(FinishingQualityCheck)
admin.site.register(Packing)
admin.site.register(Dispatch)
admin.site.register(FinishingOperation)
admin.site.register(FinishingReceipt)
