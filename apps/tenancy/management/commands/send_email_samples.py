"""Send one sample of every email producer to an allow-listed address.

For visual sign-off on a real mail client (Gmail on desktop and phone). Built
from each producer's own rendering functions, so a sample looks exactly like the
real thing, but from SAMPLE content: it never runs digest generation, never
claims an update, and never writes a digest, a stakeholder row or a
client-activity marker — real engagements are untouched.

Refuses off a localhost build, and refuses any address that is not an exact
match in the dev allow-list (FR-0.7). Every sample goes through the Outbox like
any other send, so each one is logged there with `source_type = email_sample`.

The four personal samples (touch, onboarding, manual, stage rule) are sent from
the FF's own verified address — the "my own address" choice — so the sign-off
check sees the From a partner sees. If that address is not verified they fall
back to the alias, and the output line says which address each one used.

    manage.py send_email_samples --to you@example.com [--dry-run]
    manage.py send_email_samples --to you@example.com --only manual
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

SAMPLE_PREFIX = "[Sample] "


def _root():
    root = settings.APP_ROOT_URL
    if not root.startswith("http"):
        root = settings.PUBLIC_BASE_URL.rstrip("/") + "/" + root.lstrip("/")
    return root.rstrip("/")


def _digest_sample(tenant, actor):
    from apps.crm.models import Contact, Task
    from apps.work import digests
    from apps.work.models import Cadence, Digest, Project, TaskUpdate

    K = TaskUpdate.Kind
    project = Project(title="Order-to-cash")
    invoices = Task(title="Map the invoice process", project=project)
    matching = Task(title="Automate invoice matching", project=project)
    access = Task(title="AP system access", project=project)
    owed = [
        (TaskUpdate(kind=K.STATUS_CHANGED, task=invoices, from_value="in_progress",
                    to_value="done",
                    client_facing_line="Invoices now clear in four days instead of eleven."),
         None),
        (TaskUpdate(kind=K.STATUS_CHANGED, task=matching, from_value="not_started",
                    to_value="in_progress"), None),
        (TaskUpdate(kind=K.CHECKLIST_COMPLETED, task=matching,
                    to_value="Export last quarter's remittances"), None),
        (TaskUpdate(kind=K.STATUS_CHANGED, task=access, from_value="in_progress",
                    to_value="waiting_on_client",
                    client_facing_line="We need an AP login to finish the matching rules."),
         None),
        (TaskUpdate(kind=K.STATUS_CHANGED, task=Task(title="Vendor master clean-up"),
                    from_value="in_progress", to_value="blocked",
                    client_facing_line="Blocked until the duplicate vendor list is approved."),
         None),
    ]
    now = timezone.now()
    digest = Digest(tenant=tenant, contact=Contact(tenant=tenant, first_name="Dana",
                                                  last_name="Reyes"),
                    cadence=Cadence.WEEKLY, period_start=now - timedelta(days=7),
                    period_end=now, send_window_at=now)
    narrative = ("This week the invoice process was mapped end to end, and invoices now "
                 "clear in four days instead of eleven. Matching automation has started; "
                 "it needs one thing from your side to finish.")
    digest.body_text, digest.body_html = digests.render(digest, owed, narrative=narrative)
    html, text = digests.email_for(digest, footer_url=f"{_root()}/updates/sample-link")
    return digests._subject(digest), html, text


def _client_activity_sample(tenant, actor):
    from apps.accounts.models import User
    from apps.crm.models import Task
    from apps.work.models import TaskUpdate
    from apps.work.tasks import client_activity_email

    now = timezone.now()
    priya = User(full_name="Priya Shah", email="priya@example.invalid")
    dana = User(full_name="Dana Reyes", email="dana@example.invalid")
    rows = [
        TaskUpdate(kind="comment_added", actor=priya, task=Task(title="AP system access"),
                   created_at=now - timedelta(minutes=48)),
        TaskUpdate(kind="created", actor=dana, task=Task(title="Share the vendor list"),
                   created_at=now - timedelta(minutes=41)),
        TaskUpdate(kind="status_changed", actor=dana, task=Task(title="Approve duplicates"),
                   created_at=now - timedelta(minutes=35)),
    ]
    return client_activity_email(tenant, rows)


def _referral_touch_sample(tenant, actor):
    from apps.crm.models import Contact
    from apps.crm.services.referral import compose_touch

    body, _ai, _warning = compose_touch(
        Contact(tenant=tenant, first_name="Maria", last_name="Lopez"), actor=actor)
    return f"Checking in from {tenant.name}", "", body


def _referral_onboarding_sample(tenant, actor):
    from apps.crm.models import Contact
    from apps.crm.services.referral import compose_onboarding

    body = compose_onboarding(Contact(tenant=tenant, first_name="Maria", last_name="Lopez"),
                              actor=actor, with_attachment=False)
    return "Good to meet you", "", body


def _manual_sample(tenant, actor):
    from apps.crm.services import sender as sender_service

    signature, _ = sender_service.signature(tenant, actor)
    body = ("Hi Maria,\n\nThanks for the time on Tuesday. As promised, here's the short "
            f"version of what we covered, and the link to book a follow-up: {_root()}\n\n"
            f"{signature}")
    return "Following up on Tuesday", "", body


def _stage_rule_sample(tenant, actor):
    from apps.crm.services import sender as sender_service

    signature, _ = sender_service.signature(tenant, actor)
    body = ("Hi Maria,\n\nI wanted to follow up on our conversation. If a short call "
            "next week would help, just reply with a time that suits you.\n\n"
            f"{signature}")
    return "Following up", "", body


def _magic_link_sample(tenant, actor):
    from apps.accounts.views import magic_link_email, magic_link_subject

    html, text = magic_link_email(
        tenant, url=f"{settings.PUBLIC_BASE_URL.rstrip('/')}/auth/magic/sample-not-a-real-link")
    return magic_link_subject(tenant), html, text


def _pin_reset_sample(tenant, actor):
    from apps.notes.pins import pin_reset_email

    html, text = pin_reset_email(tenant, title="Board prep — Q4",
                                 url=f"{_root()}/notes/pin-reset/sample-not-a-real-link")
    return "Clear a note's PIN", html, text


SAMPLES = [
    ("digest", _digest_sample),
    ("client_activity", _client_activity_sample),
    ("referral_touch", _referral_touch_sample),
    ("referral_onboarding", _referral_onboarding_sample),
    ("manual", _manual_sample),
    ("stage_rule", _stage_rule_sample),
    ("magic_link", _magic_link_sample),
    ("note_pin_reset", _pin_reset_sample),
]


class Command(BaseCommand):
    help = "Send one sample of every email producer to an allow-listed address."

    def add_arguments(self, parser):
        parser.add_argument("--to", required=True, help="An exact dev allow-list address.")
        parser.add_argument("--tenant", help="Tenant slug; defaults to the only tenant.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Render every sample and send nothing.")
        parser.add_argument("--only", metavar="PRODUCER",
                            help="Send just this one producer's sample, e.g. --only manual.")

    def handle(self, *args, **options):
        from apps.accounts.mailer import dev_allowlist
        from apps.crm.services import email_layout, outbox
        from apps.crm.services import sender as sender_service
        from apps.crm.services.transport import TransportUnavailable
        from apps.tenancy.context import tenant_context
        from apps.tenancy.models import Membership, Role, Tenant

        if not settings.IS_LOCAL:
            raise CommandError("Samples are sent from a localhost build only.")
        tenants = Tenant.objects.all()
        tenant = (tenants.filter(slug=options["tenant"]).first() if options["tenant"]
                  else (tenants.first() if tenants.count() == 1 else None))
        if tenant is None:
            raise CommandError("Name the tenant with --tenant.")
        address = (options["to"] or "").strip().lower()
        if address not in dev_allowlist(tenant):
            raise CommandError(
                f"{address} is not in the dev allow-list, so it would not receive real mail. "
                "Samples go only to an exact allow-listed address (FR-0.7).")

        samples = SAMPLES
        if options["only"]:
            samples = [row for row in SAMPLES if row[0] == options["only"]]
            if not samples:
                raise CommandError(
                    f"{options['only']!r} is not a sample. One of: "
                    f"{', '.join(producer for producer, _ in SAMPLES)}.")

        with tenant_context(tenant.pk):
            owner = (Membership.objects.filter(role=Role.FF, revoked_at__isnull=True)
                     .select_related("user").first())
            actor = owner.user if owner else None
            sent = []
            for producer, build in samples:
                subject, html, text = build(tenant, actor)
                subject = SAMPLE_PREFIX + subject
                personal = producer in email_layout.PERSONAL_PRODUCERS
                from_address = (sender_service.resolve_from(tenant, actor, producer,
                                                            override="self")
                                if personal and actor is not None else None)
                if options["dry_run"]:
                    self.stdout.write(f"would send  {producer:20} {subject}  "
                                      f"from {from_address or tenant.from_address}  "
                                      f"(html {len(html)} chars, text {len(text)} chars)")
                    continue
                try:
                    with transaction.atomic():
                        message = outbox.create_message(
                            tenant=tenant, producer=producer, to_address=address,
                            subject=subject, body_text=text, body_html=html, actor=actor,
                            force_direct=True, source_type="email_sample",
                            from_address=from_address,
                        )
                except TransportUnavailable as exc:
                    self.stdout.write(self.style.ERROR(f"FAILED      {producer:20} {exc}"))
                    continue
                sent.append(message)
                self.stdout.write(f"sent        {producer:20} {subject}  "
                                  f"via {message.sent_via}  from {message.from_address}  "
                                  f"outbox {message.pk}")
        if not options["dry_run"]:
            self.stdout.write(f"{len(sent)} of {len(samples)} samples sent to {address}.")
