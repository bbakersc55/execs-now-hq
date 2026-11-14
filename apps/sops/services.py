"""The SOP record, its versions and its readers (P10, docs/p10_sop_studio.md).

- **A new SOP** starts from the Operations Command Center's SOP template: its
  sections' guidance becomes the hints on the fields they match (purpose,
  roles, steps, measures, review date), and any other section of the
  practice's copy of the template becomes a section of the SOP.
- **Publishing** freezes the working copy as the next numbered version with a
  change note. Version 1 always asks the audience to read it; a later version
  marked *minor* doesn't ask again. Each version's read-by day is a week after
  it is published; reading after it is late, and the practice and the client
  owner get a Notice.
- **Remind** drafts one email to each person who hasn't read it, into the
  Sending queue for approval. **Suggest a change** is a comment for the
  practice, with a Notice to whoever published.
"""

from __future__ import annotations

import re
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.tenancy.models import AuditEvent, CLIENT_ROLES, Role, TENANT_ROLES

from . import flow
from . import layout as L
from .access import audience_memberships
from .models import (Sop, SopAck, SopAttachment, SopAudiencePerson, SopAudienceTeam,
                     SopComment, SopKpi, SopTrainingAsset, SopVersion)

READ_WITHIN_DAYS = 7
MAX_STEPS = 60
MAX_ROLES = 20
MAX_SECTIONS = 12
MAX_DEFINITIONS = 40
MAX_RELATED = 30
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
PDF_TYPE = "application/pdf"


class SopRefused(ValueError):
    def __init__(self, message, status=400, errors=None):
        super().__init__(message)
        self.status = status
        self.errors = errors or []


def _audit(sop_or_company, actor, verb, **payload):
    company = getattr(sop_or_company, "company", sop_or_company)
    AuditEvent.all_objects.create(tenant_id=company.tenant_id, actor=actor, verb=verb,
                                  target_type="company", target_id=company.pk, payload=payload)


def _name(user) -> str:
    return (user.full_name or user.email) if user is not None else ""


def _today(company):
    from apps.scorecard import board

    return board.today_for(company.tenant)


def _words(value, limit) -> str:
    return " ".join(str(value or "").split())[:limit]


def _text(value, limit) -> str:
    return str(value or "").strip()[:limit]


# ------------------------------------------------------------------ the template

#: A section's guidance, as the hint on the field it fills (the editor's names).
HINT_FIELD = {"purpose": "purpose", "scope": "applies_when", "roles": "roles",
              "steps": "steps", "metrics": "kpis", "overview": "review_date",
              "definitions": "definitions", "related": "related", "training": "training",
              "flowchart": "process_map"}


def _template_body(tenant_id) -> str:
    from apps.centers.content import operations

    body = operations.DOCUMENTS["ops_sop"][2]
    try:
        from apps.esign.models import DocumentTemplate

        own = DocumentTemplate.all_objects.filter(tenant_id=tenant_id,
                                                  original="ops_sop").first()
        if own is not None and (own.body or "").strip():
            body = own.body
    except (ImportError, LookupError, AttributeError):
        pass
    return body


def layout_of(tenant_id) -> list[dict]:
    """The SOP's sections in the practice's order and names (`apps.sops.layout`)."""
    return L.resolve(_template_body(tenant_id))


def template(tenant_id) -> dict:
    """The practice's copy of the SOP document template, or the Operations
    Command Center's: {"hints": {field: guidance}, "sections": [free-text
    sections], "layout": [{key, title, hint}]}."""
    shape = layout_of(tenant_id)
    hints = {HINT_FIELD[s["key"]]: s["hint"] for s in shape if s["key"] in HINT_FIELD}
    sections = [{"title": s["title"], "body": "", "hint": s["hint"]}
                for s in shape if s["key"] == "custom"]
    return {"hints": hints, "sections": sections[:MAX_SECTIONS], "layout": shape}


# ------------------------------------------------------------------ the overview

#: A category's prefix for the SOP number. Any other category takes its first
#: three letters; none at all is "SOP".
PREFIXES = {"operations": "OPS", "sales": "SAL", "safety": "SAF", "shipping": "SHP",
            "receiving": "RCV", "quality": "QA", "production": "PRD", "maintenance": "MNT",
            "finance": "FIN", "accounting": "ACC", "hiring": "HR", "people": "HR",
            "human resources": "HR", "marketing": "MKT", "purchasing": "PUR",
            "customer service": "CS", "it": "IT", "admin": "ADM", "administration": "ADM"}
#: How often an SOP is reviewed: the three named choices; any other number
#: of months is "Every N months".
REVIEW_CHOICES = {3: "Quarterly", 6: "Twice a year", 12: "Yearly"}
MAX_REVIEW_MONTHS = 60


def prefix_of(category: str) -> str:
    words = " ".join(str(category or "").lower().split())
    if not words:
        return "SOP"
    if words in PREFIXES:
        return PREFIXES[words]
    letters = re.sub(r"[^a-z]", "", words)
    return (letters[:3] or "SOP").upper()


def _clean_number(value) -> str:
    return re.sub(r"[^A-Z0-9-]", "", re.sub(r"\s+", "-", str(value or "").strip().upper()))[:20]


def next_number(company, category, *, exclude=None) -> str:
    """The company's next free number for the category's prefix: OPS-01, OPS-02…"""
    prefix = prefix_of(category)
    taken = set(Sop.objects.filter(company=company).exclude(pk=getattr(exclude, "pk", None))
                .values_list("number", flat=True))
    n = 1
    for number in taken:
        m = re.fullmatch(re.escape(prefix) + r"-(\d+)", number or "")
        if m:
            n = max(n, int(m.group(1)) + 1)
    while f"{prefix}-{n:02d}" in taken:
        n += 1
    return f"{prefix}-{n:02d}"


def review_label(months) -> str:
    if not months:
        return ""
    return REVIEW_CHOICES.get(months, f"Every {months} months")


def next_review(months, *, base, today):
    """The next review: `months` after `base`, rolled on past today."""
    from dateutil.relativedelta import relativedelta

    if not months:
        return None
    day = base + relativedelta(months=months)
    while day <= today:
        day += relativedelta(months=months)
    return day


def prefix_of_number(number: str) -> str:
    return (number or "").rsplit("-", 1)[0] if "-" in (number or "") else ""


# ------------------------------------------------------------------ making and editing

@transaction.atomic
def create(company, *, actor, title, data=None, from_ai_app=False) -> Sop:
    title = _words(title, 200)
    if not title:
        raise SopRefused("An SOP needs a title.")
    shape = template(company.tenant_id)
    category = _words((data or {}).get("category"), 80)
    for attempt in range(5):
        # The number is the company's next free one; two made at the same
        # moment clash on the unique number, and the second takes the next.
        try:
            with transaction.atomic():
                sop = Sop.objects.create(
                    tenant_id=company.tenant_id, company=company, title=title,
                    created_by=actor, updated_by=actor, from_ai_app=from_ai_app,
                    category=category, number=next_number(company, category),
                    sections=[{"title": s["title"], "body": ""} for s in shape["sections"]])
            break
        except IntegrityError:
            if attempt == 4:
                raise SopRefused("The SOP's number couldn't be given just now. Try again.",
                                 409) from None
    if data:
        update(sop, data, actor=actor)
    _audit(sop, actor, "sops.created", title=sop.title, sop=str(sop.pk))
    return sop


def _clean_roles(value) -> list:
    out = []
    for row in (value or [])[:MAX_ROLES]:
        if isinstance(row, str):
            row = {"name": row}
        if not isinstance(row, dict):
            continue
        name = _words(row.get("name"), 80)
        if name:
            out.append({"name": name, "does": _text(row.get("does"), 500)})
    return out


def _clean_steps(sop, value) -> list:
    if not isinstance(value, list):
        raise SopRefused("The steps are a list.")
    if len(value) > MAX_STEPS:
        raise SopRefused(f"An SOP holds {MAX_STEPS} steps at most.")
    images = {str(a) for a in SopAttachment.objects.filter(
        sop=sop, kind=SopAttachment.Kind.IMAGE).values_list("pk", flat=True)}
    out = []
    for row in value:
        if isinstance(row, str):
            row = {"text": row}
        if not isinstance(row, dict):
            continue
        text = _text(row.get("text"), 2000)
        if not text:
            continue
        chosen = [str(i) for i in (row.get("images") or []) if str(i) in images][:6]
        out.append({"text": text, "role": _words(row.get("role"), 80),
                    "when": _text(row.get("when"), 600),
                    "warning": _text(row.get("warning"), 600), "images": chosen})
    return out


def _clean_definitions(value) -> list:
    out = []
    for row in (value or [])[:MAX_DEFINITIONS]:
        if isinstance(row, dict) and _words(row.get("term"), 120):
            out.append({"term": _words(row.get("term"), 120),
                        "definition": _text(row.get("definition"), 1000)})
    return out


def _clean_related(sop, value) -> list:
    """Links, documents in the app (the company's), and the company's other SOPs."""
    from apps.esign.models import Document

    out = []
    for row in (value or [])[:MAX_RELATED]:
        if not isinstance(row, dict):
            continue
        kind = row.get("kind") or "link"
        ref = str(row.get("ref") or "")
        if kind == "sop":
            other = Sop.objects.filter(company=sop.company, pk=ref).exclude(pk=sop.pk) \
                .first() if _uuid(ref) else None
            if other is None:
                raise SopRefused("A related SOP is one of this company's other SOPs.")
            out.append({"kind": "sop", "title": other.title, "ref": str(other.pk)})
        elif kind == "document":
            document = Document.all_objects.filter(
                tenant_id=sop.tenant_id, company=sop.company, pk=ref).first() \
                if _uuid(ref) else None
            if document is None:
                raise SopRefused("A related document is one of this company's documents.")
            out.append({"kind": "document", "title": document.title, "ref": str(document.pk)})
        elif kind == "link":
            url = str(row.get("url") or "").strip()[:1000]
            title = _words(row.get("title"), 200)
            if url and not re.match(r"^https?://\S+$", url):
                raise SopRefused("A link starts with http:// or https://.")
            if title or url:
                out.append({"kind": "link", "title": title or url, "url": url})
        else:
            raise SopRefused("A related item is a link, a document or another SOP.")
    return out


def _clean_sections(value) -> list:
    out = []
    for row in (value or [])[:MAX_SECTIONS]:
        if isinstance(row, dict) and _words(row.get("title"), 120):
            out.append({"title": _words(row.get("title"), 120),
                        "body": _text(row.get("body"), 6000)})
    return out


def owner_choices(company) -> list:
    """Who may own an SOP: the practice's people and the company's portal users."""
    from apps.tenancy.models import Membership

    rows = Membership.all_objects.filter(tenant_id=company.tenant_id, revoked_at__isnull=True) \
        .select_related("user")
    staff = rows.filter(role__in=TENANT_ROLES)
    clients = rows.filter(role__in=CLIENT_ROLES, client_company_id=company.pk) \
        if not company.is_practice else rows.none()
    out, seen = [], set()
    for m in list(clients) + list(staff):
        if m.user_id in seen:
            continue
        seen.add(m.user_id)
        out.append({"id": str(m.user_id), "name": _name(m.user),
                    "side": "client" if m.role in CLIENT_ROLES else "practice"})
    return out


def _date(value, what="review date"):
    from datetime import date

    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise SopRefused(f"The {what} is a date.") from None


@transaction.atomic
def update(sop, data: dict, *, actor) -> Sop:
    """Edit the working copy. What is published doesn't change until the next
    publish."""
    from apps.scorecard.models import Kpi
    from apps.tenancy.models import Membership
    from apps.work.models import ClientTeam

    changed = []
    review_before = sop.review_date
    if "title" in data:
        title = _words(data.get("title"), 200)
        if not title:
            raise SopRefused("An SOP needs a title.")
        sop.title = title
        changed.append("title")
    for key, limit in (("purpose", 6000), ("applies_when", 3000)):
        if key in data:
            setattr(sop, key, _text(data.get(key), limit))
            changed.append(key)
    if "category" in data:
        sop.category = _words(data.get("category"), 80)
        changed.append("category")
    # The overview (2026-11-14). An automatic number follows the category
    # until the SOP is first published or a person types one.
    if "category" in data and not sop.number_by_hand and sop.version == 0 \
            and prefix_of(sop.category) != prefix_of_number(sop.number):
        sop.number = next_number(sop.company, sop.category, exclude=sop)
        changed.append("number")
    if "number" in data:
        number = _clean_number(data.get("number"))
        if not number:
            sop.number = next_number(sop.company, sop.category, exclude=sop)
            sop.number_by_hand = False
        else:
            if Sop.objects.filter(company=sop.company, number=number).exclude(
                    pk=sop.pk).exists():
                raise SopRefused(f"{number} is already another of this company's SOPs.")
            if number != sop.number:
                sop.number_by_hand = True
            sop.number = number
        changed += ["number", "number_by_hand"]
    if "effective_date" in data:
        sop.effective_date = _date(data.get("effective_date"), "effective date")
        changed.append("effective_date")
    if "review_months" in data:
        months = data.get("review_months")
        try:
            months = int(months) if months not in (None, "") else None
        except (TypeError, ValueError):
            raise SopRefused("The review frequency is a number of months.") from None
        if months is not None and not 1 <= months <= MAX_REVIEW_MONTHS:
            raise SopRefused(f"Review it every 1 to {MAX_REVIEW_MONTHS} months.")
        if months != sop.review_months:
            sop.review_months = months
            changed.append("review_months")
            if months:
                today = _today(sop.company)
                sop.review_date = next_review(months, base=sop.effective_date or today,
                                              today=today)
                changed.append("review_date")
    if "definitions" in data:
        sop.definitions = _clean_definitions(data.get("definitions"))
        changed.append("definitions")
    if "related" in data:
        sop.related = _clean_related(sop, data.get("related"))
        changed.append("related")
    for key, limit in (("training", 6000), ("metrics", 6000)):
        if key in data:
            setattr(sop, key, _text(data.get(key), limit))
            changed.append(key)
    if "roles" in data:
        sop.roles = _clean_roles(data.get("roles"))
        changed.append("roles")
    if "steps" in data:
        sop.steps = _clean_steps(sop, data.get("steps"))
        changed.append("steps")
    if "sections" in data:
        sop.sections = _clean_sections(data.get("sections"))
        changed.append("sections")
    if "review_date" in data:
        sent = _date(data.get("review_date"))
        # A new frequency sets the next review; the date the form sent along
        # with it, unchanged, doesn't undo that. A date typed by hand does.
        if not ("review_months" in changed and sent == review_before):
            sop.review_date = sent
            changed.append("review_date")
    if "process_map" in data:
        text = _text(data.get("process_map"), 12000)
        errors = flow.check(text) if text else []
        if errors:
            raise SopRefused("The process map couldn't be read.", errors=errors)
        sop.process_map = text
        changed.append("process_map")
    if "owner" in data:
        owner = str(data.get("owner") or "")
        if owner and owner not in {c["id"] for c in owner_choices(sop.company)}:
            raise SopRefused("The owner is someone at the practice or at the company.")
        sop.owner_id = owner or None
        changed.append("owner")
    if "audience" in data:
        kind = data.get("audience")
        if kind not in Sop.Audience.values:
            raise SopRefused("The audience is the whole company, chosen teams or named people.")
        sop.audience = kind
        changed.append("audience")
        teams = [str(t) for t in data.get("teams") or []]
        people = [str(p) for p in data.get("people") or []]
        SopAudienceTeam.objects.filter(sop=sop).delete()
        SopAudiencePerson.objects.filter(sop=sop).delete()
        if kind == Sop.Audience.TEAMS:
            found = ClientTeam.objects.filter(pk__in=[t for t in teams if _uuid(t)],
                                              client_company=sop.company,
                                              archived_at__isnull=True)
            if not found:
                raise SopRefused("Choose at least one of the company's teams.")
            for team in found:
                SopAudienceTeam.objects.create(tenant_id=sop.tenant_id, sop=sop, team=team)
        elif kind == Sop.Audience.PEOPLE:
            found = Membership.all_objects.filter(
                pk__in=[p for p in people if _uuid(p)], tenant_id=sop.tenant_id,
                client_company_id=sop.company_id, role__in=CLIENT_ROLES, revoked_at__isnull=True)
            if not found:
                raise SopRefused("Choose at least one person at the company.")
            for m in found:
                SopAudiencePerson.objects.create(tenant_id=sop.tenant_id, sop=sop, membership=m)
    if "kpis" in data:
        ids = [str(k) for k in data.get("kpis") or [] if _uuid(k)]
        kpis = Kpi.objects.filter(pk__in=ids, scorecard__company=sop.company,
                                  archived_at__isnull=True)
        SopKpi.objects.filter(sop=sop).exclude(kpi__in=kpis).delete()
        have = set(SopKpi.objects.filter(sop=sop).values_list("kpi_id", flat=True))
        for kpi in kpis:
            if kpi.pk not in have:
                SopKpi.objects.create(tenant_id=sop.tenant_id, sop=sop, kpi=kpi)
    sop.updated_by = actor
    # Only what this edit touched: never the version, status or dates.
    sop.save(update_fields=[*dict.fromkeys(changed), "updated_by", "updated_at"])
    return sop


def _uuid(value) -> bool:
    from .access import _is_uuid

    return _is_uuid(value)


# ------------------------------------------------------------------ attachments

@transaction.atomic
def attach(sop, upload, *, actor) -> SopAttachment:
    from apps.tenancy import storage

    content_type = (getattr(upload, "content_type", "") or "").split(";")[0].lower()
    if content_type not in IMAGE_TYPES and content_type != PDF_TYPE:
        raise SopRefused("An attachment is an image (PNG, JPEG, GIF, WebP) or a PDF.")
    if upload.size > MAX_ATTACHMENT_BYTES:
        raise SopRefused("An attachment is 10 MB at most.")
    content = upload.read()
    name = re.sub(r"[^A-Za-z0-9._ -]+", "", getattr(upload, "name", "") or "file")[:120] or "file"
    stored = storage.save(tenant=sop.company.tenant, content=content,
                          object_key=storage.object_key(f"sops/{sop.pk}", name),
                          purpose="sop_attachment", content_type=content_type)
    return SopAttachment.objects.create(
        tenant_id=sop.tenant_id, sop=sop, file=stored, name=name, created_by=actor,
        kind=SopAttachment.Kind.PDF if content_type == PDF_TYPE else SopAttachment.Kind.IMAGE)


def _published_attachment_ids(sop) -> set:
    out = set()
    for snapshot in SopVersion.objects.filter(sop=sop).values_list("snapshot", flat=True):
        out |= {str(a["id"]) for a in (snapshot or {}).get("attachments", [])}
    return out


@transaction.atomic
def detach(sop, attachment_id, *, actor):
    attachment = SopAttachment.objects.filter(sop=sop, pk=attachment_id).first() \
        if _uuid(attachment_id) else None
    if attachment is None:
        raise SopRefused("That isn't one of this SOP's attachments.", 404)
    if str(attachment.pk) in _published_attachment_ids(sop):
        raise SopRefused("It's in a published version, so it stays.", 409)
    sop.steps = [{**s, "images": [i for i in s.get("images", []) if i != str(attachment.pk)]}
                 for s in sop.steps]
    sop.save(update_fields=["steps", "updated_at"])
    attachment.delete()


# ------------------------------------------------------------------ training assets

#: The largest file of each kind (2026-11-14). A link has no limit: the file
#: stays where it is (the company's Google Drive, say).
TRAINING_LIMITS_MB = {"video": 100, "audio": 50, "slides": 25, "quiz": 25,
                      "flashcards": 25, "other": 25}
MAX_TRAINING_ASSETS = 30


def add_training(sop, *, actor, kind, title, upload=None, url="") -> SopTrainingAsset:
    from apps.tenancy import storage

    if kind not in SopTrainingAsset.Kind.values:
        raise SopRefused("Choose what kind of material it is.")
    title = _words(title, 200)
    url = str(url or "").strip()[:1000]
    if (upload is None) == (not url):
        raise SopRefused("Upload a file or give a link, one of the two.")
    if url and not re.match(r"^https://[^\s]+$", url):
        raise SopRefused("A link starts with https://.")
    if SopTrainingAsset.objects.filter(sop=sop).count() >= MAX_TRAINING_ASSETS:
        raise SopRefused(f"An SOP holds {MAX_TRAINING_ASSETS} training items at most.")
    stored = None
    if upload is not None:
        limit = TRAINING_LIMITS_MB[kind]
        if upload.size > limit * 1024 * 1024:
            raise SopRefused(f"A {SopTrainingAsset.Kind(kind).label.lower()} file is "
                             f"{limit} MB at most. Put a bigger one in the company's Drive "
                             "and add the link instead.")
        content = upload.read()
        name = re.sub(r"[^A-Za-z0-9._ -]+", "", getattr(upload, "name", "") or "file")[:120] \
            or "file"
        stored = storage.save(tenant=sop.company.tenant, content=content,
                              object_key=storage.object_key(f"sops/{sop.pk}/training", name),
                              purpose="sop_training",
                              content_type=(upload.content_type or "application/octet-stream")
                              .split(";")[0][:100])
        title = title or _words(name.rsplit(".", 1)[0], 200)
    if not title:
        raise SopRefused("Give it a title.")
    asset = SopTrainingAsset.objects.create(
        tenant_id=sop.tenant_id, sop=sop, kind=kind, title=title, file=stored, url=url,
        created_by=actor)
    Sop.objects.filter(pk=sop.pk).update(updated_at=timezone.now())
    _audit(sop, actor, "sops.training_added", sop=str(sop.pk), title=title, kind=kind)
    return asset


def remove_training(sop, asset_id, *, actor):
    asset = SopTrainingAsset.objects.filter(sop=sop, pk=asset_id).first() \
        if _uuid(asset_id) else None
    if asset is None:
        raise SopRefused("That isn't one of this SOP's training items.", 404)
    from apps.tenancy import storage

    stored = asset.file
    asset.delete()
    if stored is not None:
        try:
            storage.delete(stored)
        except storage.StorageError:
            pass
    Sop.objects.filter(pk=sop.pk).update(updated_at=timezone.now())
    _audit(sop, actor, "sops.training_removed", sop=str(sop.pk), title=asset.title)


def training_rows(sop) -> list[dict]:
    return [{"id": str(a.pk), "kind": a.kind, "label": a.get_kind_display(), "title": a.title,
             "url": a.url or f"/api/sops/{sop.pk}/training/{a.pk}/",
             "is_link": bool(a.url), "size": a.file.byte_size if a.file_id else None}
            for a in sop.training_assets.select_related("file")]


# ------------------------------------------------------------------ related documents

def _document_choices(company) -> list:
    from apps.esign.models import Document

    if company.is_practice:
        return []
    return [{"id": str(d.pk), "title": d.title, "state": d.get_state_display()}
            for d in Document.all_objects.filter(tenant_id=company.tenant_id, company=company)
            .order_by("-created_at")[:100]]


def related_rows(sop, rows, *, staff, membership=None) -> list:
    """The related items with where each opens: a link to itself, another SOP
    on its page (in the portal only when the reader can open it), a document
    on the company's page or, for a client, the portal's Documents."""
    from .access import portal_reaches

    others = {str(o.pk): o for o in Sop.objects.filter(
        company=sop.company, pk__in=[r.get("ref") for r in rows or []
                                     if r.get("kind") == "sop" and _uuid(r.get("ref"))])}
    out = []
    for row in rows or []:
        href = None
        if row.get("kind") == "link":
            href = row.get("url") or None
        elif row.get("kind") == "sop":
            other = others.get(str(row.get("ref")))
            if other is not None and (staff or (membership is not None
                                                and portal_reaches(other, membership))):
                href = f"/sops/{other.pk}"
            row = {**row, "number": other.number if other is not None else ""}
        elif row.get("kind") == "document":
            href = "/documents" if not staff else (
                None if sop.company.is_practice else f"/companies/{sop.company_id}")
        out.append({**row, "href": href})
    return out


# ------------------------------------------------------------------ versions

def snapshot(sop) -> dict:
    kpis = [{"id": str(link.kpi_id), "name": link.kpi.name}
            for link in sop.kpi_links.select_related("kpi").filter(kpi__archived_at__isnull=True)]
    used = {i for s in sop.steps for i in s.get("images", [])}
    attachments = [{"id": str(a.pk), "name": a.name, "kind": a.kind}
                   for a in sop.attachments.all()
                   if a.kind == SopAttachment.Kind.PDF or str(a.pk) in used]
    return {"title": sop.title, "number": sop.number,
            "effective_date": sop.effective_date.isoformat() if sop.effective_date else None,
            "review_months": sop.review_months,
            "purpose": sop.purpose, "applies_when": sop.applies_when,
            "definitions": sop.definitions, "roles": sop.roles, "steps": sop.steps,
            "related": sop.related, "training": sop.training, "metrics": sop.metrics,
            "sections": sop.sections, "owner": _name(sop.owner), "category": sop.category,
            "review_date": sop.review_date.isoformat() if sop.review_date else None,
            "process_map": sop.process_map, "kpis": kpis, "attachments": attachments}


#: What a version published before the eleven sections (2026-11-14) lacks,
#: read as empty. The number is given to every SOP by the migration, so a
#: version without one isn't a change to publish.
SNAPSHOT_EMPTY = {"number": "", "effective_date": None, "review_months": None,
                  "definitions": [], "related": [], "training": "", "metrics": ""}


def _same(old: dict, now: dict) -> bool:
    for key, value in now.items():
        if key not in old:
            if key == "number" or value in (SNAPSHOT_EMPTY.get(key), "", [], None):
                continue
            return False
        if key == "steps":
            # A step published before steps had a trigger reads as one without.
            if [{"when": "", **x} for x in old.get(key) or []] != \
                    [{"when": "", **x} for x in value or []]:
                return False
            continue
        if old[key] != value:
            return False
    return True


def revisions(sop, up_to=None) -> list[dict]:
    """The revision history: each published version's date, number, what
    changed and who published it, oldest first (up to a version, for its PDF)."""
    rows = SopVersion.objects.filter(sop=sop).select_related("published_by").order_by("number")
    if up_to is not None:
        rows = rows.filter(number__lte=up_to)
    return [{"date": v.published_at.date().isoformat(), "version": v.number,
             "change": v.change_note + (" (minor change)" if v.minor else ""),
             "author": _name(v.published_by)} for v in rows]


def latest(sop):
    return SopVersion.objects.filter(sop=sop).order_by("-number").first()


def unpublished_changes(sop) -> bool:
    last = latest(sop)
    if last is None:
        return True
    return not _same(last.snapshot or {}, snapshot(sop))


@transaction.atomic
def publish(sop, *, actor, change_note="", minor=False) -> SopVersion:
    from apps.centers import recorder
    from apps.centers.models import LibraryRecord

    # Lock the row, then work on the caller's own object, read fresh, so it
    # never holds a stale version number afterwards.
    Sop.objects.select_for_update().filter(pk=sop.pk).first()
    sop.refresh_from_db()
    if sop.status == Sop.Status.ARCHIVED:
        raise SopRefused("Restore it before publishing.", 409)
    if not sop.steps:
        raise SopRefused("Add at least one step before publishing.")
    note = _text(change_note, 2000)
    first = sop.version == 0
    if first:
        minor = False
        note = note or "First version."
    elif not note:
        raise SopRefused("Say what changed, in a line.")
    if not audience_memberships(sop) and sop.audience != Sop.Audience.COMPANY:
        raise SopRefused("The audience has nobody in it yet.")
    now = timezone.now()
    today = _today(sop.company)
    # The overview: the first version takes effect the day it is published
    # unless a date was set; a review frequency sets the next review from
    # each publish.
    if first and sop.effective_date is None:
        sop.effective_date = today
    if sop.review_months and not minor:
        sop.review_date = next_review(sop.review_months, base=today, today=today)
    if first and not sop.number:
        sop.number = next_number(sop.company, sop.category, exclude=sop)
    number = sop.version + 1
    version = SopVersion.objects.create(
        tenant_id=sop.tenant_id, sop=sop, number=number, change_note=note, minor=bool(minor),
        snapshot=snapshot(sop), published_by=actor, published_at=now,
        read_by=_today(sop.company) + timedelta(days=READ_WITHIN_DAYS))
    sop.version = number
    if not minor:
        sop.ask_number = number
    sop.status = Sop.Status.PUBLISHED
    sop.published_at = now
    sop.updated_by = actor
    sop.save()
    _audit(sop, actor, "sops.published", title=sop.title, sop=str(sop.pk), number=number,
           minor=bool(minor))
    if recorder._recording(sop.tenant_id):
        recorder.keep(sop.tenant_id, kind=LibraryRecord.Kind.SOP, source_type="sop",
                      source_id=sop.pk, title=sop.title,
                      structure={"purpose": sop.purpose, "roles": sop.roles,
                                 "steps": [s["text"] for s in sop.steps],
                                 "category": sop.category, "version": number})
    if not minor and not sop.company.is_practice:
        from apps.work.digests import UNSENT_DRAFTS
        from apps.work.models import Cadence, Digest

        # A weekly draft already waiting is marked out of date, so its Update
        # button adds the SOP's line; it is never rewritten behind anyone's back.
        Digest.all_objects.filter(
            tenant_id=sop.tenant_id, contact__company=sop.company, cadence=Cadence.WEEKLY,
            state__in=UNSENT_DRAFTS).update(is_stale=True, stale_reason=DIGEST_STALE)
    return version


@transaction.atomic
def archive(sop, *, actor) -> Sop:
    sop.status = Sop.Status.ARCHIVED
    sop.archived_at = timezone.now()
    sop.updated_by = actor
    sop.save(update_fields=["status", "archived_at", "updated_by", "updated_at"])
    _audit(sop, actor, "sops.archived", title=sop.title, sop=str(sop.pk))
    return sop


@transaction.atomic
def restore(sop, *, actor) -> Sop:
    sop.status = Sop.Status.PUBLISHED if sop.version else Sop.Status.DRAFT
    sop.archived_at = None
    sop.updated_by = actor
    sop.save(update_fields=["status", "archived_at", "updated_by", "updated_at"])
    return sop


# ------------------------------------------------------------------ reading it

def _asking(sop):
    return SopVersion.objects.filter(sop=sop, number=sop.ask_number).first() \
        if sop.ask_number else None


def has_read(sop, membership) -> bool:
    return SopAck.objects.filter(sop=sop, membership=membership,
                                 version__number__gte=sop.ask_number or 1).exists()


def reads(sop) -> dict:
    """"7 of 12 read": who is asked, who has read the version that asks, and
    who hasn't yet."""
    if not sop.version:
        return {"asked": 0, "read": 0, "outstanding": [], "readers": [], "number": 0}
    people = audience_memberships(sop)
    acks = {}
    for ack in SopAck.objects.filter(sop=sop, version__number__gte=sop.ask_number) \
            .select_related("version").order_by("acknowledged_at"):
        acks.setdefault(ack.membership_id, ack)
    readers, outstanding = [], []
    for m in people:
        ack = acks.get(m.pk)
        if ack is None:
            outstanding.append({"membership": str(m.pk), "name": _name(m.user)})
        else:
            readers.append({"membership": str(m.pk), "name": _name(m.user),
                            "at": ack.acknowledged_at.isoformat(),
                            "version": ack.version.number, "late": ack.late})
    asking = _asking(sop)
    return {"asked": len(people), "read": len(readers), "outstanding": outstanding,
            "readers": readers, "number": sop.ask_number,
            "read_by": asking.read_by.isoformat() if asking and asking.read_by else None}


@transaction.atomic
def acknowledge(sop, *, membership, user) -> dict:
    from .access import portal_reaches

    if not portal_reaches(sop, membership):
        raise SopRefused("That SOP isn't one you're asked to read.", 404)
    version = latest(sop)
    already = SopAck.objects.filter(version=version, membership=membership).first()
    if already is not None:
        return {"acknowledged_at": already.acknowledged_at.isoformat(),
                "version": version.number, "late": already.late}
    asking = _asking(sop) or version
    today = _today(sop.company)
    late = bool(asking.read_by and today > asking.read_by)
    ack = SopAck.objects.create(tenant_id=sop.tenant_id, sop=sop, version=version,
                                membership=membership, user=user,
                                acknowledged_at=timezone.now(), late=late)
    if late:
        _tell_late(sop, ack, asking)
    return {"acknowledged_at": ack.acknowledged_at.isoformat(), "version": version.number,
            "late": late}


def _client_owners(company) -> list:
    from apps.tenancy.models import Membership

    return list(Membership.all_objects.filter(
        tenant_id=company.tenant_id, client_company_id=company.pk, role=Role.FCC,
        revoked_at__isnull=True).values_list("user_id", flat=True))


def _tell_late(sop, ack, asking):
    from apps.notify import service as notices
    from apps.notify.models import Kind

    who = _name(ack.user)
    when = asking.read_by.strftime("%B ") + str(asking.read_by.day)
    for recipient in {asking.published_by_id, *_client_owners(sop.company)} - {ack.user_id, None}:
        portal = recipient in _client_owners(sop.company)
        notices.tell(tenant_id=sop.tenant_id, recipient_id=recipient, kind=Kind.SOP,
                     title=f"{who} read “{sop.title}” late"[:120],
                     text=f"Version {ack.version.number} was to be read by {when}; "
                          f"{who} ticked “Read and understood” today.",
                     url=f"/sops/{sop.pk}" if portal else f"/sops/{sop.pk}",
                     source_type="sop_ack", source_id=ack.pk)


REMIND_SUBJECT = "Please read: {title}"
REMIND_BODY = ("Hi {first},\n\n{asker} asked you to read “{title}” (version {number}) and tick "
               "“Read and understood” at the bottom when you have:\n\n{link}\n\n"
               "If something in it doesn't match how the work is done, use “Suggest a "
               "change” on the same page.\n")


@transaction.atomic
def remind(sop, *, actor, role) -> dict:
    """One draft to each person who hasn't read it, waiting in the Sending
    queue. A person with a reminder already waiting gets no second one."""
    from apps.crm.models import OutboxMessage
    from apps.crm.services import outbox

    if not sop.version or sop.status != Sop.Status.PUBLISHED:
        raise SopRefused("Publish it first.", 409)
    state = reads(sop)
    if not state["outstanding"]:
        raise SopRefused("Everyone asked has read it.", 409)
    waiting = set(OutboxMessage.all_objects.filter(
        tenant_id=sop.tenant_id, producer=OutboxMessage.Producer.SOP_REMINDER,
        source_type="sop", source_id=sop.pk,
        state=OutboxMessage.State.PENDING_APPROVAL).values_list("to_address", flat=True))
    from apps.tenancy.models import Membership

    link = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/sops/{sop.pk}"
    # A client owner's reminder goes from the practice, like any other: the
    # sender is whoever published it, and the draft waits for the practice.
    sender = actor if role in TENANT_ROLES else (latest(sop).published_by or None)
    made, skipped = 0, 0
    for row in state["outstanding"]:
        m = Membership.all_objects.select_related("user", "contact").get(pk=row["membership"])
        address = (m.contact.primary_email if m.contact_id else "") or m.user.email
        if not address or address.lower() in {w.lower() for w in waiting}:
            skipped += 1
            continue
        first = (m.contact.first_name if m.contact_id else "") or \
            (m.user.full_name or "").split(" ")[0] or "there"
        outbox.create_message(
            tenant=sop.company.tenant, producer=OutboxMessage.Producer.SOP_REMINDER,
            to_address=address, to_contact=m.contact if m.contact_id else None,
            subject=REMIND_SUBJECT.format(title=sop.title)[:250],
            body_text=REMIND_BODY.format(first=first, asker=_name(actor) or "Your practice",
                                         title=sop.title, number=sop.version, link=link),
            role=role, actor=sender, source_type="sop", source_id=sop.pk,
            send_by=timezone.now() + timedelta(days=7))
        made += 1
    _audit(sop, actor, "sops.reminded", title=sop.title, sop=str(sop.pk), count=made)
    return {"drafted": made, "skipped": skipped}


@transaction.atomic
def suggest(sop, *, membership, user, text) -> SopComment:
    from apps.notify import service as notices
    from apps.notify.models import Kind

    from .access import portal_reaches

    text = _text(text, 4000)
    if len(text) < 3:
        raise SopRefused("Say what should change.")
    if membership.role in CLIENT_ROLES and not portal_reaches(sop, membership):
        raise SopRefused("That SOP isn't one you're asked to read.", 404)
    comment = SopComment.objects.create(tenant_id=sop.tenant_id, sop=sop,
                                        version_number=sop.version, author=user, text=text)
    last = latest(sop)
    recipient = (last.published_by_id if last else None) or sop.created_by_id
    if recipient and recipient != user.pk:
        notices.tell(tenant_id=sop.tenant_id, recipient_id=recipient, kind=Kind.SOP,
                     title=f"A change suggested to “{sop.title}”"[:120],
                     text=f"{_name(user)}: {text}"[:500], url=f"/sops/{sop.pk}",
                     source_type="sop_comment", source_id=comment.pk)
    return comment


def resolve(sop, comment_id, *, actor) -> SopComment:
    comment = SopComment.objects.filter(sop=sop, pk=comment_id).first() \
        if _uuid(comment_id) else None
    if comment is None:
        raise SopRefused("That isn't one of this SOP's suggestions.", 404)
    comment.resolved_at, comment.resolved_by = timezone.now(), actor
    comment.save(update_fields=["resolved_at", "resolved_by", "updated_at"])
    return comment


# ------------------------------------------------------------------ the weekly digest

DIGEST_HEADING = "SOPs to read"
DIGEST_STALE = "An SOP was published or updated. Update this draft to include it."


def digest_lines(digest) -> list[str]:
    """New and updated SOPs since the last digest this person was sent, if
    they are asked to read them (or own the company)."""
    from apps.tenancy.models import Membership
    from apps.work.models import Cadence, Digest

    from .access import available, in_audience

    contact = getattr(digest, "contact", None)
    company = getattr(contact, "company", None)
    if company is None or getattr(digest, "cadence", None) != Cadence.WEEKLY \
            or not available(company.tenant_id):
        return []
    membership = Membership.all_objects.filter(
        tenant_id=company.tenant_id, contact=contact, client_company=company,
        revoked_at__isnull=True).first()
    if membership is None:
        return []
    last = (Digest.objects.filter(contact=contact, state=Digest.State.SENT)
            .exclude(pk=digest.pk).order_by("-period_end")
            .values_list("period_end", flat=True).first())
    since = last or (digest.created_at or digest.period_start) - timedelta(days=14)
    lines = []
    for v in SopVersion.all_objects.filter(
            sop__company=company, sop__status=Sop.Status.PUBLISHED, minor=False,
            published_at__gt=since).select_related("sop").order_by("published_at"):
        if membership.role != Role.FCC and not in_audience(v.sop, membership):
            continue
        lines.append(f"New: {v.sop.title}" if v.number == 1 else
                     f"Updated to version {v.number}: {v.sop.title}. {v.change_note}".strip())
    return lines


# ------------------------------------------------------------------ for the screens

def summary(sop, access=None) -> dict:
    state = reads(sop) if (access is None or access.sees_reads) else None
    return {"id": str(sop.pk), "title": sop.title, "number": sop.number, "status": sop.status,
            "category": sop.category, "version": sop.version,
            "company": {"id": "practice" if sop.company.is_practice else str(sop.company_id),
                        "name": sop.company.name, "is_practice": sop.company.is_practice},
            "owner": _name(sop.owner), "review_date": sop.review_date.isoformat()
            if sop.review_date else None,
            "published_at": sop.published_at.isoformat() if sop.published_at else None,
            "updated_at": sop.updated_at.isoformat(), "from_ai_app": sop.from_ai_app,
            "reads": {"asked": state["asked"], "read": state["read"]} if state else None}


def list_for(request, *, company=None, q="", status="", category="") -> list:
    """Every SOP the person reaches, newest change first: the practice's
    across the companies it reaches; a client user's published ones only."""
    from apps.crm import permissions as crm_perms
    from apps.crm.models import Company

    from .access import SopAccess, portal_reaches

    membership = request.membership
    rows = Sop.objects.select_related("company", "owner").order_by("company__name", "title")
    if membership.role in CLIENT_ROLES:
        rows = rows.filter(company_id=membership.client_company_id,
                           status=Sop.Status.PUBLISHED)
        found = [s for s in rows if portal_reaches(s, membership)]
    else:
        reach = crm_perms.company_queryset_for(request, Company.objects.filter(
            deleted_at__isnull=True)).values("pk")
        rows = rows.filter(company_id__in=reach) | rows.filter(company__is_practice=True)
        if company is not None:
            rows = rows.filter(company=company)
        if status in Sop.Status.values:
            rows = rows.filter(status=status)
        elif status != "all":
            rows = rows.exclude(status=Sop.Status.ARCHIVED)
        if category:
            rows = rows.filter(category__iexact=category)
        if q:
            rows = rows.filter(title__icontains=q) | rows.filter(purpose__icontains=q) \
                | rows.filter(company__name__icontains=q)
        found = list(rows.distinct())
    out = []
    for sop in found:
        row = summary(sop, SopAccess(request, sop.company))
        if membership.role in CLIENT_ROLES:
            # The person's own state, so the portal's list needs no second call.
            from .access import in_audience

            mine = SopAck.objects.filter(sop=sop, membership=membership).order_by(
                "-acknowledged_at").first()
            row["mine"] = {"asked": in_audience(sop, membership),
                           "read": has_read(sop, membership),
                           "read_at": mine.acknowledged_at.isoformat() if mine else None}
        out.append(row)
    return out


def categories(request) -> list[str]:
    return sorted({s["category"] for s in list_for(request, status="all") if s["category"]},
                  key=str.lower)


def map_svg(text, title=""):
    if not (text or "").strip():
        return None
    try:
        return flow.svg(text, title=title or "Process map")
    except flow.FlowError:
        return None


def full(sop, access) -> dict:
    """The practice's whole view: the working copy, its versions, its readers,
    the suggestions, and the choices the editor needs."""
    from apps.scorecard.models import Kpi
    from apps.work.models import ClientTeam

    out = summary(sop, access)
    last = latest(sop)
    shape = template(sop.tenant_id)
    out.update({
        "layout": shape["layout"],
        "number": sop.number, "number_by_hand": sop.number_by_hand,
        "effective_date": sop.effective_date.isoformat() if sop.effective_date else None,
        "review_months": sop.review_months, "review_label": review_label(sop.review_months),
        "definitions": sop.definitions, "related": related_rows(sop, sop.related, staff=True),
        "training": sop.training, "metrics": sop.metrics,
        "training_assets": training_rows(sop),
        "revisions": revisions(sop),
        "brain_dump": str(sop.brainstorms.filter(archived_at__isnull=True)
                          .values_list("pk", flat=True).first() or "") or None,
        "purpose": sop.purpose, "applies_when": sop.applies_when, "roles": sop.roles,
        "steps": sop.steps, "sections": sop.sections, "process_map": sop.process_map,
        "map_svg": map_svg(sop.process_map, sop.title),
        "owner_id": str(sop.owner_id) if sop.owner_id else None,
        "audience": sop.audience,
        "teams": [str(t) for t in sop.audience_teams.values_list("team_id", flat=True)],
        "people": [str(p) for p in sop.audience_people.values_list("membership_id", flat=True)],
        "kpis": [{"id": str(link.kpi_id), "name": link.kpi.name}
                 for link in sop.kpi_links.select_related("kpi")],
        "attachments": [{"id": str(a.pk), "name": a.name, "kind": a.kind,
                         "url": f"/api/sops/{sop.pk}/attachments/{a.pk}/"}
                        for a in sop.attachments.all()],
        "versions": [{"number": v.number, "change_note": v.change_note, "minor": v.minor,
                      "published_at": v.published_at.isoformat(),
                      "published_by": _name(v.published_by),
                      "read_by": v.read_by.isoformat() if v.read_by else None}
                     for v in sop.versions.select_related("published_by")],
        "unpublished_changes": unpublished_changes(sop) if sop.version else True,
        "reads": reads(sop) if access.sees_reads else None,
        "comments": [{"id": str(c.pk), "text": c.text, "by": _name(c.author),
                      "at": c.created_at.isoformat(), "version": c.version_number,
                      "resolved": c.resolved_at is not None}
                     for c in sop.comments.select_related("author")[:50]],
        "brainstorms": [{"id": str(b.pk), "title": b.title,
                         "updated_at": b.updated_at.isoformat()}
                        for b in sop.brainstorms.filter(archived_at__isnull=True)[:10]],
        "may": {**access.describe(),
                "publish": access.publishes and sop.status != Sop.Status.ARCHIVED,
                "edit": access.drafts and sop.status != Sop.Status.ARCHIVED},
        "hints": shape["hints"],
        "last_version": last.number if last else 0,
    })
    if access.drafts:
        out["choices"] = {
            "owners": owner_choices(sop.company),
            "teams": [] if sop.company.is_practice else [
                {"id": str(t.pk), "name": t.name} for t in ClientTeam.objects.filter(
                    client_company=sop.company, archived_at__isnull=True)],
            "people": [{"id": str(m.pk), "name": _name(m.user)}
                       for m in _company_people(sop.company)],
            "kpis": [{"id": str(k.pk), "name": k.name} for k in Kpi.objects.filter(
                scorecard__company=sop.company, archived_at__isnull=True).order_by("name")],
            "documents": _document_choices(sop.company),
            "sops": [{"id": str(o.pk), "title": o.title, "number": o.number}
                     for o in Sop.objects.filter(company=sop.company).exclude(pk=sop.pk)
                     .exclude(status=Sop.Status.ARCHIVED).order_by("number", "title")],
        }
    return out


def _company_people(company):
    from apps.tenancy.models import Membership

    if company.is_practice:
        return []
    return sorted(Membership.all_objects.filter(
        tenant_id=company.tenant_id, client_company_id=company.pk, role__in=CLIENT_ROLES,
        revoked_at__isnull=True).select_related("user"),
        key=lambda m: _name(m.user).lower())


def portal_view(sop, membership, access) -> dict:
    """What someone in the audience reads: the latest published version, and
    whether they've read it."""
    version = latest(sop)
    snap = version.snapshot
    read = has_read(sop, membership)
    mine = SopAck.objects.filter(sop=sop, membership=membership).order_by(
        "-acknowledged_at").first()
    from .access import in_audience

    snap = {**SNAPSHOT_EMPTY, **(snap or {})}
    out = {"id": str(sop.pk), "title": snap["title"], "version": version.number,
           "published_at": version.published_at.isoformat(), "change_note": version.change_note,
           "minor": version.minor, "layout": layout_of(sop.tenant_id),
           "number": snap["number"], "effective_date": snap["effective_date"],
           "review_months": snap["review_months"],
           "review_label": review_label(snap["review_months"]),
           "purpose": snap["purpose"], "applies_when": snap["applies_when"],
           "definitions": snap["definitions"], "roles": snap["roles"],
           "steps": snap["steps"], "sections": snap["sections"], "owner": snap["owner"],
           "related": related_rows(sop, snap["related"], staff=False, membership=membership),
           "training": snap["training"], "metrics": snap["metrics"],
           "training_assets": training_rows(sop), "revisions": revisions(sop),
           "category": snap["category"], "review_date": snap["review_date"],
           "kpis": snap["kpis"], "map_svg": map_svg(snap["process_map"], snap["title"]),
           "attachments": [{**a, "url": f"/api/sops/{sop.pk}/attachments/{a['id']}/"}
                           for a in snap["attachments"]],
           "asked": in_audience(sop, membership),
           "read": read, "read_at": mine.acknowledged_at.isoformat() if mine else None,
           "read_version": mine.version.number if mine else None,
           "read_by": (_asking(sop) or version).read_by.isoformat()
           if (_asking(sop) or version).read_by else None,
           "may": access.describe()}
    if access.sees_reads:
        out["reads"] = reads(sop)
    return out
