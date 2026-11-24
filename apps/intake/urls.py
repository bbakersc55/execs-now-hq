from django.urls import path

from . import views

urlpatterns = [
    path("intake/companies", views.CompaniesView.as_view()),
    path("intake/companies/<str:company_id>/form", views.FormView.as_view()),
    path("intake/companies/<str:company_id>/form/image", views.FormImageView.as_view()),
    path("intake/companies/<str:company_id>/refresh", views.RefreshView.as_view()),
    path("intake/companies/<str:company_id>/test-mode", views.TestModeView.as_view()),
    path("intake/companies/<str:company_id>/submissions", views.SubmissionsView.as_view()),
    path("intake/submissions/<str:submission_id>", views.SubmissionView.as_view()),
    path("intake/submissions/<str:submission_id>/answers", views.AnswersView.as_view()),
    path("intake/submissions/<str:submission_id>/secret", views.SecretView.as_view()),
    path("intake/submissions/<str:submission_id>/reveal", views.RevealView.as_view()),
    path("intake/submissions/<str:submission_id>/tax-code", views.TaxCodeView.as_view()),
    path("intake/submissions/<str:submission_id>/tax-show", views.TaxShowView.as_view()),
    path("intake/submissions/<str:submission_id>/staff", views.StaffView.as_view()),
    path("intake/submissions/<str:submission_id>/check", views.CheckView.as_view()),
    path("intake/submissions/<str:submission_id>/link", views.LinkView.as_view()),
    path("intake/submissions/<str:submission_id>/reopen", views.ReopenView.as_view()),
    path("intake/submissions/<str:submission_id>/discard", views.DiscardView.as_view()),
    path("intake/submissions/<str:submission_id>/send", views.SendView.as_view()),
    path("intake/submissions/<str:submission_id>/run", views.RunView.as_view()),
    path("intake/submissions/<str:submission_id>/files", views.FilesView.as_view()),
    path("intake/submissions/<str:submission_id>/files/<str:file_id>", views.FileView.as_view()),
    path("intake/submissions/<str:submission_id>/dates/place", views.PlaceDatesView.as_view()),
    path("intake/submissions/<str:submission_id>/dates/<str:date_id>/cancel",
         views.CancelDateView.as_view()),
]
