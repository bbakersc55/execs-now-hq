from django.urls import path

from apps.scorecard import views

urlpatterns = [
    path("scorecard/", views.BoardView.as_view(), name="scorecard"),
    path("scorecard/companies/", views.CompaniesView.as_view(), name="scorecard-companies"),
    path("scorecard/entry/", views.EntryView.as_view(), name="scorecard-entry"),
    path("scorecard/readings/", views.ReadingsView.as_view(), name="scorecard-readings"),
    path("scorecard/readings/<str:pk>/history/", views.HistoryView.as_view(),
         name="scorecard-reading-history"),
    path("scorecard/bulk/", views.BulkView.as_view(), name="scorecard-bulk"),
    path("scorecard/notices/", views.NoticesView.as_view(), name="scorecard-notices"),
    path("scorecard/setup/", views.SetupView.as_view(), name="scorecard-setup"),
    path("scorecard/pages/", views.PagesView.as_view(), name="scorecard-pages"),
    path("scorecard/pages/order/", views.PageOrderView.as_view(), name="scorecard-page-order"),
    path("scorecard/pages/<str:pk>/", views.PageView.as_view(), name="scorecard-page"),
    path("scorecard/pages/<str:pk>/archive/", views.PageArchiveView.as_view(),
         name="scorecard-page-archive"),
    path("scorecard/pages/<str:pk>/restore/", views.PageRestoreView.as_view(),
         name="scorecard-page-restore"),
    path("scorecard/kpis/", views.KpisView.as_view(), name="scorecard-kpis"),
    path("scorecard/kpis/order/", views.KpiOrderView.as_view(), name="scorecard-kpi-order"),
    path("scorecard/kpis/<str:pk>/", views.KpiView.as_view(), name="scorecard-kpi"),
    path("scorecard/kpis/<str:pk>/archive/", views.KpiArchiveView.as_view(),
         name="scorecard-kpi-archive"),
    path("scorecard/kpis/<str:pk>/restore/", views.KpiRestoreView.as_view(),
         name="scorecard-kpi-restore"),
    path("scorecard/starters/", views.StartersView.as_view(), name="scorecard-starters"),
]
