from django.urls import path

from apps.personal import views

urlpatterns = [
    path("personal/ledger", views.LedgerView.as_view()),
    path("personal/categories", views.CategoryListView.as_view()),
    path("personal/categories/<uuid:pk>", views.CategoryView.as_view()),
    path("personal/accounts", views.AccountListView.as_view()),
    path("personal/accounts/<uuid:pk>", views.AccountView.as_view()),
    path("personal/lines", views.LineListView.as_view()),
    path("personal/lines/bulk", views.BulkView.as_view()),
    path("personal/lines/<uuid:pk>", views.LineView.as_view()),
    path("personal/sort", views.SortView.as_view()),
]
