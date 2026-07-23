from django.contrib import admin
from .models import Operator, BundleAssignment, OperatorIncome

admin.site.register(Operator)
admin.site.register(BundleAssignment)
admin.site.register(OperatorIncome)
