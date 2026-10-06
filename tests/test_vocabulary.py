"""P1 vocabulary (owner, 2026-10-02): a tenant is a "Practice" and roles have
names, wherever a person reads them. Codes stay in code and data.

These guards keep it that way: they fail the moment a message a person can
read says "VA", "FCC" or "tenant" again.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from apps.tenancy.models import Role
from apps.tenancy.roles import ROLE_LABEL, UNKNOWN_ROLE, role_label

ROOT = pathlib.Path(__file__).resolve().parent.parent
FORBIDDEN = re.compile(r"\b(FF|CF|VA|FCC|ECC)\b|tenant|founder fractional", re.I)

#: Text no person reads: internal invariants raised as programming errors, and
#: operator-facing management commands.
INTERNAL = {
    "apps/tenancy/context.py",
    "apps/tenancy/managers.py",
}
INTERNAL_MESSAGES = {"Cannot merge contacts across tenants."}


def _docstrings(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                out.add(id(first.value))
    return out


def test_no_message_a_person_reads_names_a_role_code_or_tenant():
    found = []
    for path in sorted((ROOT / "apps").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if "/migrations/" in rel or "/management/commands/" in rel or rel in INTERNAL:
            continue
        tree = ast.parse(path.read_text())
        docs = _docstrings(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            text = node.value
            # A bare code or key ("FF", "tenant_id") is logic, not a sentence.
            if id(node) in docs or " " not in text.strip() or text in INTERNAL_MESSAGES:
                continue
            if FORBIDDEN.search(text):
                found.append(f"{rel}:{node.lineno}: {text[:80]!r}")
    assert not found, "Person-readable text with a role code or 'tenant':\n" + "\n".join(found)


def test_the_role_choices_are_the_names():
    assert dict(Role.choices) == ROLE_LABEL
    assert role_label("FF") == "Practice owner"
    assert role_label("ZZ") == role_label(None) == UNKNOWN_ROLE


def test_the_frontend_uses_the_same_names():
    source = (ROOT / "frontend/src/lib/roles.ts").read_text()
    block = re.search(r"ROLE_LABEL[^{]*\{(.*?)\};", source, re.S).group(1)
    frontend = dict(re.findall(r'(\w+):\s*"([^"]+)"', block))
    assert frontend == ROLE_LABEL
    assert f'UNKNOWN_ROLE = "{UNKNOWN_ROLE}"' in source


def test_me_and_the_staff_list_carry_the_name(api, ff):
    me = api.as_(ff).get("/api/me").json()
    assert me["role"] == "FF" and me["role_label"] == "Practice owner"
    staff = api.as_(ff).get("/api/staff/").json()
    assert {m["role_label"] for m in staff} >= {"Practice owner"}


@pytest.mark.django_db
def test_the_practices_own_people_are_its_team_not_its_staff(seeded_tenant, ff, api):
    """Beta feedback, 2026-10-05: "staff" read as the client's staff, so what a
    practice owner reads says "team". The address /staff and the code keep
    their names."""
    import json

    from apps.tenancy import getting_started, services
    from apps.tenancy.models import Role

    labels = [item["label"] for item in getting_started.items(seeded_tenant)]
    assert "Invite your team" in labels
    assert not [label for label in labels if "staff" in label.lower()]
    assert next(i for i in getting_started.items(seeded_tenant)
                if i["label"] == "Invite your team")["to"] == "/staff"

    for call in (
        lambda: services.invite_member(tenant=seeded_tenant, email="x@example.invalid",
                                       role=Role.FCC, actor=ff.user),
        lambda: services.change_role(ff, Role.ECC, actor=ff.user),
    ):
        with pytest.raises(services.StaffActionNotPermitted) as refused:
            call()
        assert "team" in str(refused.value) and "staff" not in str(refused.value).lower()

    # The same refusal, as the Team screen receives it.
    response = api.as_(ff).post("/api/staff/", json.dumps(
        {"email": "y@example.invalid", "role": "FCC"}), content_type="application/json")
    assert "staff" not in response.content.decode().lower()

