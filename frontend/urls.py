from django.urls import path
from . import views

urlpatterns = [
    # Root = login page (no /app/ prefix needed).
    path("", views.login_view, name="login"),

    # One dedicated dashboard per role.
    path("dashboard/admin/", views.page_view, {"page": "dashboard_admin"}, name="dashboard-admin"),
    path("dashboard/merchandising/", views.page_view, {"page": "dashboard_merchandising"}, name="dashboard-merchandising"),
    path("dashboard/store/", views.page_view, {"page": "dashboard_store"}, name="dashboard-store"),
    path("dashboard/cutting/", views.page_view, {"page": "dashboard_cutting"}, name="dashboard-cutting"),
    path("dashboard/production/", views.page_view, {"page": "dashboard_production"}, name="dashboard-production"),
    path("dashboard/finishing/", views.page_view, {"page": "dashboard_finishing"}, name="dashboard-finishing"),
    path("dashboard/accounts/", views.page_view, {"page": "dashboard_accounts"}, name="dashboard-accounts"),
    path("dashboard/operator/", views.page_view, {"page": "dashboard_operator"}, name="dashboard-operator"),

    # Admin-only extra screens.
    path("dashboard/kpi/", views.page_view, {"page": "dashboard_kpi"}, name="dashboard-kpi"),
    path("reports/", views.page_view, {"page": "admin_report"}, name="admin-report"),
    path("masters/", views.page_view, {"page": "masters"}, name="masters"),
    path("users/", views.page_view, {"page": "users"}, name="users"),

    # Merchandising's own screens: order management plus the master-data
    # screens it needs day-to-day (Party/Product/Color/Fabric Type).
    path("merchandising/orders/", views.page_view, {"page": "merchandising_orders"}, name="merchandising-orders"),
    path("merchandising/parties/", views.page_view, {"page": "merchandising_parties"}, name="merchandising-parties"),
    path("merchandising/products/", views.page_view, {"page": "merchandising_products"}, name="merchandising-products"),
    path("merchandising/colors/", views.page_view, {"page": "merchandising_colors"}, name="merchandising-colors"),
    path("merchandising/fabric-types/", views.page_view, {"page": "merchandising_fabric_types"}, name="merchandising-fabric-types"),

    # Store's purchasing workflow: order-specific / bulk / customer-supplied
    # purchase creation, an overview with receiving, and accessory master data.
    path("store/purchases/", views.page_view, {"page": "store_purchase_orders"}, name="store-purchases"),
    path("store/purchases/order-specific/", views.page_view, {"page": "store_purchase_order_specific"}, name="store-purchase-order-specific"),
    path("store/purchases/bulk/", views.page_view, {"page": "store_purchase_bulk"}, name="store-purchase-bulk"),
    path("store/purchases/customer-supplied/", views.page_view, {"page": "store_purchase_customer_supplied"}, name="store-purchase-customer-supplied"),
    path("store/accessories/", views.page_view, {"page": "store_accessories"}, name="store-accessories"),
    path("store/stock/", views.page_view, {"page": "store_stock"}, name="store-stock"),
    path("store/finished-goods/", views.page_view, {"page": "store_finished_goods"}, name="store-finished-goods"),
    path("store/vendors/", views.page_view, {"page": "store_vendors"}, name="store-vendors"),
    path("store/issue-materials/", views.page_view, {"page": "store_issue_materials"}, name="store-issue-materials"),
    path("store/issue-accessories/", views.page_view, {"page": "store_issue_accessories"}, name="store-issue-accessories"),

    # Accounts' own screens: purchase-order visibility, payments, and
    # income/expense recording -- the dashboard itself stays overview-only.
    path("accounts/purchase-orders/", views.page_view, {"page": "accounts_purchase_orders"}, name="accounts-purchase-orders"),
    path("accounts/payments/", views.page_view, {"page": "accounts_payments"}, name="accounts-payments"),
    path("accounts/income-expenses/", views.page_view, {"page": "accounts_income_expenses"}, name="accounts-income-expenses"),
    path("accounts/order-pnl/", views.page_view, {"page": "accounts_order_pnl"}, name="accounts-order-pnl"),
    path("accounts/quotations/", views.page_view, {"page": "accounts_quotations"}, name="accounts-quotations"),

    # Cutting's own screens: receiving fabric from Store, recording the
    # actual cut result, and bundling -- the dashboard stays overview-only.
    path("cutting/orders/", views.page_view, {"page": "cutting_orders"}, name="cutting-orders-list"),
    path("cutting/receive-fabric/", views.page_view, {"page": "cutting_receive_fabric"}, name="cutting-receive-fabric"),
    path("cutting/record-cut/", views.page_view, {"page": "cutting_record_cut"}, name="cutting-record-cut"),
    path("cutting/bundles/", views.page_view, {"page": "cutting_bundles"}, name="cutting-bundles"),
    path("cutting/issue-accessories/", views.page_view, {"page": "cutting_issue_accessories"}, name="cutting-issue-accessories"),
    path("cutting/setup/", views.page_view, {"page": "cutting_setup"}, name="cutting-setup"),

    # Production's own screens: accessories received from Store, receiving
    # bundles from Cutting, allocating to operators, and performance/income.
    path("production/accessories/", views.page_view, {"page": "production_accessories"}, name="production-accessories"),
    path("production/receive-bundles/", views.page_view, {"page": "production_receive_bundles"}, name="production-receive-bundles"),
    path("production/bundle-allocation/", views.page_view, {"page": "production_bundle_allocation"}, name="production-bundle-allocation"),
    path("production/send-to-finishing/", views.page_view, {"page": "production_send_to_finishing"}, name="production-send-to-finishing"),
    path("production/processing/", views.page_view, {"page": "production_processing"}, name="production-processing"),
    path("production/operators/", views.page_view, {"page": "production_operators"}, name="production-operators"),
    path("production/performance/", views.page_view, {"page": "production_performance"}, name="production-performance"),

    # Finishing's own screens: operation-type-aware finishing work with
    # cost tracking, and dispatch with printable packing list/challan --
    # the dashboard stays overview-only.
    path("finishing/operations/", views.page_view, {"page": "finishing_operations"}, name="finishing-operations"),
    path("finishing/dispatch/", views.page_view, {"page": "finishing_dispatch"}, name="finishing-dispatch"),
]
