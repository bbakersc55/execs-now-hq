from rest_framework.routers import DefaultRouter

from apps.finance import views

router = DefaultRouter()
router.register("finance-entries", views.EntryViewSet, basename="finance-entry")
router.register("finance-accounts", views.AccountViewSet, basename="finance-account")
router.register("finance-categories", views.CategoryViewSet, basename="finance-category")
router.register("finance-settings", views.FinanceSettingsView, basename="finance-settings")
router.register("finance-reports", views.ReportView, basename="finance-report")

urlpatterns = router.urls
