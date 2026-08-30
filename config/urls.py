from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from rest_framework_simplejwt.views import TokenRefreshView
from apps.users.views import CustomTokenObtainPairView

urlpatterns = [
    path("admin/", admin.site.urls),

    # Auth
    path("api/auth/login/", CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    # API schema / docs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),

    # Module APIs
    path("api/users/", include("apps.users.urls")),
    path("api/master/", include("apps.master_data.urls")),
    path("api/store/", include("apps.store.urls")),
    path("api/orders/", include("apps.orders.urls")),
    path("api/cutting/", include("apps.cutting.urls")),
    path("api/operators/", include("apps.operators.urls")),
    path("api/production/", include("apps.production.urls")),
    path("api/finishing/", include("apps.finishing.urls")),
    path("api/accounts/", include("apps.finance.urls")),

    # Frontend (root "/" = login page; dashboards live under /dashboard/<role>/)
    path("", include("frontend.urls")),
]

if not settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)