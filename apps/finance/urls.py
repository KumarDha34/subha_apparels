from rest_framework.routers import DefaultRouter
from django.urls import path
from .views import (
    PurchaseOrderViewSet, InvoiceViewSet, PaymentRecordViewSet,
    IncomeRecordViewSet, ExpenseRecordViewSet, AccountsSummaryView, OrderPnLView,
    ManagementKPIView, QuotationViewSet, CustomerInvoiceViewSet, PartyStatementView,
    SupplierStatementView,
)
from .reports import AdminReportView
from .product_pnl import ProductPnLListView, ProductPnLDetailView
from .admin_dashboard import AdminFinancialView

router = DefaultRouter()
router.register("purchase-orders", PurchaseOrderViewSet, basename="purchase-order")
router.register("invoices", InvoiceViewSet, basename="invoice")
router.register("payments", PaymentRecordViewSet, basename="payment-record")
router.register("income", IncomeRecordViewSet, basename="income-record")
router.register("expenses", ExpenseRecordViewSet, basename="expense-record")
router.register("quotations", QuotationViewSet, basename="quotation")
router.register("customer-invoices", CustomerInvoiceViewSet, basename="customer-invoice")

urlpatterns = [
    path("summary/", AccountsSummaryView.as_view(), name="accounts-summary"),
    path("admin-dashboard/", AdminFinancialView.as_view(), name="admin-dashboard"),
    path("kpi/", ManagementKPIView.as_view(), name="management-kpi"),
    path("report/", AdminReportView.as_view(), name="admin-report"),
    path("orders/<int:pk>/pnl/", OrderPnLView.as_view(), name="order-pnl"),
    path("party-statement/", PartyStatementView.as_view(), name="party-statement"),
    path("supplier-statement/", SupplierStatementView.as_view(), name="supplier-statement"),
    path("product-pnl/", ProductPnLListView.as_view(), name="product-pnl-list"),
    path("product-pnl/<int:pk>/", ProductPnLDetailView.as_view(), name="product-pnl-detail"),
] + router.urls
