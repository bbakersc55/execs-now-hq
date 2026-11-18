"""Hiring, and documents to sign (2026-11-17).

An **offer letter** is sent from a new record in "offer out", through the
app's own e-signature: People's offer template (`people_offer_letter`),
merged with the record's title, pay, start date, type, work state and
manager, to the email it is sent to. It goes to the Outbox for approval and
is countersigned as any document is. **When the candidate signs, the record
moves to onboarding and the onboarding checklist starts.**

The signer of any e-signature document is a contact of the company. A
candidate who is not one already becomes one (`PersonRecord.made_contact`):
People's, so it is never in Contacts, search or an AI app. A document People
sends is People's too (`PersonDocument.esign_document`): in Documents only
for an HR Director, in the portal only for the client owner and its signer,
never in an AI app, and it moves nobody on a pipeline.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.people import checklists
from apps.people import services as S
from apps.people.models import Kind, PayUnit, PeopleAccessLog, PersonDocument, Status

OFFER_TEMPLATE = "people_offer_letter"
HANDBOOK_TEMPLATE = "people_handbook_ack"
WAITING = ("sent", "viewed")


def _template(tenant, original):
    from apps.esign import seed
    from apps.esign.models import DocumentTemplate

    seed.seed_tenant(tenant)
    found = DocumentTemplate.all_objects.filter(tenant=tenant, original=original).first()
    if found is None:
        raise S.PeopleRefused("Turn the People Command Center on to send its documents.", 409)
    return found


def signer_for(record, email: str):
    """The contact a document for this person is sent to: theirs, if they
    have a sign-in with a contact at this address; a contact of the company
    with this address; or one made for them, People's."""
    from apps.crm.models import Contact, ContactEmail
    from apps.tenancy.models import Membership

    email = (email or "").strip().lower()
    if "@" not in email:
        raise S.PeopleRefused("Give the email address to send it to.")
    if record.user_id:
        mine = Membership.all_objects.filter(
            tenant_id=record.tenant_id, user_id=record.user_id,
            client_company_id=record.client_company_id, contact__isnull=False).first()
        if mine is not None and (mine.contact.primary_email or "").lower() == email:
            return mine.contact
    if record.made_contact_id and (record.made_contact.primary_email or "").lower() == email:
        return record.made_contact
    known = (ContactEmail.all_objects.filter(tenant_id=record.tenant_id, address__iexact=email,
                                             contact__company_id=record.client_company_id,
                                             contact__deleted_at__isnull=True)
             .select_related("contact").first())
    if known is not None:
        return known.contact
    contact = Contact.all_objects.create(tenant_id=record.tenant_id,
                                         company_id=record.client_company_id,
                                         first_name=record.first_name,
                                         last_name=record.last_name, title=record.title)
    ContactEmail.all_objects.create(tenant_id=record.tenant_id, contact=contact,
                                    address=email, is_primary=True)
    record.made_contact = contact
    record.save(update_fields=["made_contact", "updated_at"])
    return contact


def _pay_words(values) -> str:
    rate = (values.get("pay_rate") or "").strip()
    if not rate:
        return ""
    unit = values.get("pay_unit") or ""
    return f"{rate} {PayUnit(unit).label}" if unit in PayUnit.values else rate


def _send(record, *, actor, kind, template, email, fields, role):
    from apps.esign import services as esign

    if record.client_company_id is None:
        raise S.PeopleRefused("Documents for signature go from a client company's People "
                              "page.")
    signer = signer_for(record, email)
    try:
        document = esign.from_template(record.client_company, template, signer, fields=fields,
                                       actor=actor)
        PersonDocument.all_objects.create(tenant_id=record.tenant_id, person=record, kind=kind,
                                          title=document.title, esign_document=document,
                                          uploaded_by=actor)
        esign.queue_request(document, actor=actor, role=role)
    except esign.DocumentRefused as exc:
        raise S.PeopleRefused(str(exc), exc.status) from None
    return document


def offer_fields(record, values) -> dict:
    return {"JobTitle": record.title, "Pay": _pay_words(values),
            "StartDate": record.start_date.isoformat(),
            "EmploymentType": record.get_employment_type_display(),
            "WorkState": S.STATE_NAMES.get(record.work_state, record.work_state) or "",
            "Manager": record.manager.name if record.manager_id
            else record.client_company.name}


def make_offer(record, *, actor, role, email=""):
    """The offer letter made and queued, its checks passed (`send_offer`)."""
    values = S.read_sensitive(record)
    return _send(record, actor=actor, kind=PersonDocument.Kind.OFFER_LETTER,
                 template=_template(record.tenant, OFFER_TEMPLATE),
                 email=email or values.get("personal_email"),
                 fields=offer_fields(record, values), role=role)


@transaction.atomic
def send_offer(request, access, record, data, *, role):
    """The offer letter, from a record in "offer out": an HR Director's,
    since it carries pay. The pay it carries is logged as exported."""
    from apps.people import access as A

    if access.level != A.DIRECTOR:
        raise S.PeopleRefused("Only an HR Director sends an offer: it carries pay.", 403)
    if record.status != Status.OFFER_OUT:
        raise S.PeopleRefused("An offer goes from a record in \"offer out\".", 409)
    waiting = PersonDocument.all_objects.filter(
        person=record, kind=PersonDocument.Kind.OFFER_LETTER,
        esign_document__state__in=("draft",) + WAITING).exists()
    if waiting:
        raise S.PeopleRefused("An offer is already out for signature. Void it in Documents "
                              "to send another.", 409)
    values = S.read_sensitive(record)
    if not (record.title and record.start_date and _pay_words(values)):
        raise S.PeopleRefused("An offer needs a title, a start date and pay on the record.")
    document = make_offer(record, actor=request.user, role=role, email=data.get("email") or "")
    S.log(request, record, PeopleAccessLog.Action.EXPORT,
          [k for k in ("pay_rate", "pay_unit") if values.get(k)])
    S._audit(record, request.user, "people.offer_sent", document=str(document.pk))
    return document


@transaction.atomic
def send_handbook(request, access, record, data, *, role):
    """The handbook acknowledgment, to the person to sign."""
    from apps.people import access as A

    if access.level not in A.HR_LEVELS:
        raise S.PeopleRefused("Only HR permissions send documents to sign.", 403)
    values = S.read_sensitive(record) if A.sees_in_full(access, record) else {}
    email = data.get("email") or record.work_email or values.get("personal_email")
    document = _send(record, actor=request.user, kind=PersonDocument.Kind.HANDBOOK,
                     template=_template(record.tenant, HANDBOOK_TEMPLATE), email=email,
                     fields={}, role=role)
    S._audit(record, request.user, "people.handbook_sent", document=str(document.pk))
    return document


def to_sign(record) -> list[dict]:
    """The documents waiting for this person's signature."""
    return [{"id": str(d.pk), "title": d.title, "kind_label": d.get_kind_display(),
             "state_label": d.esign_document.get_state_display(),
             "sent_at": d.esign_document.sent_at.isoformat() if d.esign_document.sent_at
             else None}
            for d in PersonDocument.all_objects.filter(
                person=record, esign_document__state__in=WAITING).select_related(
                "esign_document").order_by("-created_at")]


# ------------------------------------------------------------ e-signature's word

def is_peoples(document) -> bool:
    return PersonDocument.all_objects.filter(esign_document_id=document.pk).exists()


def document_event(document, what: str) -> None:
    """From e-signature, in its transaction: "signed" or "complete". A signed
    offer moves its record to onboarding and starts the onboarding
    checklist, as whoever sent the offer."""
    found = (PersonDocument.all_objects.filter(esign_document_id=document.pk)
             .select_related("person").first())
    if found is None:
        return
    record = found.person
    if what == "signed" and found.kind == PersonDocument.Kind.OFFER_LETTER \
            and record.status == Status.OFFER_OUT:
        actor = document.created_by
        checklists.start(record, Kind.ONBOARDING, actor=actor,
                         anchor_date=record.start_date or timezone.localdate())
        S._audit(record, actor, "people.offer_signed", document=str(document.pk))

