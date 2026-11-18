"""The People Command Center's shipped content (2026-11-17, the employee
records): two document templates for e-signature, and the standard items of
the onboarding and offboarding checklists, each in its section (People, IT,
Manager). A company's checklists start as a copy of these; it adds, edits and
reorders its own from there (`apps/people/checklists.py`).

Nothing here asks for, or names a place for, a Social Security number, bank
details, an I-9, medical or leave paperwork, a background check or benefits:
the employee gives those to the payroll provider directly.
"""

from __future__ import annotations

CODE = "people"
#: People has no strategy-session template of its own.
HAS_SESSION_TEMPLATE = False

KPIS: list = []
PLAYBOOKS: dict = {}
EMAILS: dict = {}
TOOLS: list = []
FEEDS: list = []
FEED_NAMES: dict = {}
NOTEBOOK_PROMPTS: list = []
AI_ACTIONS: list = []

#: original key -> (name, title, body), merged as any document template is.
DOCUMENTS = {
    "people_offer_letter": (
        "Offer letter",
        "Offer of employment: {JobTitle}",
        "{Today}\n\n"
        "Dear {FirstName},\n\n"
        "{Company} is pleased to offer you the position of {JobTitle}, reporting to "
        "{Manager}.\n\n"
        "# Start date\n{StartDate}\n\n"
        "# Pay\n{Pay}\n\n"
        "# Employment\n{EmploymentType}, working in {WorkState}. Employment with {Company} "
        "is at will: either of us may end it at any time, with or without notice.\n\n"
        "# Before your first day\n"
        "You will hear from {Company}'s payroll provider directly to set up your pay, tax "
        "forms and benefits. Please give those details to them, not to us.\n\n"
        "# Accepting\n"
        "Sign below to accept this offer. This offer is open for seven days from the date "
        "above.\n\n"
        "{FractionalName}\n{PracticeName}, for {Company}",
    ),
    "people_handbook_ack": (
        "Handbook acknowledgment",
        "Employee handbook acknowledgment",
        "{Today}\n\n"
        "I, {FirstName} {LastName}, have received {Company}'s employee handbook. I "
        "understand it is my responsibility to read it and to follow the policies in it, "
        "and that {Company} may change those policies from time to time.\n\n"
        "Signing below acknowledges that I received the handbook. It is not a contract of "
        "employment.",
    ),
}

#: kind -> [(key, section, title, owner role, days from the start date or last day)].
#: Owner roles: "hr" (whoever starts the checklist), "it" (the IT owner chosen
#: then), "manager" (their manager's sign-in), "employee" (their own sign-in).
CHECKLISTS = {
    "onboarding": [
        ("on_welcome", "people", "Send the welcome email with first-day details", "hr", -5),
        ("on_payroll", "people", "Ask the payroll provider to invite them to set up pay and "
         "tax forms", "hr", -5),
        ("on_handbook", "people", "Send the handbook acknowledgment for signature", "hr", -3),
        ("on_paperwork", "people", "Complete payroll setup with the payroll provider",
         "employee", 0),
        ("on_benefits", "people", "Confirm benefits enrollment is under way with the "
         "provider", "hr", 7),
        ("on_accounts", "it", "Create their email and system accounts", "it", -3),
        ("on_equipment", "it", "Order and set up their laptop and phone", "it", -5),
        ("on_access_list", "it", "Record every system, account and item given on their "
         "access list", "it", 0),
        ("on_keys", "it", "Hand over keys and building access", "it", 0),
        ("on_first_week", "manager", "Plan their first week and introductions", "manager",
         -2),
        ("on_one_on_one", "manager", "Hold the first one-on-one", "manager", 1),
        ("on_goals", "manager", "Set 30-, 60- and 90-day goals", "manager", 7),
        ("on_30_day", "manager", "Hold the 30-day check-in", "manager", 30),
    ],
    "offboarding": [
        ("off_letter", "people", "Confirm the last day in writing", "hr", -10),
        ("off_payroll", "people", "Tell the payroll provider the last day and final pay "
         "(a person does this in payroll; nothing here changes it)", "hr", -5),
        ("off_final_pay", "people", "Check the final-pay deadline for their work state",
         "hr", -5),
        ("off_exit_interview", "people", "Hold the exit interview", "hr", -1),
        ("off_benefits", "people", "Ask the provider to send benefits continuation "
         "information", "hr", 1),
        ("off_equipment", "it", "Collect the laptop, phone and other equipment", "it", 0),
        ("off_forward", "it", "Set email forwarding or an out-of-office reply", "it", 0),
        ("off_handover", "manager", "Plan the handover of their work", "manager", -10),
        ("off_announce", "manager", "Tell the team and clients who takes over", "manager",
         -3),
    ],
}
