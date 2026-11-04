from rest_framework.routers import DefaultRouter

from apps.finance import views
from apps.finance.bankfeeds import views as bank_views

router = DefaultRouter()
router.register("finance-entries", views.EntryViewSet, basename="finance-entry")
router.register("finance-accounts", views.AccountViewSet, basename="finance-account")
router.register("finance-categories", views.CategoryViewSet, basename="finance-category")
router.register("finance-settings", views.FinanceSettingsView, basename="finance-settings")
router.register("finance-reports", views.ReportView, basename="finance-report")
router.register("finance-imports", views.ImportViewSet, basename="finance-import")
router.register("finance-rules", views.RuleViewSet, basename="finance-rule")
router.register("finance-payees", views.PayeeView, basename="finance-payee")
router.register("finance-reconcile", views.ReconcileViewSet, basename="finance-reconcile")
router.register("finance-months", views.MonthViewSet, basename="finance-month")
router.register("finance-forecast", views.ForecastViewSet, basename="finance-forecast")
router.register("finance-bank", bank_views.BankConnectionViewSet, basename="finance-bank")

urlpatterns = router.urls
