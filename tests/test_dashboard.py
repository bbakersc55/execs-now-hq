"""The landing page's numbers (design brief, Tier 2).

**One call, one set of scoping rules.** The point of the endpoint being an
aggregate rather than five is that a CF can never be shown a total that
includes work they cannot open — so most of what follows is about who sees
which number, not about arithmetic.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.crm.models import Task
from apps.work.models import Digest, Goal, GoalResolution

from . import registry_config  # noqa: F401
from .factories import (
    ClientAssignmentFactory, ClientCompanyFactory, ContactFactory, DigestFactory,
    GoalFactory, MembershipFactory, TaskFactory,
)


@pytest.fixture
def board(seeded_tenant, in_tenant_a):
    """A week with something in every panel."""
    today = timezone.localdate()
    acme = ClientCompanyFactory(tenant=seeded_tenant, name="Acme Facilities")
    north = ClientCompanyFactory(tenant=seeded_tenant, name="Northwind")

    TaskFactory(tenant=seeded_tenant, title="Late one", client_company=acme,
                due_date=today - timedelta(days=2), status=Task.Status.IN_PROGRESS)
    TaskFactory(tenant=seeded_tenant, title="Due today", client_company=acme,
                due_date=today, status=Task.Status.NOT_STARTED)
    TaskFactory(tenant=seeded_tenant, title="Due Friday", client_company=north,
                due_date=today + timedelta(days=3), status=Task.Status.NOT_STARTED)
    # Outside the window, and one already done: neither is "due this week".
    TaskFactory(tenant=seeded_tenant, title="Next month", client_company=north,
                due_date=today + timedelta(days=30), status=Task.Status.NOT_STARTED)
    TaskFactory(tenant=seeded_tenant, title="Finished", client_company=acme,
                due_date=today, status=Task.Status.DONE)

    GoalFactory(tenant=seeded_tenant, title="Cut DSO", client_company=acme)
    return {"acme": acme, "north": north, "today": today}


@pytest.mark.django_db
def test_the_four_tiles_count_what_they_say(seeded_tenant, ff, api, board):
    body = api.as_(ff).get("/api/dashboard/").json()

    tiles = body["tiles"]
    assert tiles["tasks_due"] == 3            # late, today, Friday
    # Overdue is named separately: a number that folds "late" into "soon" is a
    # number you stop reading.
    assert tiles["tasks_overdue"] == 1
    assert tiles["goals_open"] == 1
    assert body["window_days"] == 7


@pytest.mark.django_db
def test_due_by_day_names_every_day_including_the_quiet_ones(
    seeded_tenant, ff, api, board
):
    """A list that skips quiet days makes a light week look like a missing one,
    and hides that Thursday is the day with everything in it."""
    days = api.as_(ff).get("/api/dashboard/").json()["due_by_day"]

    assert days[0]["label"] == "Overdue" and days[0]["count"] == 1
    named = {row["label"]: row["count"] for row in days}
    assert named["Today"] == 1
    assert named["Tomorrow"] == 0             # present, and zero
    assert len([row for row in days if not row["overdue"]]) == 8   # today + 7


@pytest.mark.django_db
def test_a_goal_resolved_is_not_open_and_a_resumed_one_is_again(
    seeded_tenant, ff, api, board
):
    """A goal's state is its **latest** resolution row, so "open" cannot be a
    column filter: a paused goal that was resumed is current again."""
    goal = Goal.objects.get(title="Cut DSO")
    GoalResolution.objects.create(tenant=seeded_tenant, goal=goal,
                                  resolution=GoalResolution.Resolution.PAUSED,
                                  reason="Client asked to hold until Q4.")

    assert api.as_(ff).get("/api/dashboard/").json()["tiles"]["goals_open"] == 0

    GoalResolution.objects.create(
        tenant=seeded_tenant, goal=goal,
        resolution=GoalResolution.Resolution.RESUMED,
        reason="Q4 started.", resolved_at=timezone.now() + timedelta(minutes=1))

    assert api.as_(ff).get("/api/dashboard/").json()["tiles"]["goals_open"] == 1


@pytest.mark.django_db
def test_pipeline_movement_counts_only_the_last_week(seeded_tenant, ff, api, board):
    from apps.crm.models import Pipeline, PipelineStage, StageChange

    contact = ContactFactory(tenant=seeded_tenant, first_name="Dana",
                             last_name="Reyes")
    pipeline = Pipeline.objects.first()
    stages = list(PipelineStage.objects.filter(pipeline=pipeline)[:2])
    recent = StageChange.objects.create(
        tenant=seeded_tenant, contact=contact, pipeline=pipeline,
        from_stage=stages[0], to_stage=stages[1])
    old = StageChange.objects.create(
        tenant=seeded_tenant, contact=contact, pipeline=pipeline,
        from_stage=stages[0], to_stage=stages[1])
    StageChange.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=30))

    body = api.as_(ff).get("/api/dashboard/").json()

    assert body["tiles"]["pipeline_moves"] == 1
    assert [row["id"] for row in body["pipeline"]] == [str(recent.pk)]
    assert body["pipeline"][0]["to"] == stages[1].label


@pytest.mark.django_db
def test_pending_digests_are_listed_for_approval(seeded_tenant, ff, api, board):
    contact = ContactFactory(tenant=seeded_tenant, company=board["acme"])
    DigestFactory(tenant=seeded_tenant, contact=contact,
                  state=Digest.State.PENDING)
    DigestFactory(tenant=seeded_tenant, contact=contact, state=Digest.State.SENT)

    body = api.as_(ff).get("/api/dashboard/").json()

    assert body["tiles"]["digests_pending"] == 1
    assert len(body["digests"]) == 1


@pytest.mark.django_db
def test_client_cards_lead_with_what_is_overdue(seeded_tenant, ff, api, board):
    """The card is scanned for one question — do I need to open this? — so it
    is ordered by the answer."""
    cards = api.as_(ff).get("/api/dashboard/").json()["clients"]

    assert [card["name"] for card in cards] == ["Acme Facilities", "Northwind"]
    acme = cards[0]
    assert acme["overdue"] == 1
    assert acme["open_tasks"] == 2           # late + today; the done one is not
    assert acme["open_goals"] == 1


@pytest.mark.django_db
def test_a_cf_sees_only_their_own_accounts_in_every_figure(
    seeded_tenant, api, board, in_tenant_a
):
    """The reason this is one endpoint and not five: a total that includes work
    the caller cannot open is a total that leaks."""
    cf = MembershipFactory(tenant=seeded_tenant, role="CF")
    ClientAssignmentFactory(tenant=seeded_tenant, user=cf.user,
                            company=board["north"])

    body = api.as_(cf).get("/api/dashboard/").json()

    assert [card["name"] for card in body["clients"]] == ["Northwind"]
    assert body["tiles"]["tasks_due"] == 1          # Friday's, at Northwind
    assert body["tiles"]["goals_open"] == 0         # the goal is Acme's


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["FCC", "ECC"])
def test_a_client_user_has_no_dashboard(role, seeded_tenant, api, in_tenant_a):
    """Their landing page is the portal, and every figure here spans the
    practice."""
    company = ClientCompanyFactory(tenant=seeded_tenant)
    membership = MembershipFactory(tenant=seeded_tenant, role=role,
                                   client_company=company)

    assert api.as_(membership).get("/api/dashboard/").status_code == 403


@pytest.mark.django_db
def test_another_tenants_work_is_not_counted(seeded_tenant, ff, api, board,
                                             tenant_b):
    from apps.tenancy.context import tenant_context

    with tenant_context(tenant_b.id):
        other = ClientCompanyFactory(tenant=tenant_b)
        TaskFactory(tenant=tenant_b, client_company=other,
                    due_date=board["today"], status=Task.Status.NOT_STARTED)

    body = api.as_(ff).get("/api/dashboard/").json()

    assert body["tiles"]["tasks_due"] == 3
    assert all(card["name"] != other.name for card in body["clients"])
