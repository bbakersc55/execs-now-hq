"""The gate's dependency audit (scripts/dependency_audit.py,
docs/security_updates.md): what blocks, what passes, the dated allow-list,
and "couldn't check" failing. No network and no database: the advisory
services are replaced by canned answers in OSV's and npm's own shapes."""
import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("dependency_audit", ROOT / "scripts" / "dependency_audit.py")
audit = importlib.util.module_from_spec(spec)
sys.modules["dependency_audit"] = audit
spec.loader.exec_module(audit)

TODAY = dt.date(2026, 11, 27)


def osv_record(id, package, *, severity=None, fixed=("2.0.0",), aliases=()):
    record = {"id": id, "summary": f"{id} in {package}", "aliases": list(aliases),
              "affected": [{"package": {"ecosystem": "PyPI", "name": package},
                            "ranges": [{"type": "ECOSYSTEM",
                                        "events": [{"introduced": "0"}]
                                        + [{"fixed": f} for f in fixed]}]}]}
    if severity:
        record["database_specific"] = {"severity": severity}
    return record


def fake_osv(records_by_package, extra=None):
    """A fetcher answering querybatch and vulns/<id> like OSV."""
    by_id = {r["id"]: r for rs in records_by_package.values() for r in rs}
    by_id.update(extra or {})

    def fetch(url, body=None):
        if url.endswith("/querybatch"):
            return {"results": [
                {"vulns": [{"id": r["id"]} for r in records_by_package.get(q["package"]["name"], [])]}
                for q in body["queries"]]}
        return by_id[url.rsplit("/", 1)[-1]]
    return fetch


def test_pins_reads_every_exact_pin_and_skips_the_rest():
    text = "# a comment\n-r requirements.txt\nDjango==5.2.19\npsycopg[binary]==3.3.5\n" \
           "typing_extensions==4.16.0  # why\nanthropic>=1\n\n"
    assert audit.pins([text]) == {"django": "5.2.19", "typing-extensions": "4.16.0"}


def test_a_critical_or_high_advisory_with_a_fix_blocks():
    fetch = fake_osv({"pillow": [osv_record("GHSA-aaaa", "pillow", severity="CRITICAL")],
                      "pypdf": [osv_record("GHSA-bbbb", "pypdf", severity="HIGH")]})
    found = audit.python_advisories({"pillow": "12.3.0", "pypdf": "6.20.1"}, fetch)
    blocking, allowed, info = audit.verdict(found, [])
    assert [a.id for a in blocking] == ["GHSA-aaaa", "GHSA-bbbb"] and not allowed and not info
    assert blocking[0].fixed == ["2.0.0"]


@pytest.mark.parametrize("severity,fixed,blocks", [
    ("MODERATE", ("2.0.0",), False),     # below high: noted only
    ("LOW", ("2.0.0",), False),
    ("HIGH", (), False),                 # no fixed version yet: noted only
    ("CRITICAL", (), False),
    (None, ("2.0.0",), True),            # no rating anywhere: counts as high
])
def test_what_blocks_and_what_is_only_noted(severity, fixed, blocks):
    fetch = fake_osv({"pkg": [osv_record("PYSEC-1", "pkg", severity=severity, fixed=fixed)]})
    found = audit.python_advisories({"pkg": "1.0"}, fetch)
    blocking, _, info = audit.verdict(found, [])
    assert bool(blocking) is blocks and bool(info) is not blocks


def test_the_rating_comes_from_the_github_alias_when_the_record_has_none():
    pysec = osv_record("PYSEC-2", "pkg", aliases=["GHSA-cccc"])
    ghsa = {"id": "GHSA-cccc", "database_specific": {"severity": "HIGH"}}
    found = audit.python_advisories({"pkg": "1.0"}, fake_osv({"pkg": [pysec]}, {"GHSA-cccc": ghsa}))
    assert found[0].severity == "HIGH"


def test_the_same_flaw_under_two_ids_is_listed_once():
    pysec = osv_record("PYSEC-3", "pkg", severity="HIGH", aliases=["GHSA-dddd"])
    ghsa = osv_record("GHSA-dddd", "pkg", severity="CRITICAL", aliases=["PYSEC-3"])
    found = audit.python_advisories({"pkg": "1.0"}, fake_osv({"pkg": [pysec, ghsa]}))
    assert [(a.id, a.severity) for a in found] == [("GHSA-dddd", "CRITICAL")]


def test_a_fix_for_another_package_in_the_same_record_is_not_ours():
    record = osv_record("GHSA-eeee", "other", severity="HIGH")
    record["id"] = "GHSA-eeee"
    found = audit.python_advisories({"pkg": "1.0"}, fake_osv({"pkg": [record]}))
    assert found[0].fixed == [] and not found[0].blocking


ALLOW = """
[[allow]]
id = "CVE-2026-1"
package = "pkg"
reason = "The fix needs a code change, being made on dev."
added = 2026-11-20
until = 2026-12-15
"""


def test_an_allow_list_entry_lets_one_advisory_pass_by_any_of_its_names():
    allowlist = audit.load_allowlist(ALLOW, TODAY)
    record = osv_record("GHSA-ffff", "pkg", severity="HIGH", aliases=["CVE-2026-1"])
    found = audit.python_advisories({"pkg": "1.0"}, fake_osv({"pkg": [record]}))
    blocking, allowed, _ = audit.verdict(found, allowlist)
    assert not blocking and allowed[0][1].reason.startswith("The fix needs")


@pytest.mark.parametrize("text,problem", [
    (ALLOW.replace("2026-12-15", "2026-11-26"), "expired on 2026-11-26"),
    (ALLOW.replace("2026-12-15", "2027-01-15"), "lasts 56 days; the most is 30"),
    (ALLOW.replace('reason = "The fix needs a code change, being made on dev."', 'reason = ""'),
     "missing reason"),
    (ALLOW.replace("until = 2026-12-15\n", ""), "missing until"),
    (ALLOW.replace("2026-12-15", "2026-11-01"), "until is before added"),
    (ALLOW.replace("until = 2026-12-15", 'until = "soon"'), "must be dates"),
])
def test_a_bad_or_expired_entry_fails_the_audit(text, problem):
    with pytest.raises(audit.AuditError, match=problem):
        audit.load_allowlist(text, TODAY)


def test_the_shipped_allow_list_is_well_formed():
    """Its dates are the audit's business on the day; here only the shape."""
    text = (ROOT / "scripts" / "audit_allowlist.toml").read_text()
    entries = audit.tomllib.loads(text).get("allow", [])
    earliest = min((e["added"] for e in entries), default=TODAY)
    assert len(audit.load_allowlist(text, earliest)) == len(entries)


NPM = {"vulnerabilities": {
    "react-dom": {"severity": "high", "fixAvailable": True, "range": "<19.0.1",
                  "via": [{"source": 1, "title": "XSS", "severity": "high", "range": "<19.0.1",
                           "url": "https://github.com/advisories/GHSA-gggg-0000-0000"}]},
    "scheduler": {"severity": "high", "fixAvailable": True, "via": ["react-dom"]},
    "lucide-react": {"severity": "critical", "fixAvailable": False,
                     "via": [{"source": 2, "title": "No fix yet", "severity": "critical",
                              "url": "https://github.com/advisories/GHSA-hhhh-0000-0000"}]},
    "router": {"severity": "moderate",
               "fixAvailable": {"name": "react-router-dom", "version": "8.0.0", "isSemVerMajor": True},
               "via": [{"source": 3, "title": "Open redirect", "severity": "moderate",
                        "url": "https://github.com/advisories/GHSA-iiii-0000-0000"}]},
}}


def test_npm_audit_high_with_a_fix_blocks_and_a_package_carrying_it_is_not_counted_twice():
    found = audit.frontend_advisories(NPM)
    blocking, _, info = audit.verdict(found, [])
    assert [(a.package, a.id) for a in blocking] == [("react-dom", "GHSA-gggg-0000-0000")]
    assert {a.package for a in info} == {"lucide-react", "router"}
    assert next(a for a in info if a.package == "router").fixed == [
        "react-router-dom@8.0.0 (a major version)"]


def test_an_unreachable_service_fails_the_audit(monkeypatch, capsys):
    def offline(*args, **kwargs):
        raise audit.AuditError("couldn't reach https://api.osv.dev (URLError)")
    monkeypatch.setattr(audit, "python_advisories", offline)
    assert audit.main(TODAY) == 2
    assert "couldn't complete" in capsys.readouterr().err


def test_main_refuses_on_a_blocking_advisory_and_passes_when_clean(monkeypatch, capsys):
    bad = [audit.Advisory("python", "pkg", "1.0", "GHSA-jjjj", "HIGH", ["2.0"], "bad")]
    monkeypatch.setattr(audit, "python_advisories", lambda pinned: bad)
    monkeypatch.setattr(audit, "npm_audit_json", lambda: {"vulnerabilities": {}})
    assert audit.main(TODAY) == 1
    assert "BLOCKING" in capsys.readouterr().out
    monkeypatch.setattr(audit, "python_advisories", lambda pinned: [])
    assert audit.main(TODAY) == 0
    assert "0 blocking" in capsys.readouterr().out
