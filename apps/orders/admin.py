from django.contrib import admin
from .models import Order, OrderItem, OrderItemColor, OrderItemColorSize

admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(OrderItemColor)
admin.site.register(OrderItemColorSize)
