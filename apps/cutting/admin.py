from django.contrib import admin
from .models import CuttingOrder, CuttingPiece, Bundle, Marker

admin.site.register(CuttingOrder)
admin.site.register(CuttingPiece)
admin.site.register(Bundle)
admin.site.register(Marker)
