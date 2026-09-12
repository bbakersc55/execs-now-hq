from rest_framework.routers import DefaultRouter

from apps.crm import views
from apps.crm import views_gmail

router = DefaultRouter()
router.register("contacts", views.ContactViewSet, basename="contact")
router.register("companies", views.CompanyViewSet, basename="company")
router.register("pipelines", views.PipelineViewSet, basename="pipeline")
router.register("pipeline-stages", views.PipelineStageViewSet, basename="pipeline-stage")
router.register("contact-types", views.ContactTypeViewSet, basename="contact-type")
router.register("service-categories", views.ServiceCategoryViewSet, basename="service-category")
router.register("stage-automations", views.StageAutomationViewSet, basename="stage-automation")
router.register("outbox", views.OutboxViewSet, basename="outbox")
router.register("dev-allowlist", views.DevSendAllowlistViewSet,
                basename="dev-allowlist")
router.register("mail-preference", views.MailPreferenceView,
                basename="mail-preference")
router.register("imports", views.ImportViewSet, basename="import")
router.register("import-profiles", views.ImportMappingProfileViewSet,
                basename="import-profile")
router.register("email-templates", views.EmailTemplateViewSet, basename="email-template")
router.register("referral-settings", views.ReferralSettingsView, basename="referral-settings")
router.register("gmail-connection", views_gmail.GmailConnectionViewSet,
                basename="gmail-connection")

urlpatterns = router.urls
