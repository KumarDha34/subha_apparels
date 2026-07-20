from django.contrib import admin
from .models import PurchaseOrder, PurchaseOrderItem, Invoice, PaymentRecord, IncomeRecord, ExpenseRecord

admin.site.register(PurchaseOrder)
admin.site.register(PurchaseOrderItem)
admin.site.register(Invoice)
admin.site.register(PaymentRecord)
admin.site.register(IncomeRecord)
admin.site.register(ExpenseRecord)
