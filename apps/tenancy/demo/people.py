"""People on the demo (2026-11-17, the employee records).

The People Command Center on for Summit, and Acme Fasteners' people as
records: thirteen with managers and departments (the owner, the plant
manager, the floor, quality, shipping and maintenance), each linked to their
portal sign-in where they have one, with pay and personal details (all
fictional; phone numbers in 555-01xx); and around them:

- **Lola Bunny**, offered the next machinist's job: "offer out", her offer
  letter sent and waiting for her signature;
- **Bugs Bunny**, started a week ago: onboarding about half done;
- **Sylvester Pussycat**, leaving: offboarding started, his access list
  (Slack, his email, a phone, a laptop and a key) being revoked, two of
  them done;
- **Ted Lasso**, an associate on Summit's team, HR Generalist for Acme.

Made through People's own services, so the checklists' tasks are in Work and
the offer is a real e-signature document. No Claude, and the seed's mail
goes nowhere.
"""

from __future__ import annotations

from datetime import date, timedelta

from .clock import at, moment

COMPANY = "Acme Fasteners"
#: (first, last, title, department, team, manager's first name, type,
#: started (y, m, d), pay, unit, born (y, m, d)).
STAFF = [
    ("Wiley", "Coyote", "Owner", "Leadership", "Leadership", None, "full_time",
     (2012, 3, 1), "140,000", "year", (1974, 2, 11)),
    ("Marvin", "Martian", "Plant manager", "Operations", "Leadership", "Wiley", "full_time",
     (2016, 6, 13), "96,000", "year", (1980, 12, 2)),
    ("Daffy", "Duckworth", "Purchasing lead", "Operations", "Office", "Wiley", "full_time",
     (2019, 9, 3), "68,000", "year", (1986, 7, 19)),
    ("Elmer", "Fudd", "Header line lead", "Production", "Header line", "Marvin", "full_time",
     (2017, 12, 4), "31.50", "hour", (1983, 5, 30)),
    ("Yosemite", "Sam", "Machinist", "Production", "Header line", "Elmer", "full_time",
     (2020, 2, 17), "27.25", "hour", (1979, 11, 28)),
    ("Foghorn", "Leghorn", "Machinist", "Production", "Header line", "Elmer", "full_time",
     (2021, 8, 9), "26.00", "hour", (1990, 4, 6)),
    ("Pepe", "LePew", "Machinist", "Production", "Header line", "Elmer", "part_time",
     (2023, 1, 23), "24.50", "hour", (1995, 2, 14)),
    ("Gossamer", "Hare", "Maintenance", "Production", "Maintenance", "Marvin", "contractor",
     (2022, 11, 28), "45.00", "hour", (1977, 10, 31)),
    ("Porky", "Pig", "Quality lead", "Quality", "Quality", "Marvin", "full_time",
     (2018, 4, 2), "30.00", "hour", (1984, 8, 22)),
    ("Tweety", "Bird", "Quality inspector", "Quality", "Quality", "Porky", "full_time",
     (2024, 12, 9), "23.75", "hour", (1998, 12, 9)),
    ("Speedy", "Gonzales", "Shipping lead", "Shipping", "Shipping", "Marvin", "full_time",
     (2019, 12, 16), "28.50", "hour", (1988, 1, 5)),
    ("Sylvester", "Pussycat", "Shipping", "Shipping", "Shipping", "Speedy", "full_time",
     (2021, 3, 1), "22.50", "hour", (1987, 6, 1)),
    ("Petunia", "Pig", "Receiving", "Shipping", "Receiving", "Speedy", "part_time",
     (2022, 5, 9), "21.00", "hour", (1993, 9, 17)),
]
HIRE = ("Lola", "Bunny", "Machinist", "Production", "Header line", "Elmer", "full_time",
        "26.50", "hour", "lola.bunny@home.example")
NEW = ("Bugs", "Bunny", "Machinist", "Production", "Header line", "Elmer", "full_time",
       "26.50", "hour")
LEAVING = "Sylvester"
ACCESS = [("system", "Slack", "Acme workspace"), ("email", "sylvester@acmefasteners.example", ""),
          ("phone", "(520) 555-0142", "Shipping desk"), ("equipment", "Laptop", "Dell 5440, tag A-118"),
          ("key", "Loading dock key", "Key 7")]


def _sensitive(first, last, pay, unit, effective, born):
    return {"pay_rate": pay, "pay_unit": unit, "pay_effective_on": effective.isoformat(),
            "home_address": f"{100 + len(first) * 7} {last} Lane, Tucson, AZ 857{len(last):02d}",
            "date_of_birth": born.isoformat() if born else "",
            "personal_phone": f"(520) 555-01{(len(first) * 13 + len(last)) % 100:02d}",
            "personal_email": f"{first.lower()}.{last.lower()}@home.example",
            "emergency_contact": f"A family member, (520) 555-01{len(first + last) % 100:02d}"}


def people(world) -> dict:
    from apps.centers.models import PracticeCenter
    from apps.crm.services import outbox
    from apps.people import checklists, hiring
    from apps.people import services as S
    from apps.people.models import HRGrant, PersonRecord
    from apps.tenancy.models import Membership

    tenant, owner, today = world.tenant, world.owner, world.today
    company = world.companies.get(COMPANY)
    if company is None:
        return {}
    with at(moment(today - timedelta(days=45), 9, 0)):
        PracticeCenter.all_objects.update_or_create(
            tenant=tenant, center="people",
            defaults={"enabled_at": moment(today - timedelta(days=45), 9, 0),
                      "enabled_by": owner, "disabled_at": None})
    sign_ins = {(m.contact.first_name, m.contact.last_name): m.user for m in
                Membership.objects.filter(client_company=company, revoked_at__isnull=True,
                                          contact__isnull=False).select_related("contact",
                                                                                "user")}
    records = {}

    def make(first, last, title, department, team, kind, started, pay, unit, born, status,
             email_domain=True):
        record = PersonRecord(
            tenant=tenant, client_company=company, first_name=first, last_name=last,
            title=title, department=department, team=team, employment_type=kind,
            work_email=f"{first.lower()}@acmefasteners.example" if email_domain else "",
            work_phone=f"(520) 555-01{len(first + title) % 100:02d}", work_state="AZ",
            start_date=started, status=status, user=sign_ins.get((first, last)),
            is_placeholder=False, created_by=owner)
        S.write_sensitive(record, _sensitive(first, last, pay, unit, started, born))
        record.save()
        records[first] = record
        return record

    with at(moment(today - timedelta(days=44), 10, 0)):
        for first, last, title, dept, team, _boss, kind, started, pay, unit, born in STAFF:
            make(first, last, title, dept, team, kind, date(*started), pay, unit, date(*born),
                 "active")
        for first, _last, _t, _d, _team, boss, *_rest in STAFF:
            if boss:
                PersonRecord.objects.filter(pk=records[first].pk).update(
                    manager=records[boss])
        for record in records.values():
            record.refresh_from_db()

    # Ted Lasso, HR Generalist for Acme.
    lasso = world.staff.get("lasso")
    if lasso is not None:
        HRGrant.objects.create(tenant=tenant, user=lasso, level="generalist",
                               client_company=company, granted_by=owner)

    # Bugs Bunny, a week in: onboarding about half done.
    first, last, title, dept, team, boss, kind, pay, unit = NEW
    started = today - timedelta(days=7)
    with at(moment(started - timedelta(days=12), 11, 0)):
        bugs = make(first, last, title, dept, team, kind, started, pay, unit, None, "active")
        PersonRecord.objects.filter(pk=bugs.pk).update(manager=records[boss])
        bugs.refresh_from_db()
        onboarding = checklists.start(bugs, "onboarding", actor=owner, anchor_date=started)
    due = [i for i in onboarding.items.order_by("due_date", "position")
           if i.due_date and i.due_date <= today]
    for item in due[: len(due) // 2 or 1]:
        with at(moment(item.due_date, 15, 0)):
            checklists.mark_done(item, actor=owner)

    # Sylvester, leaving in a week: his access list being revoked.
    leaving = records[LEAVING]
    given = date(2021, 3, 1)
    with at(moment(given, 9, 0)):
        for kind, name, detail in ACCESS:
            checklists.save_entry(leaving, {"kind": kind, "name": name, "detail": detail,
                                            "given_on": given.isoformat(),
                                            "given_by_name": "Acme IT"}, actor=owner)
    last_day = today + timedelta(days=7)
    with at(moment(today - timedelta(days=3), 9, 30)):
        offboarding = checklists.start(leaving, "offboarding", actor=owner,
                                       anchor_date=last_day, reason="resignation",
                                       note="Moving to Phoenix. Two weeks' notice given.")
    revokes = list(offboarding.items.filter(access_entry__isnull=False).order_by("position"))
    early = [i for i in offboarding.items.filter(access_entry__isnull=True)
             .order_by("due_date") if i.due_date and i.due_date <= today]
    with at(moment(today - timedelta(days=1), 14, 0)):
        for item in revokes[:2] + early:
            checklists.mark_done(item, actor=owner)

    # Lola Bunny, offered the next machinist's job: waiting for her signature.
    first, last, title, dept, team, boss, kind, pay, unit, email = HIRE
    with at(moment(today - timedelta(days=2), 10, 0)):
        lola = make(first, last, title, dept, team, kind, today + timedelta(days=14), pay,
                    unit, None, "offer_out", email_domain=False)
        PersonRecord.objects.filter(pk=lola.pk).update(manager=records[boss])
        lola.refresh_from_db()
        document = hiring.make_offer(lola, actor=owner, role="FF", email=email)
    with at(moment(today - timedelta(days=2), 10, 20)):
        outbox.approve(document.request_message, actor=owner, role="FF")
    return {"People records": PersonRecord.objects.filter(client_company=company).count(),
            "People offer out": 1, "People onboarding": 1, "People offboarding": 1}
