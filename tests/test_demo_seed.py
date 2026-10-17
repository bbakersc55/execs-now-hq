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


def world_of(today):
    """Enough of the seed's world for `household.in_window`."""
    from types import SimpleNamespace

    return SimpleNamespace(today=today)


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
    from apps.tenancy.models import (
        AuditEvent, ClientAssignment, Membership, StoredFile, Tenant,
    )
    from apps.work import milestones
    from apps.work.models import (
        Comment, Digest, Goal, GoalMeasurement, GoalMilestone, GoalOrderProposal,
        GoalProposal, GoalResolution, Stakeholder,
    )

    settings.APP_ENVIRONMENT, settings.IS_DEMO, settings.IS_LOCAL = "demo", True, False
    settings.DEMO_MAIL_REDIRECT = "redirect@demo-inbox.invalid"
    monkeypatch.setattr(transport.GmailTransport, "send",
                        lambda *a, **k: pytest.fail("the seed reached Gmail"))

    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType
    from django.contrib.sites.models import Site
    from django.test import Client

    # As an earlier reset left the demo on 2026-10-08: no site row at all.
    Site.objects.all().delete()
    Site.objects.clear_cache()
    types_before, permissions_before = ContentType.objects.count(), Permission.objects.count()
    assert types_before and permissions_before

    call_command("seed_demo", database=_name(), ff_email=OWNER)
    said = capsys.readouterr().out
    assert "Summit Operations Partners" in said and '"client companies": 11' in said

    def sign_in_still_works():
        """The reset leaves Django's own tables alone, and Google sign-in,
        which looks up the site, answers."""
        assert Site.objects.filter(pk=settings.SITE_ID).exists()
        assert ContentType.objects.count() == types_before
        assert Permission.objects.count() == permissions_before
        assert Client().get("/accounts/google/login/").status_code < 500
        assert Client().get("/accounts/google/start", {"email": OWNER}).status_code < 500

    sign_in_still_works()

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
        assert by_state == {"draft": 1, "in_call": 1, "complete": 2, "converted": 1}
        assert StrategySessionPrep.objects.get().state == "ready"
        live = StrategySession.objects.get(state="in_call")
        assert StrategyMapRow.objects.filter(session=live, state="proposed").count() >= 2
        done = StrategySession.objects.get(state="complete", company__name__startswith="Sheinhardt")
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
        # Wayne Industries' session carries the approved mock's words, so the
        # demo's PDF is the mock (2026-10-15): two pages, nothing past a foot.
        from apps.strategy import pdf as strategy_pdf
        from apps.tenancy.demo.sessions import WAYNE_WORDS

        wayne = StrategySession.objects.get(company__name="Wayne Industries")
        assert wayne.state == "complete" and not wayne.pdf_file_id
        doc = strategy_pdf.context_for(wayne)["doc"]
        assert doc["headline"] == WAYNE_WORDS["headline"]
        assert [t["number"] for t in doc["tiles"]] == ["4", "6", "2"]
        assert doc["tiles"][1]["label"] == "components assessed, two to fix"
        assert [c["pill"] for c in doc["components"]] == [
            "watch", "fix", "fix", "strong", "strong", "watch"]
        assert [len(box["bullets"]) for box in doc["boxes"]] == [3, 3, 3]
        assert [p["recommended"] for p in doc["paths"]] == [True, False]
        assert len(doc["next_moves"]) == 4
        assert strategy_pdf.page_count(wayne) == 2
        assert strategy_pdf.overflowing_pages(wayne) == []
        signoff = strategy_pdf.context_for(wayne)["signoff"]
        assert signoff == ("John Carter, Summit Operations Partners · "
                           "john.carter@summitops.example · summitops.example")

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
        # Two clients a month behind, and (P6 M2) one old enough not to be counted.
        # Their invoices go out on the 1st at net 15, so from the 17th this
        # month's are past due as well as last month's.
        behind = 2 * (2 if today.day > 16 else 1) + 1
        assert invoices.filter(status="sent", due_date__lt=today).count() == behind
        assert invoices.filter(kind="contact", client_company__isnull=True).count() == 2
        assert invoices.order_by("issue_date").first().issue_date == date(2025, 1, 1)
        assert all(i.pdf_id for i in invoices.exclude(status="draft"))
        assert set(FinanceAccount.objects.values_list("kind", flat=True)) == {"bank", "card"}
        assert all(a.opening_balance_cents for a in FinanceAccount.objects.exclude(side="mixed"))
        income = expenses = 0
        for year in (2025, today.year):
            report = reports.pnl(tenant, year=year)
            income += report["income"]["total"]
            expenses += report["expenses"]["total"]
            # Only this month's Mixed card lines still waiting for a side (P6 M4).
            assert report["uncategorized"]["count"] == FinanceEntry.objects.filter(
                side="to_sort", removed_at__isnull=True, on_date__year=year).count()
        assert 0.55 <= (income - expenses) / income <= 0.60, "margin after contractors"
        entries = FinanceEntry.objects.filter(removed_at__isnull=True)
        assert entries.filter(kind="owner").count() >= 20
        assert entries.filter(kind="transfer").count() >= 20
        assert entries.filter(kind="income", direction="out").count() == 1    # a refund
        # Another, entered late, and the correcting entry in the open month.
        assert entries.filter(kind="expense", direction="in").count() == 2
        batch = FinanceImportBatch.objects.get(source="csv", account__side="business")
        assert batch.status == "committed"
        # One PDF statement, imported, so the PDF import and the statement on
        # Reconcile can be shown (owner, 2026-10-14). Written without Claude.
        from apps.finance import reconcile as reconciling, statement_pdf
        from apps.finance.models import FinanceReconciliation
        from apps.tenancy import storage

        last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        pdf = FinanceImportBatch.objects.get(source="pdf")
        assert (pdf.status, pdf.period_start, pdf.ai_call_id) == (
            "committed", last_month, None)
        assert pdf.filename == f"FrontRange_statement_{last_month:%Y_%m}.pdf"
        rec = FinanceReconciliation.objects.get(account=pdf.account, month=last_month)
        assert (pdf.period_end, pdf.last_balance_cents) == (
            rec.statement_on, rec.statement_balance_cents)
        # It is a real PDF with text in it, it adds up, and it is the
        # statement the Reconcile screen shows for that month.
        content = storage.read(pdf.statement_file)
        assert statement_pdf.inspect(content)["pages"] >= 1
        assert statement_pdf.adds_up(pdf)["difference_cents"] == 0
        lines = FinanceImportRow.objects.filter(batch=pdf)
        assert lines.count() >= 10
        assert set(lines.values_list("outcome", flat=True)) == {"duplicate"}
        [shown] = reconciling.statements(pdf.tenant)[(pdf.account_id, last_month)]
        assert shown["filename"] == pdf.filename
        assert reconciling.represent(rec, detail=True)["statements"] == [shown]
        # The newest figure the bank gave is still this month's file's.
        from apps.finance import importer
        assert importer.bank_said(pdf.tenant)[pdf.account_id]["on"] >= today.replace(day=1)
        from apps.tenancy.demo import household

        assert 1 <= FinanceRule.objects.exclude(
            contains__in=[rule[0] for rule in household.RULES]).count() <= 6
        assert FinanceImportRow.objects.filter(batch=batch,
                                               outcome="invoice_payment").count() >= 1
        # P6 M1 §10: every month before this one reconciled, bank and card,
        # and closed in order by the reconcile code; nobody typed the lock.
        from apps.finance import reconcile
        from apps.finance.models import (
            FinanceCategory, FinanceCategoryChange, FinanceMonthClose,
            FinanceReconciliation,
        )
        from apps.tenancy.demo.clock import months as months_from

        this_month = today.replace(day=1)
        whole = [m for m in months_from(date(2025, 1, 1), today) if m < this_month]
        assert len(whole) >= 21
        standing = FinanceMonthClose.objects.filter(reopened_at__isnull=True)
        assert [row.month for row in standing.order_by("month")] == whole
        assert all(row.closed_by == owner and row.closed_at.date() > row.month
                   for row in standing)
        assert FinanceSettings.objects.get().locked_through == \
            this_month - timedelta(days=1)
        assert not AuditEvent.objects.filter(verb="finance.settings_changed").exists()
        finished = FinanceReconciliation.objects.filter(state="finished")
        mixed_months = [m for m in whole if household.in_window(world_of(today), m)]
        assert len(mixed_months) == household.MONTHS
        assert finished.count() == 2 * len(whole) + len(mixed_months)
        for name, months_ in (("Front Range Bank checking", whole), ("Business Visa", whole),
                              (household.CARD, mixed_months)):
            mine = finished.filter(account__name=name).order_by("month")
            assert [rec.month for rec in mine] == months_, name
            assert all(reconcile.totals(rec)["difference_cents"] == 0 for rec in mine)
        assert all(rec.statement_on.day == 25
                   for rec in finished.filter(account__name="Business Visa"))
        # A few entries carry forward: the Chamber's check clears the month after.
        check = entries.filter(description__startswith="Quarterly sponsorship",
                               on_date__lt=this_month - timedelta(days=40)).first()
        cleared_in = check.cleared.get().reconciliation
        assert cleared_in.month == reconcile.next_month(check.on_date.replace(day=1))
        # One month closed, reopened and closed again, with its reason.
        reopened = FinanceMonthClose.objects.get(reopened_at__isnull=False)
        assert "Adobe" in reopened.reopen_reason and reopened.month in whole
        assert FinanceMonthClose.objects.filter(month=reopened.month).count() == 2
        assert entries.filter(description__startswith="Refund: second Acrobat",
                              on_date__year=reopened.month.year,
                              on_date__month=reopened.month.month).count() == 1
        # One correcting entry in the open month for a mistake found in a closed one.
        fix = entries.get(description__startswith="Correcting entry")
        assert fix.on_date >= this_month and fix.direction == "in"
        # This month: the bank in progress, its difference one unticked deposit;
        # the card not started.
        going = FinanceReconciliation.objects.get(state="open")
        assert (going.account.kind, going.month) == ("bank", this_month)
        shown = reconcile.represent(going, detail=True)
        left = [row for row in shown["lines"] if not row["cleared"] and not row["carried"]]
        if any(row["kind"] == "income" for row in shown["lines"]):
            assert [row["way"] for row in left] == ["in"]
            assert shown["difference_cents"] == left[0]["amount_cents"]
            assert shown["hints"][0] == {"kind": "untick", "entry": left[0]["id"],
                                         "text": shown["hints"][0]["text"]}
        # Invoice income is broken down by the kind of invoice: the retainers
        # under Retainers, the workshop where its invoice said, none on the parent.
        paid = entries.filter(source="invoice", kind="income")
        by_category = dict(paid.values_list("category__name").annotate(n=Count("pk")))
        assert set(by_category) == {"Retainers", "Workshops and speaking"}, by_category
        assert by_category["Workshops and speaking"] == 1
        assert not paid.filter(category__parent__isnull=True).exists()
        fees = next(row for row in reports.pnl(tenant, year=today.year)["income"]["rows"]
                    if row["name"] == "Client fees")
        assert {c["name"]: c["total"] > 0 for c in fees["children"]}["Retainers"] is True
        assert not any(c.get("direct") for c in fees["children"])
        # P6 M4 decision 27 and the brief: John Carter's personal side.
        from apps.personal import models as personal_models
        from apps.personal import reconcile as personal_reconcile
        from apps.tenancy import modules

        assert modules.has(tenant, modules.PERSONAL)
        mine = {m.__name__: m.of(owner) for m in personal_models.OWNED}
        assert sorted(mine["PersonalMember"].values_list("relation", flat=True)) == \
            ["self", "spouse"]
        assert sorted(mine["PersonalAccount"].values_list("name", flat=True)) == \
            ["Joint checking", "Joint savings"]
        card = FinanceAccount.objects.get(side="mixed")
        assert (card.name, card.kind) == (household.CARD, "card")
        lines = mine["PersonalLine"].filter(removed_at__isnull=True)
        first_month = min(mixed_months)
        assert lines.order_by("on_date").first().on_date < first_month + timedelta(days=10)
        assert lines.count() > 200
        # The card was split: personal lines are owner draws, the home
        # internet both; and a business line from joint checking is paid
        # personally, in the P&L and in no account of the practice's.
        assert entries.filter(side="personal", account=card).count() > 50
        internet = entries.filter(description="XFINITY INTERNET", account=card)
        assert {e.kind for e in internet} == {"expense", "owner"}
        canva = entries.filter(description="CANVA PRO")
        assert canva.count() == household.MONTHS
        assert all(e.side == "paid_personally" and e.account_id is None for e in canva)
        # Spouse pay and pay from the practice come in; the mortgage and car
        # go out; card payments and savings moves are paired transfers.
        by_category = dict(lines.values_list("category__name").annotate(n=Count("pk")))
        assert by_category["Spouse pay"] == 2 * household.MONTHS
        assert by_category["Pay from the practice"] >= household.MONTHS
        assert by_category["Rent or mortgage"] == household.MONTHS
        paired = lines.filter(transfer_pair__isnull=False)
        assert paired.count() >= 2 * (2 * household.MONTHS + household.MONTHS - 1)
        assert all(line.category.type == "transfer" for line in paired)
        # Waiting: last month's three checking lines, and this month's card
        # lines no rule knows.
        waiting = lines.filter(category__isnull=True)
        assert waiting.count() >= 2 and {
            line.description.split()[0] for line in waiting} <= {"COSTCO", "BELL", "CANYON"}
        assert all(line.on_date >= last_month for line in waiting)
        # Monthly statements came in through the personal import.
        assert mine["PersonalImport"].filter(status="committed").count() == \
            2 * household.MONTHS
        # Data only for now: a mortgage and a car loan, retirement and
        # investment balances month by month, three goals, the set-aside.
        assert sorted(mine["PersonalDebt"].values_list("kind", flat=True)) == \
            ["auto", "mortgage"]
        assert set(mine["PersonalHolding"].values_list("kind", flat=True)) == \
            {"retirement", "investment"}
        assert mine["PersonalBalance"].count() == 6 * household.MONTHS
        assert mine["PersonalGoal"].count() == 3
        set_aside = mine["PersonalSetAside"].get()
        assert set_aside.year == today.year and set_aside.saved_cents > 0
        # Stop 2: the budget, proposed from the six months and used; three
        # goals live, the home policy spread, two envelopes over this month.
        from apps.personal import budget as personal_budget

        view = personal_budget.month_view(owner.personal_ledger)
        named = {row["name"]: row for row in view["envelopes"]}
        assert {"Groceries", "Dining", "Rent or mortgage"} <= set(named)
        assert named["Groceries"]["source"] == "history"
        assert {"Emergency fund", "Car repairs", "Christmas"} <= set(named)
        assert all(named[g]["rolls"] for g in ("Emergency fund", "Car repairs", "Christmas"))
        assert named["Home insurance"]["yearly_cents"] == 138_000
        assert sorted(row["name"] for row in view["envelopes"] if row["over"]) == \
            ["Dining", "Groceries"]
        assert view["income"] and view["income_planned_cents"] > 0
        assert mine["PersonalQuestion"].filter(state="open").exists()
        assert mine["PersonalPlanned"].filter(goal__isnull=False).count() == 2
        # Last month's savings statement reconciled; nothing to close.
        [rec] = mine["PersonalReconciliation"]
        assert rec.state == "finished" and personal_reconcile.totals(rec)[
            "difference_cents"] == 0
        # P6 M2 §10: the cash forecast, switched on, with what the owner said.
        from apps.finance import forecast
        from apps.finance.models import (
            FinanceForecastAdjustment, FinanceForecastPlanned, FinanceForecastSnapshot,
        )
        from apps.tenancy import modules as practice_modules

        assert practice_modules.enabled(tenant) == ["bookkeeping", "forecast", "personal"]
        ahead = forecast.build(tenant, today, snapshot=False)
        assert ahead["ready"] and ahead["closed_months"] == len(whole)
        view = ahead["views"]["90"]
        # A floor a little under where the books alone would go; what he has
        # planned takes the forecast under it, so the mark has something to show.
        assert ahead["floor_cents"] and ahead["floor_cents"] % 100_000 == 0
        assert view["first_below_floor"] is not None and view["first_below_zero"] is None
        assert 0 < ahead["floor_cents"] - view["low_cents"] < 1_500_000
        kinds = {row["kind"] for row in ahead["lines"]}
        assert kinds == {"known", "regular", "card", "planned"}
        cadences = {row["cadence"] for row in ahead["lines"] if row["kind"] == "regular"}
        assert cadences == {"monthly", "quarterly"}, "estimated tax and the Chamber"
        assert {row["label"] for row in ahead["lines"]
                if row["label"].startswith("Estimated tax")} == {
            "Estimated tax, federal", "Estimated tax, state"}
        planned = {row["description"]: row for row in ahead["planned"]}
        assert sorted(row["state"] for row in planned.values()) == [
            "planned", "planned", "what_if"]
        assert planned["Operations analyst, part time"]["repeat"] == "monthly"
        assert "Globex does not renew: its retainer stops" in planned
        assert FinanceForecastPlanned.objects.count() == 3
        assert sorted(FinanceForecastAdjustment.objects.values_list("kind", flat=True)) == [
            "amount", "not_regular"]
        rent = [row for row in ahead["lines"] if row["label"] == "Larimer Square Cowork"]
        assert {row["amount_cents"] for row in rent} == {69_500, 74_500}
        assert any(row["adjusted"].startswith("You set it to $745.00") for row in rent)
        # One invoice old enough not to be counted; the two a month behind are
        # forecast late, by those clients' own habit or on their due date.
        [left] = ahead["left_out"]
        assert left["why"] == "more than 60 days overdue" and left["days_overdue"] > 60
        # Six months of "how good it has been", each with what happened beside it.
        assert len(ahead["history"]) == 6
        assert [row["month"] for row in ahead["history"]] == [
            month.isoformat()[:7] for month in whole[-1:-7:-1]]
        assert all(row["taken_on"].endswith("-01") for row in ahead["history"])
        assert all(row["actual"]["out_cents"] > 0 and row["forecast"]["out_cents"] > 0
                   for row in ahead["history"])
        assert any(row["largest"] for row in ahead["history"])
        assert FinanceForecastSnapshot.objects.filter(actual__isnull=True).count() == 1, \
            "this month's is kept and still open"
        # The what-if is drawn and not counted until it is tried.
        globex = [row for row in ahead["lines"] if row["label"].startswith("Globex does")]
        assert globex and all(not row["counted"] for row in globex)
        tried = forecast.build(tenant, today, snapshot=False, what_if={
            "on": [planned["Globex does not renew: its retainer stops"]["id"]]})
        assert tried["what_if"]["views"]["months"]["low_cents"] < \
            ahead["views"]["months"]["low_cents"]
        assert tried["weeks"] == ahead["weeks"], "a look changes nothing as it stands"
        # The CPA's chart (§5.4): every expense is under a line of the worksheet.
        from apps.finance import chart as the_chart
        from apps.finance.models import FinanceYearFacts

        lines = {name for name, _subs in the_chart.STARTING_CHART[1][1]}
        used = set(entries.filter(kind="expense", category__isnull=False).values_list(
            "category__parent__name", "category__name"))
        assert all((parent or name) in lines for parent, name in used), used
        assert len({parent or name for parent, name in used}) >= 12
        # Estimated tax: owner draws, marked federal or state, each quarter.
        taxes = entries.exclude(estimated_tax="")
        assert set(taxes.values_list("kind", "direction", "category__name")) == {
            ("owner", "out", "Owner draw")}
        assert not FinanceCategory.objects.filter(
            name__iexact="Estimated tax payments").exists()
        assert set(taxes.values_list("estimated_tax", flat=True)) == {"federal", "state"}
        assert taxes.count() >= 12 and taxes.count() % 2 == 0
        assert {t.on_date.month for t in taxes} <= {1, 4, 6, 9}
        import csv
        import io

        sheet = list(csv.reader(io.StringIO(reports.export_worksheet(tenant, year=2025))))
        assert sheet[0] == ["Business income and expense worksheet, 2025, cash basis"]
        assert ["Estimated tax payments", "Federal", "State"] in sheet
        assert ["Total miles driven", "14820", ""] in sheet
        assert ["Office square footage", "180", ""] in sheet
        assert FinanceYearFacts.objects.count() == 2
        # The chart with sub-categories, and one combine and one split on record.
        assert FinanceCategory.objects.filter(parent__isnull=False).count() >= 30
        assert sorted(FinanceCategoryChange.objects.values_list("kind", flat=True)) == \
            ["merge", "split"]
        assert all(change.entries_moved > 0 for change in FinanceCategoryChange.objects.all())
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
        TenantSecret.all_objects.create(
            tenant=tenant, kind=SecretKind.ANTHROPIC_API_KEY, user=None,
            ciphertext=b"sealed-key", last4="9zzz", verified_at=timezone.now(),
            verified_by=owner)
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

    sign_in_still_works()
    assert list(Tenant.objects.values_list("slug", flat=True)) == ["summit-demo"], \
        "the reset emptied everything first, including what was there before"
    again = Tenant.objects.get()
    assert again.pk != tenant.pk
    with tenant_context(again.pk):
        assert Contact.objects.count() == counts_first[0], "the same practice, not two"
        assert Company.objects.filter(is_client_company=True).count() == 11
        assert ClientInvoice.objects.count() < counts_first[2]
        # The demo's own Anthropic key is carried across too, sealed as it was,
        # and the practice still allows no automatic spend on it.
        from apps.tenancy import ai_guard, claude
        from apps.tenancy.models import SecretKind, TenantSecret

        key = TenantSecret.objects.get(kind=SecretKind.ANTHROPIC_API_KEY)
        assert bytes(key.ciphertext) == b"sealed-key" and key.last4 == "9zzz"
        assert key.user_id is None and key.verified_at is not None
        assert key.verified_by.email == OWNER
        assert claude._tenant_secret(again) == key
        assert again.ai_unattended_daily_cap_usd == 0
        assert ai_guard.cap_reached(again), "every unattended call is skipped"
        assert ai_guard.refusal(again, purpose="digest_narrative", target_type="",
                                target_id=None, input_hash="x") == ai_guard.DAILY_CAP
        assert '"AI key kept": true' in said
        kept = GmailConnection.objects.get()
        assert kept.send_as_address == settings.DEMO_MAIL_FROM and kept.secret_id
        assert bytes(kept.secret.ciphertext) == b"sealed", \
            "the demo's own Gmail connection is carried across the reset"
