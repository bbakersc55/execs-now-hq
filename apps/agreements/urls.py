from django.urls import path

from . import views

urlpatterns = [
    path("agreements/companies", views.CompaniesView.as_view()),
    path("agreements/companies/<str:company_id>", views.CompanyView.as_view()),
    path("agreements/companies/<str:company_id>/agreements", views.CreateView.as_view()),
    path("agreements/companies/<str:company_id>/preview", views.PreviewView.as_view()),
    path("agreements/companies/<str:company_id>/access", views.AccessView.as_view()),
    path("agreements/companies/<str:company_id>/settings", views.SettingsView.as_view()),
    path("agreements/companies/<str:company_id>/authority", views.AuthorityView.as_view()),
    path("agreements/companies/<str:company_id>/documents", views.DocumentsView.as_view()),
    path("agreements/<str:agreement_id>", views.AgreementView.as_view()),
    path("agreements/<str:agreement_id>/pdf", views.PdfView.as_view()),
    path("agreements/<str:agreement_id>/<str:action>", views.ActionView.as_view()),
]
