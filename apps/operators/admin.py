from django.contrib import admin
from .models import Operator, OperatorRate, BundleAssignment, OperatorIncome

admin.site.register(Operator)
admin.site.register(OperatorRate)
admin.site.register(BundleAssignment)
admin.site.register(OperatorIncome)
