from rest_framework.routers import DefaultRouter

from apps.crm import views, views_campaigns, views_queue
from apps.crm import views_gmail
from apps.crm import views_microsoft
from apps.crm import views_inbound
from apps.crm import views_referrals

router = DefaultRouter()
router.register("contacts", views.ContactViewSet, basename="contact")
router.register("campaigns", views_campaigns.CampaignViewSet, basename="campaign")
router.register("leave-requests", views_inbound.LeaveRequestViewSet, basename="leave-request")
router.register("sending-queue", views_queue.SendingQueueView, basename="sending-queue")
router.register("referrals", views_referrals.ReferralViewSet, basename="referral")
router.register("introductions", views_referrals.IntroductionViewSet, basename="introduction")
router.register("companies", views.CompanyViewSet, basename="company")
router.register("pipelines", views.PipelineViewSet, basename="pipeline")
router.register("pipeline-stages", views.PipelineStageViewSet, basename="pipeline-stage")
router.register("contact-types", views.ContactTypeViewSet, basename="contact-type")
router.register("service-categories", views.ServiceCategoryViewSet, basename="service-category")
router.register("contact-tags", views.ContactTagViewSet, basename="contact-tag")
router.register("stage-automations", views.StageAutomationViewSet, basename="stage-automation")
router.register("pipeline-notices", views.PipelineNoticeViewSet, basename="pipeline-notice")
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
router.register("email-threads", views_inbound.EmailThreadViewSet,
                basename="email-thread")
router.register("unmatched-inbound", views_inbound.UnmatchedInboundViewSet,
                basename="unmatched-inbound")
router.register("gmail-connection", views_gmail.GmailConnectionViewSet,
                basename="gmail-connection")
router.register("microsoft-connection", views_microsoft.MicrosoftConnectionViewSet,
                basename="microsoft-connection")
router.register("mail-provider", views_microsoft.MailProviderView, basename="mail-provider")

urlpatterns = router.urls
