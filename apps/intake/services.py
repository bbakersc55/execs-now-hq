"""What can happen to an intake: start, answer, submit, review, send, and
afterwards. The views are thin; everything that changes state is here.
"""

from __future__ import annotations

import re

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.text import slugify

from apps.tenancy.context import tenant_context

from . import defaults, derive, links, plan, schema, tracklists, vault
from .models import (
    IntakeForm, OwnerDate, SendRun, Submission, SubmissionEvent, SubmissionFile,
)

S = Submission.Status


class Refused(ValueError):
    """Something this intake won't do, in words, with an HTTP status."""

    def __init__(self, text, status=400):
        super().__init__(text)
        self.status = status


def _event(submission, kind, actor=None, detail=""):
    SubmissionEvent.all_objects.create(tenant_id=submission.tenant_id, submission=submission,
                                       kind=kind, actor=actor, detail=detail[:300])


# ------------------------------------------------------------ the form

def unique_slug(name: str) -> str:
    base = slugify(name)[:50] or "intake"
    slug, n = base, 2
    while IntakeForm.all_objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def form_for(company, *, create=True):
    """The company's "New owner and property" form, made with its starting
    settings the first time (built from Track's lists, if they can be read)."""
    form = IntakeForm.all_objects.filter(company=company,
                                         kind=IntakeForm.Kind.NEW_OWNER).first()
    if form is None and create:
        lists, _ = tracklists.lists_for(company)
        form = IntakeForm.all_objects.create(
            tenant_id=company.tenant_id, company=company, brand_name=company.name[:120],
            slug=unique_slug(company.name), settings=defaults.build(lists))
    return form


def settings_of(form, lists) -> dict:
    """The form's settings, completed from Track's lists where never built."""
    current = dict(form.settings or {})
    if not current.get("sleeps") and lists.get("bed_types"):
        current = {**defaults.build(lists), **{k: v for k, v in current.items() if v}}
    return defaults.refreshed(current, lists) if lists.get("bed_types") else current


def custom_allowed(form) -> set:
    states = (form.settings or {}).get("custom_fields") or {}
    return {ref for ref, s in states.items()
            if (s or {}).get("state") == "owner" and ref not in schema.BUILTIN_FIELDS}


# ------------------------------------------------------------ starting one

def start(form, *, first_name, last_name="", email="", actor=None, answers=None,
          carried_from=None):
    first_name = (first_name or "").strip()[:80]
    email = (email or "").strip().lower()[:200]
    if not first_name:
        raise Refused("Enter the owner's first name.")
    if email and not schema.email_ok(email):
        raise Refused("That email doesn't look right.")
    from apps.crm.models import Company

    with transaction.atomic():
        # One number at a time per company: lock its row, then count.
        Company.all_objects.select_for_update().filter(pk=form.company_id).first()
        number = (Submission.all_objects.filter(company=form.company)
                  .aggregate(n=Max("number"))["n"] or 0) + 1
        base = answers or {"about": {"first_name": first_name, "last_name": last_name.strip(),
                                     "email": email}}
        submission = Submission(tenant_id=form.tenant_id, form=form, company=form.company,
                                number=number, invite_first_name=first_name,
                                invite_last_name=(last_name or "").strip()[:80],
                                invite_email=email, started_by=actor,
                                answers=schema.clean(base, custom_allowed=custom_allowed(form)),
                                carried_from=carried_from)
        links.issue(submission)
        submission.save()
    _event(submission, SubmissionEvent.Kind.STARTED, actor,
           "Started by a manager" if actor else "Started from another property's form")
    return submission


# ------------------------------------------------------------ answering

def save_section(submission, section, value, *, by_owner: bool):
    if submission.locked:
        raise Refused("This intake was sent to Track. Later changes are made in Track.", 409)
    if submission.status == S.DISCARDED:
        raise Refused("This intake was discarded.", 409)
    if by_owner and not submission.owner_may_edit:
        raise Refused("This form was already submitted. Thank you!", 409)
    if section not in schema.CLEANERS and section != "custom":
        raise Refused("Unknown section.")
    answers = schema.merge(submission.answers, section, value,
                           custom_allowed=custom_allowed(submission.form))
    now = timezone.now()
    submission.answers = answers
    submission.last_changed_at = now
    fields = ["answers", "last_changed_at"]
    if by_owner:
        submission.last_activity_at = now
        fields.append("last_activity_at")
        if submission.status == S.DRAFT:
            submission.status = S.IN_PROGRESS
            fields.append("status")
    submission.save(update_fields=fields)
    return submission


def touch(submission):
    """The owner opened the link: it stays good for 30 days from now."""
    submission.last_activity_at = timezone.now()
    submission.save(update_fields=["last_activity_at"])


def missing_for_submit(submission) -> list[str]:
    a = submission.answers or {}
    about, prop = a.get("about") or {}, a.get("property") or {}
    out = []
    if not about.get("first_name") or not about.get("last_name"):
        out.append("your first and last name")
    if not about.get("email") and not about.get("mobile"):
        out.append("an email or a mobile number")
    if not prop.get("street") or not prop.get("city"):
        out.append("the property's address")
    return out


def submit(submission):
    if not submission.owner_may_edit:
        raise Refused("This form was already submitted. Thank you!", 409)
    missing = missing_for_submit(submission)
    if missing:
        raise Refused("Before you submit, please add " + ", ".join(missing) + ".")
    submission.status, submission.submitted_at = S.SUBMITTED, timezone.now()
    submission.last_activity_at = submission.last_changed_at = timezone.now()
    submission.save(update_fields=["status", "submitted_at", "last_activity_at",
                                   "last_changed_at"])
    _event(submission, SubmissionEvent.Kind.SUBMITTED, None, "The owner submitted it")
    from . import notices

    with tenant_context(submission.tenant_id):
        notices.submitted(submission)
    return submission


def add_another(submission):
    """"Add another property": a new submission with the owner's details (and
    tax id) carried over. One property per submission."""
    if submission.status in (S.DRAFT, S.IN_PROGRESS):
        raise Refused("Submit this property first, then add another.", 409)
    carried = {"about": (submission.answers or {}).get("about") or {},
               "tax": (submission.answers or {}).get("tax") or {}}
    about = carried["about"]
    new = start(submission.form, first_name=about.get("first_name") or
                submission.invite_first_name, last_name=about.get("last_name", ""),
                email=about.get("email") or submission.invite_email, answers=carried,
                carried_from=submission)
    tax = vault.value(submission, "tax_id")
    if tax:
        vault.put(new, vault.Kind.TAX_ID, "", tax)
    return new


def discard(submission, actor):
    if submission.locked:
        raise Refused("A sent intake can't be discarded.", 409)
    submission.status, submission.discarded_at, submission.discarded_by = (
        S.DISCARDED, timezone.now(), actor)
    submission.save(update_fields=["status", "discarded_at", "discarded_by"])
    vault.delete_all(submission, "the intake was discarded")
    _event(submission, SubmissionEvent.Kind.DISCARDED, actor, "Discarded")


# ------------------------------------------------------------ review

def _norm_street(text) -> str:
    text = re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())
    words = {"street": "st", "drive": "dr", "road": "rd", "avenue": "ave", "lane": "ln",
             "court": "ct", "circle": "cir", "boulevard": "blvd", "way": "way"}
    return " ".join(words.get(w, w) for w in text.split())


def check_track(submission, client) -> dict:
    """The warnings that need Track: an owner or contact with the same email,
    a unit at the same street address. Reads only."""
    from apps.scorecard import track
    from .track_writer import rows_of

    a = submission.answers or {}
    out = {"owners": [], "contacts": {}, "units": [], "error": ""}
    try:
        emails = {p["email"].lower(): i for i, p in enumerate(plan.people(a)) if p["email"]}
        page = 1
        while page <= 20:
            data = client.get("/pms/owners", {"page": page, "size": 100})
            for row in rows_of(data):
                if (row.get("email") or "").lower() in emails:
                    out["owners"].append({"id": row.get("id"), "name": row.get("name", ""),
                                          "isActive": row.get("isActive")})
            if page >= int((data or {}).get("page_count") or 1):
                break
            page += 1
        for email, i in emails.items():
            found = [{"id": r.get("id"), "name": r.get("name") or
                      f"{r.get('firstName', '')} {r.get('lastName', '')}".strip()}
                     for r in rows_of(client.get("/crm/contacts", {"search": email, "size": 20}))
                     if (r.get("primaryEmail") or "").lower() == email]
            if found:
                out["contacts"][str(i)] = found
        street = _norm_street((a.get("property") or {}).get("street"))
        if street:
            for active in (1, 0):
                page = 1
                while page <= 20:
                    data = client.get("/pms/units", {"page": page, "size": 100,
                                                     "isActive": active})
                    for row in rows_of(data):
                        if _norm_street(row.get("streetAddress")) == street:
                            out["units"].append({"id": row.get("id"),
                                                 "name": row.get("name", ""),
                                                 "isActive": row.get("isActive")})
                    if page >= int((data or {}).get("page_count") or 1):
                        break
                    page += 1
    except track.TrackUnavailable as exc:
        out["error"] = str(exc)
    submission.track_check, submission.checked_at = out, timezone.now()
    submission.save(update_fields=["track_check", "checked_at"])
    return out


def staff_choices(submission, form_settings, lists) -> dict:
    return derive.staff_with_defaults(submission.staff, submission.answers or {},
                                      form_settings, lists)


def save_staff(submission, changes: dict, actor):
    if submission.locked:
        raise Refused("This intake was sent to Track. Later changes are made in Track.", 409)
    allowed = set(derive.staff_defaults({}, {}, {}).keys())
    current = dict(submission.staff or {})
    for key, value in (changes or {}).items():
        if key in allowed:
            current[key] = value
    submission.staff = current
    submission.last_changed_at = timezone.now()
    submission.save(update_fields=["staff", "last_changed_at"])
    return submission


def build_plan(submission, lists, form_settings, *, owner_active=None, unit_bookable=None):
    staff = staff_choices(submission, form_settings, lists)
    held = vault.masked(submission)
    return plan.build(answers=submission.answers or {}, staff=staff, settings=form_settings,
                      lists=lists, brand=submission.form.brand_name,
                      has_tax_id=bool(held["tax_id"]), owner_active=owner_active,
                      unit_bookable=unit_bookable)


# ------------------------------------------------------------ sending

def start_send(submission, actor):
    """Queue a send (or "Try the rest again"). The worker does the writing."""
    if submission.locked:
        raise Refused("This intake was already sent to Track.", 409)
    if submission.status not in (S.SUBMITTED, S.FAILED, S.IN_PROGRESS, S.DRAFT):
        raise Refused("This intake can't be sent from here.", 409)
    if SendRun.all_objects.filter(submission=submission,
                                  state__in=[SendRun.State.QUEUED,
                                             SendRun.State.RUNNING]).exists():
        raise Refused("A send is already running.", 409)
    lists, _ = tracklists.lists_for(submission.company)
    form_settings = settings_of(submission.form, lists)
    the_plan = build_plan(submission, lists, form_settings)
    if the_plan["problems"]:
        raise Refused("Not ready to send: " + " ".join(the_plan["problems"]))
    run = SendRun.all_objects.create(
        tenant_id=submission.tenant_id, submission=submission, started_by=actor,
        steps=[{"key": s["key"], "label": s["label"], "state": "waiting", "detail": ""}
               for s in the_plan["steps"]] + [
            {"key": "enhq:tasks", "label": "Create the onboarding tasks in ENHQ",
             "state": "waiting", "detail": ""},
            {"key": "enhq:dates", "label": "Hold the owner's dates in ENHQ", "state": "waiting",
             "detail": ""},
            {"key": "enhq:lock", "label": "Lock the intake and delete what Track now holds",
             "state": "waiting", "detail": ""}])
    submission.status, submission.sent_by = S.SENDING, actor
    submission.save(update_fields=["status", "sent_by"])
    _event(submission, SubmissionEvent.Kind.SEND_STARTED, actor, "Send to Track pressed")
    from django_q.tasks import async_task

    transaction.on_commit(lambda: async_task("apps.intake.tasks.run_send",
                                             str(submission.tenant_id), str(run.pk)))
    return run


def _step(run, key, state, detail=""):
    for step in run.steps:
        if step["key"] == key:
            step["state"], step["detail"] = state, detail[:300]
    run.save(update_fields=["steps"])


def run_send(run, *, client=None, today=None):
    """The worker's half of a send: Track first, then ENHQ's own steps."""
    from apps.scorecard import feeds, track

    from . import checklist, notices, ownerdates, track_writer

    submission = run.submission
    run.state = SendRun.State.RUNNING
    run.save(update_fields=["state"])
    lists, _ = tracklists.lists_for(submission.company)
    form_settings = settings_of(submission.form, lists)
    the_plan = build_plan(submission, lists, form_settings)
    state = dict(submission.track or {})
    state.setdefault("ids", {})
    staff = staff_choices(submission, form_settings, lists)
    if the_plan["mode"] == "existing" and staff.get("existing_owner_id"):
        state["ids"]["owner"] = staff["existing_owner_id"]
    for index, contact_id in (staff.get("reuse_contacts") or {}).items():
        if contact_id and the_plan["mode"] == "new":
            state["ids"].setdefault(f"contact:{index}", contact_id)

    def save(current, key, status, detail):
        submission.track = current
        submission.save(update_fields=["track"])
        _step(run, key, status, detail)

    def secret(name):
        return vault.value(submission, name) if name else None

    def confirm(name):
        vault.confirmed(submission, name)

    try:
        client = client or feeds.track_client(submission.company)
    except track.TrackUnavailable as exc:
        return _failed(run, submission, None, str(exc))
    ok, failed_key, message = track_writer.execute(
        the_plan, client, state, secret=secret, save=save, confirm=confirm,
        track_errors=(track.TrackUnavailable,))
    if not ok:
        return _failed(run, submission, failed_key, message)
    sent_on = today or timezone.localdate()
    with tenant_context(submission.tenant_id):
        sender = run.started_by
        if submission.project_id is None:
            tasks = checklist.create(submission, sender=sender, mode=the_plan["mode"],
                                     sent_on=sent_on)
            _step(run, "enhq:tasks", "done", f"{len(tasks)} tasks")
        else:
            _step(run, "enhq:tasks", "skipped", "Already made")
        if not submission.owner_dates.exists():
            held = ownerdates.hold(submission)
            _step(run, "enhq:dates", "done", f"{len(held)} date range(s) held")
        else:
            _step(run, "enhq:dates", "skipped", "Already held")
        vault.delete_all(submission, "sent to Track; Track holds what it needs")
        now = timezone.now()
        submission.status, submission.sent_at, submission.locked_at = S.SENT, now, now
        submission.save(update_fields=["status", "sent_at", "locked_at"])
        _step(run, "enhq:lock", "done", "")
        run.state, run.finished_at = SendRun.State.SUCCEEDED, now
        run.save(update_fields=["state", "finished_at"])
        _event(submission, SubmissionEvent.Kind.SENT, sender, "Sent to Track")
        notices.tell(submission, source_type="intake_sent", source_id=submission.pk,
                     title=f"Intake #{submission.number} sent to Track",
                     text="The owner, the unit and its details are in Track, and the "
                          "onboarding tasks are made.")
    return run


def _failed(run, submission, key, message):
    from . import notices

    run.state, run.error, run.finished_at = SendRun.State.FAILED, message[:2000], timezone.now()
    run.save(update_fields=["state", "error", "finished_at"])
    submission.status = S.FAILED
    submission.save(update_fields=["status"])
    _event(submission, SubmissionEvent.Kind.SEND_FAILED, run.started_by,
           f"Stopped at {key or 'the start'}: {message}"[:300])
    with tenant_context(submission.tenant_id):
        notices.tell(submission, source_type="intake_send_failed", source_id=run.pk,
                     users=[run.started_by] if run.started_by else None,
                     title=f"Intake #{submission.number}: send stopped",
                     text=f"{message} What was done is kept; press Try the rest again.")
    return run


# ------------------------------------------------------------ files

ACCEPTED = {"application/pdf": b"%PDF", "image/png": b"\x89PNG", "image/jpeg": b"\xff\xd8\xff"}
MOST_FILES, MOST_BYTES = 5, 15 * 1024 * 1024


def _kind_of(content: bytes) -> str | None:
    for kind, magic in ACCEPTED.items():
        if content.startswith(magic):
            return kind
    if content[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftyphevc", b"ftypmsf1"):
        return "image/heic"
    return None


def add_file(submission, upload, *, by_owner=True):
    from apps.tenancy import storage

    if submission.locked:
        raise Refused("This intake was sent to Track.", 409)
    if submission.files.count() >= MOST_FILES:
        raise Refused(f"You can upload up to {MOST_FILES} files.")
    content = upload.read(MOST_BYTES + 1)
    if len(content) > MOST_BYTES:
        raise Refused("That file is over 15 MB. Try a smaller copy or a photo of the page.")
    kind = _kind_of(content)
    if kind is None:
        raise Refused("Upload a PDF, JPG, PNG or HEIC file.")
    name = re.sub(r"[^\w.\- ]", "_", (upload.name or "document"))[:120] or "document"
    stored = storage.save(tenant=submission.tenant, content=content,
                          object_key=storage.object_key("intake", name), purpose="intake_file",
                          content_type=kind)
    row = SubmissionFile.all_objects.create(
        tenant_id=submission.tenant_id, submission=submission, stored_file=stored, name=name,
        content_type=kind, byte_size=len(content), uploaded_by_owner=by_owner)
    submission.last_changed_at = timezone.now()
    submission.save(update_fields=["last_changed_at"])
    return row


def remove_file(submission, file_id):
    from apps.tenancy import storage

    if submission.locked:
        raise Refused("This intake was sent to Track.", 409)
    row = submission.files.filter(pk=file_id).first()
    if row is None:
        raise Refused("No such file.", 404)
    stored = row.stored_file
    row.delete()
    try:
        storage.delete(stored)
    except storage.StorageError:
        pass


def owner_dates_cancel(submission, date_id, actor):
    from . import ownerdates

    row = submission.owner_dates.filter(pk=date_id).first()
    if row is None or not ownerdates.cancel(row, actor):
        raise Refused("Only held dates can be cancelled.", 409)


def hourly(tenant_id):
    """The hourly owner-dates check for one practice."""
    from apps.scorecard import feeds, track

    from . import ownerdates

    for submission in ownerdates.waiting_submissions(tenant_id):
        with tenant_context(tenant_id):
            ownerdates.remind(submission)
            try:
                client = feeds.track_client(submission.company)
            except track.TrackUnavailable:
                continue
            lists, _ = tracklists.lists_for(submission.company)
            ownerdates.place(submission, client, lists)


def daily(tenant_id):
    vault.purge_stale(tenant_id)


def owner_date_rows(submission) -> list:
    return [{"id": str(r.pk), "start": r.start.isoformat(), "end": r.end.isoformat(),
             "state": r.state, "state_label": OwnerDate.State(r.state).label,
             "message": r.message} for r in submission.owner_dates.all()]


def owner_differences(submission, client, owner_id) -> list[dict]:
    """Change 4 (owner, 2026-11-19): an existing owner is never written to.
    What the intake says that Track's owner record doesn't, for the reviewer."""
    from apps.scorecard import track

    try:
        owner = client.get(f"/pms/owners/{int(owner_id)}") or {}
    except (track.TrackUnavailable, TypeError, ValueError):
        return []
    about = (submission.answers or {}).get("about") or {}
    pairs = [("Name", plan.account_name(submission.answers or {}), owner.get("name")),
             ("Email", about.get("email"), owner.get("email")),
             ("Phone", plan.e164(about.get("mobile", "")), owner.get("phone")),
             ("Street", about.get("street"), owner.get("streetAddress")),
             ("City", about.get("city"), owner.get("locality")),
             ("State", about.get("state"), owner.get("region")),
             ("ZIP", about.get("postal"), owner.get("postal"))]
    return [{"field": label, "intake": mine or "", "track": theirs or ""}
            for label, mine, theirs in pairs
            if (mine or "") and str(mine or "").strip().lower() != str(theirs or "").strip().lower()]
