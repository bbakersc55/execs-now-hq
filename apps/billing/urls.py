from rest_framework.routers import DefaultRouter

from apps.billing import views

router = DefaultRouter()
router.register("invoices", views.InvoiceViewSet, basename="invoice")
router.register("invoice-settings", views.InvoiceSettingsView, basename="invoice-settings")
router.register("invoice-schedules", views.ScheduleViewSet, basename="invoice-schedule")
router.register("portal-invoices", views.PortalInvoiceViewSet, basename="portal-invoice")

urlpatterns = router.urls
