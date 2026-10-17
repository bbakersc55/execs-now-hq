from django.urls import path

from apps.personal import views, views_budget as vb

urlpatterns = [
    path("personal/ledger", views.LedgerView.as_view()),
    # Stop 2: the budget.
    path("personal/budget", vb.BudgetView.as_view()),
    path("personal/budget/accept", vb.BudgetAcceptView.as_view()),
    path("personal/budget/assign", vb.AssignView.as_view()),
    path("personal/budget/explain", vb.ExplainBudgetView.as_view()),
    path("personal/envelopes", vb.EnvelopeListView.as_view()),
    path("personal/envelopes/<uuid:pk>", vb.EnvelopeView.as_view()),
    path("personal/envelopes/<uuid:pk>/cover", vb.EnvelopeView.as_view()),
    path("personal/questions", vb.QuestionListView.as_view()),
    path("personal/questions/<uuid:pk>", vb.QuestionView.as_view()),
    path("personal/goals", vb.GoalListView.as_view()),
    path("personal/goals/<uuid:pk>", vb.GoalView.as_view()),
    path("personal/categories", views.CategoryListView.as_view()),
    path("personal/categories/<uuid:pk>", views.CategoryView.as_view()),
    path("personal/accounts", views.AccountListView.as_view()),
    path("personal/accounts/<uuid:pk>", views.AccountView.as_view()),
    path("personal/lines", views.LineListView.as_view()),
    path("personal/lines/bulk", views.BulkView.as_view()),
    path("personal/lines/<uuid:pk>", views.LineView.as_view()),
    path("personal/sort", views.SortView.as_view()),
    path("personal/sort-with-claude", views.SortWithClaudeView.as_view()),
    path("personal/imports", views.ImportListView.as_view()),
    path("personal/imports/detect", views.ImportDetectView.as_view()),
    path("personal/imports/dry-run", views.ImportDryRunView.as_view()),
    path("personal/imports/<uuid:pk>", views.ImportDetailView.as_view()),
    path("personal/imports/<uuid:pk>/rows/<uuid:row_id>", views.ImportRowView.as_view()),
    path("personal/imports/<uuid:pk>/commit", views.ImportCommitView.as_view()),
    path("personal/imports/<uuid:pk>/rollback", views.ImportRollbackView.as_view()),
    path("personal/accounts/<uuid:pk>/reconciliations",
         views.ReconciliationListView.as_view()),
    path("personal/reconciliations/<uuid:pk>", views.ReconciliationView.as_view()),
    path("personal/reconciliations/<uuid:pk>/<str:step>", views.ReconciliationView.as_view()),
]
