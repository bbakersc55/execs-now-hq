"""What `seed_demo` makes (owner, 2026-10-08): Summit Operations Partners,
with staff, eleven clients, a pipeline, partners, work in every state,
strategy sessions, a meeting queue, digests, email, and invoices and books
from January 2025. One seed, read many ways; then a second, which resets it.

The seed runs the app's own code for two years of history, so this is the
slowest test in the suite, on purpose: it is the only thing that proves the
demo can be built at all."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.conf import settings
from django.core.management import call_command
from django.db.models import Count
from django.urls import get_resolver
from django.utils import timezone

from . import registry_config  # noqa: F401

OWNER = "owner@getexecutivesnow.invalid"


def _name():
    return settings.DATABASES["default"]["NAME"]


def _list_routes():
    """Every route that lists something and takes no argument."""
    found = set()

    def walk(patterns, prefix=""):
        for pattern in patterns:
            route = prefix + str(pattern.pattern)
            if hasattr(pattern, "url_patterns"):
                walk(pattern.url_patterns, route)
            elif (pattern.name or "").endswith("-list") and "<" not in route \
                    and "(?P" not in route:
                found.add("/" + route.replace("^", "").replace("$", "").replace("\\.", "."))
    walk(get_resolver().url_patterns)
    return sorted(path for path in found if path.startswith("/api/"))


@pytest.mark.django_db
def test_the_seed_makes_the_whole_practice_and_a_second_run_resets_it(
        settings, monkeypatch, api, capsys):
    from apps.accounts.models import User
    from apps.billing.models import ClientInvoice, ClientInvoiceSchedule
    from apps.crm.models import (
        Campaign, CampaignRecipient, Company, Contact, ContactEmail, EmailSuppression,
        Enrollment, GmailConnection, OutboxMessage, PipelineStage, StageChange, Task,
        UnmatchedInbound,
    )
    from apps.crm.services import transport
    from apps.finance import payees, reports
    from apps.finance.models import (
        FinanceAccount, FinanceEntry, FinanceImportBatch, FinanceImportRow, FinanceRule,
        FinanceSettings,
    )
    from apps.meetings.models import Commitment, MeetingProposal, ProposalItem
    from apps.notes.models import Note
    from apps.platform.models import AgreementAcceptance
    from apps.strategy.models import (
        StrategyCallNotes, StrategyMapRow, StrategyPathNote, StrategySection,
        StrategySession, StrategySessionPrep, StrategyTemplate,
    )
    from apps.tenancy import contrast
    from apps.tenancy.context import tenant_context
    from apps.tenancy.demo import cast, money
    from apps.tenancy.models import ClientAssignment, Membership, StoredFile, Tenant
    from apps.work import milestones
    from apps.work.models import (
        Comment, Digest, Goal, GoalMeasurement, GoalMilestone, GoalOrderProposal,
        GoalProposal, GoalResolution, Stakeholder,
    )

    settings.APP_ENVIRONMENT, settings.IS_DEMO, settings.IS_LOCAL = "demo", True, False
    settings.DEMO_MAIL_REDIRECT = "redirect@demo-inbox.invalid"
    monkeypatch.setattr(transport.GmailTransport, "send",
                        lambda *a, **k: pytest.fail("the seed reached Gmail"))

    call_command("seed_demo", database=_name(), ff_email=OWNER)
    said = capsys.readouterr().out
    assert "Summit Operations Partners" in said and '"client companies": 11' in said

    tenant = Tenant.objects.get()
    today = timezone.localdate()
    with tenant_context(tenant.pk):
        # ------------------------------------------------------ the practice
        assert (tenant.name, tenant.slug) == ("Summit Operations Partners", "summit-demo")
        assert tenant.from_address == settings.DEMO_MAIL_FROM
        assert tenant.brand_footer_text == "Summit Operations Partners · Denver, CO"
        assert tenant.email_logo_id and tenant.email_mark_id
        assert all(check.ok for check in contrast.check(tenant.email_header_color,
                                                        tenant.email_accent_color))
        owner = User.objects.get(email=OWNER)
        assert owner.full_name == "John Carter" and owner.is_platform_owner
        assert AgreementAcceptance.objects.filter(user=owner).exists()
        roles = dict(Membership.objects.values_list("role").annotate(n=Count("id")))
        assert (roles["FF"], roles["CF"], roles["VA"]) == (1, 2, 2)
        for key, *_ in cast.ASSOCIATES:
            user = User.objects.get(email=next(a[2] for a in cast.ASSOCIATES if a[0] == key))
            assert ClientAssignment.objects.filter(user=user).count() == 2
        assert Contact.objects.filter(is_1099_payee=True).count() == 5
        assert all(address.endswith(".example") for address in
                   ContactEmail.objects.values_list("address", flat=True)), \
            "every address is at a domain that cannot receive mail"

        # ------------------------------------------------- clients and seats
        clients = Company.objects.filter(is_client_company=True)
        assert clients.count() == 11
        fees = [row.lines[0]["unit_price_cents"] for row in
                ClientInvoiceSchedule.objects.filter(is_active=True)]
        assert len(fees) == 11 and min(fees) == 200_000 and max(fees) == 800_000
        assert sum(fees) / len(fees) == 400_000
        portal = Membership.objects.filter(role__in=("FCC", "ECC"))
        assert all(clients.filter(pk=m.client_company_id).exists() for m in portal)
        assert portal.filter(role="FCC").count() == 11
        assert portal.filter(user__last_login_at__isnull=True).count() == 2

        # --------------------------------------------------- the pipeline
        sales = PipelineStage.objects.filter(pipeline__kind="sales").exclude(semantic="won")
        for stage in sales:
            assert stage.positions.count() >= 3, f"{stage.label} has prospects in it"
        recent = StageChange.objects.filter(created_at__gte=timezone.now()
                                            - timedelta(days=60))
        assert recent.count() >= 60
        partners = Contact.objects.filter(types__code="referral_partner")
        enrolled = Enrollment.objects.filter(ended_at__isnull=True).count()
        assert partners.count() >= 36 and 0 < partners.count() - enrolled <= 10
        assert Contact.objects.filter(types__code="vendor",
                                      service_categories__isnull=False).distinct().count() >= 3

        # ---------------------------------------------------------- the work
        per_company = dict(Goal.objects.values_list("client_company__name")
                           .annotate(n=Count("id")))
        assert len(per_company) == 11 and all(1 <= n <= 3 for n in per_company.values())
        for goal in Goal.objects.all():
            assert goal.measurable_kind == "numeric" and goal.direction
            assert goal.baseline_value is not None and goal.target_value is not None
            readings = GoalMeasurement.objects.filter(goal=goal)
            months = max((today - goal.baseline_at).days // 31, 1)
            assert readings.count() >= min(months, 1), goal.title
        states = {milestones.state_of(m, today=today) for m in GoalMilestone.objects.all()}
        assert {"hit", "late", "due"} <= states | {"hit"} and "late" in states
        assert GoalMilestone.objects.filter(source_task__isnull=False).exists()
        statuses = dict(Task.objects.values_list("status").annotate(n=Count("id")))
        assert set(statuses) == set(Task.Status.values)
        assert statuses["done"] > sum(statuses.values()) / 2, "most of it is finished"
        open_tasks = Task.objects.exclude(status__in=("done", "cancelled"))
        assert 3 <= open_tasks.filter(due_date__lt=today).count() <= 12
        assert open_tasks.filter(due_date__gte=today,
                                 due_date__lte=today + timedelta(days=7)).count() >= 5
        kinds = list(GoalResolution.objects.values_list("resolution", flat=True))
        assert sorted(kinds) == ["achieved", "changed_course", "paused", "resumed"]
        assert all(GoalResolution.objects.values_list("reason", flat=True))
        assert GoalProposal.objects.filter(state="pending").count() == 1
        assert GoalOrderProposal.objects.filter(state="pending").count() == 1
        assert set(Stakeholder.objects.values_list("cadence", flat=True)) == \
            {"weekly", "every_update"}
        assert set(Comment.objects.values_list("visibility", flat=True)) == \
            {"internal", "shared"}
        commitments = Commitment.objects.filter(state="open")
        assert commitments.count() == 12
        assert commitments.filter(due_date__lt=today).count() == 2

        # -------------------------------------------------- strategy sessions
        assert StrategyTemplate.objects.filter(is_default=True).count() == 1
        assert StrategySection.objects.filter(kind="custom").count() == 1
        by_state = dict(StrategySession.objects.values_list("state")
                        .annotate(n=Count("id")))
        assert by_state == {"draft": 1, "in_call": 1, "complete": 1, "converted": 1}
        assert StrategySessionPrep.objects.get().state == "ready"
        live = StrategySession.objects.get(state="in_call")
        assert StrategyMapRow.objects.filter(session=live, state="proposed").count() >= 2
        done = StrategySession.objects.get(state="complete")
        assert done.pdf_file_id and StrategyCallNotes.objects.filter(session=done).exists()
        assert {"pro", "con"} == set(StrategyPathNote.objects.filter(session=done)
                                     .values_list("kind", flat=True))
        assert StrategyMapRow.objects.filter(session=done, from_call_notes=True).exists()
        assert StrategyMapRow.objects.filter(session=done, added_by=owner).exists()
        assert OutboxMessage.objects.filter(producer="strategy_pdf", state="sent",
                                            source_id=done.pk).exists()
        converted = StrategySession.objects.get(state="converted")
        made = Goal.objects.get(source_map_row__session=converted)
        assert made.measurements.exists() and made.projects.exists()

        # ----------------------------------- meetings, digests, email, notes
        proposals = dict(MeetingProposal.objects.values_list("state")
                         .annotate(n=Count("id")))
        assert 6 <= sum(proposals.values()) <= 8
        assert {"pending", "partially_actioned", "dismissed"} <= set(proposals)
        owner_kinds = {item.payload.get("owner_kind") for item in
                       ProposalItem.objects.filter(kind="action_item")}
        # Each kind of owner an action can have; "" is the practice's own.
        assert {"client", "prospect", "vendor", "third_party", ""} <= owner_kinds
        waiting = Digest.objects.filter(state="pending")
        assert 3 <= waiting.count() <= 4
        assert set(waiting.values_list("cadence", flat=True)) == {"weekly", "every_update"}
        assert Digest.objects.filter(state="sent").count() >= 10
        assert Campaign.objects.count() == 2
        assert CampaignRecipient.objects.filter(outbox_message__state="sent").count() >= 15
        assert UnmatchedInbound.objects.filter(state="pending").count() == 2
        assert EmailSuppression.objects.filter(category="marketing").count() == 1
        touches = OutboxMessage.objects.filter(state="pending_approval",
                                               producer="referral_touch")
        assert touches.count() == 5
        assert Note.objects.count() >= 12
        assert Note.objects.filter(pin_hash__isnull=False).count() == 1
        assert Note.objects.filter(source="recording", summary_state="accepted").count() == 1

        # ------------------------------------------------- invoices and books
        invoices = ClientInvoice.objects.all()
        by_status = dict(invoices.values_list("status").annotate(n=Count("id")))
        assert by_status.get("paid", 0) > 150 and by_status["partially_paid"] == 1
        assert by_status["void"] == 1 and invoices.get(status="void").void_reason
        assert invoices.filter(status="sent", due_date__lt=today).count() == 2
        assert invoices.filter(kind="contact", client_company__isnull=True).count() == 1
        assert invoices.order_by("issue_date").first().issue_date == date(2025, 1, 1)
        assert all(i.pdf_id for i in invoices.exclude(status="draft"))
        assert set(FinanceAccount.objects.values_list("kind", flat=True)) == {"bank", "card"}
        assert all(a.opening_balance_cents for a in FinanceAccount.objects.all())
        income = expenses = 0
        for year in (2025, today.year):
            report = reports.pnl(tenant, year=year)
            income += report["income"]["total"]
            expenses += report["expenses"]["total"]
            assert report["uncategorized"]["count"] == 0
        assert 0.55 <= (income - expenses) / income <= 0.60, "margin after contractors"
        entries = FinanceEntry.objects.filter(removed_at__isnull=True)
        assert entries.filter(kind="owner").count() >= 20
        assert entries.filter(kind="transfer").count() >= 20
        assert entries.filter(kind="income", direction="out").count() == 1    # a refund
        assert entries.filter(kind="expense", direction="in").count() == 1    # another
        batch = FinanceImportBatch.objects.get()
        assert batch.status == "committed"
        assert 1 <= FinanceRule.objects.count() <= 6
        assert FinanceImportRow.objects.filter(batch=batch,
                                               outcome="invoice_payment").count() >= 1
        assert FinanceSettings.objects.get().locked_through == date(2025, 12, 31)
        over = [row for row in payees.report(tenant, year=2025)["payees"]
                if row["over_threshold"]]
        assert len(over) >= 2
        bank = FinanceAccount.objects.get(kind="bank")
        assert reports.account_balance(tenant, bank, today) > 0
        files_first = StoredFile.objects.count()
        counts_first = (Contact.objects.count(), Task.objects.count(), invoices.count())

        # ---------------------------------- every screen's list, by each role
        people = {
            "practice owner": Membership.objects.get(role="FF"),
            "associate": Membership.objects.filter(role="CF").first(),
            "assistant": Membership.objects.filter(role="VA").first(),
            "client owner": Membership.objects.filter(
                role="FCC", user__last_login_at__isnull=False).first(),
        }
    routes = _list_routes()
    assert len(routes) > 30
    for who, membership in people.items():
        client = api.as_(membership)
        for path in routes + ["/api/me"]:
            status = client.get(path).status_code
            assert status < 500, f"{path} answered {status} for the {who}"
    # An assistant still has no financials, in the demo as anywhere.
    assert api.as_(people["assistant"]).get("/api/finance-entries/").status_code in (403, 404)

    # -------------------------------------------------- the second run resets
    with tenant_context(tenant.pk):
        from apps.tenancy.models import SecretKind, TenantSecret

        secret = TenantSecret.all_objects.create(
            tenant=tenant, kind=SecretKind.GMAIL_REFRESH, user=owner,
            ciphertext=b"sealed", last4="oken")
        GmailConnection.all_objects.create(
            tenant=tenant, user=owner, email_address=OWNER, scopes=["gmail.send"],
            send_as_address=settings.DEMO_MAIL_FROM, send_as_verified_at=timezone.now(),
            secret=secret)
    # A short history is enough to prove the reset; the long one is above.
    first_of_this_month = today.replace(day=1)
    monkeypatch.setattr(money, "FIRST", (first_of_this_month - timedelta(days=200))
                        .replace(day=1))
    call_command("seed_demo", database=_name(), ff_email=OWNER)
    said = capsys.readouterr().out
    assert f"removed {files_first} of {files_first} old files" in said

    assert list(Tenant.objects.values_list("slug", flat=True)) == ["summit-demo"], \
        "the reset emptied everything first, including what was there before"
    again = Tenant.objects.get()
    assert again.pk != tenant.pk
    with tenant_context(again.pk):
        assert Contact.objects.count() == counts_first[0], "the same practice, not two"
        assert Company.objects.filter(is_client_company=True).count() == 11
        assert ClientInvoice.objects.count() < counts_first[2]
        kept = GmailConnection.objects.get()
        assert kept.send_as_address == settings.DEMO_MAIL_FROM and kept.secret_id
        assert bytes(kept.secret.ciphertext) == b"sealed", \
            "the demo's own Gmail connection is carried across the reset"
