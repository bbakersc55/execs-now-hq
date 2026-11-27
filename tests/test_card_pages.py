"""Script controls on the card pages (P16, docs/p16_card_page_scripts.md):
the policy every app page is served with, the browsers' violation reports,
the daily change and tamper check, approving, the report-only switch, and the
platform owner told."""

from __future__ import annotations

import io
import json
from datetime import UTC, timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.cardpages import alerts, check, policy, reports, tasks
from apps.cardpages.models import Baseline, Check, Setting, Violation
from apps.crm.models import OutboxMessage
from apps.notify.models import Notice

from .conftest import _member

pytestmark = pytest.mark.django_db

SHELL = ('<!doctype html><html lang="en"><head><meta charset="UTF-8" /><title>Portal</title>'
         '<link rel="icon" href="/api/branding/mark" />'
         '<script type="module" crossorigin integrity="sha384-abc" '
         'src="/static/assets/index-AAAA.js"></script></head><body><div id="root"></div>'
         '</body></html>')
CARD = ("script-src 'self' 'report-sample'; frame-src 'self' blob: https://secure.nmi.com; "
        "worker-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
        "report-uri http://testserver/csp-report; report-to card-pages")
COLLECT = "https://secure.vaultixpay.com/token/Collect.js"


@pytest.fixture
def shell(settings, monkeypatch):
    """The app's pages served as in production: the built page, not the
    laptop's dev server."""
    from config import spa

    settings.APP_ROOT_URL = "/"
    monkeypatch.setattr(spa, "_index", lambda: SHELL)


@pytest.fixture
def platform_owner(seeded_tenant, monkeypatch):
    monkeypatch.setattr("apps.crm.services.outbox._deliver", lambda m, **kw: None)
    owner = _member(seeded_tenant, "FF")
    owner.user.is_platform_owner = True
    owner.user.save()
    return owner


def told(owner) -> tuple[list, list]:
    notices = list(Notice.all_objects.filter(recipient=owner.user, source_type="card_pages"))
    mail = list(OutboxMessage.all_objects.filter(producer="card_page_alert",
                                                 to_address=owner.user.email))
    return notices, mail


# ------------------------------------------------------------ the policy

def test_every_app_page_has_the_card_policy_and_the_bank_pages_the_bank_policy(client, shell):
    for path in ("/", "/invoices", "/pay/a-pay-link-token-of-some-length",
                 "/settings/billing", "/contacts/123", "/finance", "/finance/personal"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r["Content-Security-Policy"] == CARD, path
        assert "Content-Security-Policy-Report-Only" not in r
        assert r["Reporting-Endpoints"] == 'card-pages="http://testserver/csp-report"'
        assert '<meta name="enhq-page-policy" content="card" />' in r.content.decode()
        assert "cdn.plaid.com" not in r["Content-Security-Policy"]
    for path in ("/finance/import", "/finance/personal/import/", "/settings/finance"):
        r = client.get(path)
        csp = r["Content-Security-Policy"]
        assert csp.startswith("script-src 'self' 'report-sample' "
                              "https://cdn.plaid.com/link/v2/stable/link-initialize.js;"), path
        assert "frame-src 'self' blob: https://secure.nmi.com https://cdn.plaid.com;" in csp
        assert '<meta name="enhq-page-policy" content="bank" />' in r.content.decode()


def test_the_gateways_collect_js_is_allowed_only_where_settings_use_it(client, shell, settings):
    settings.NMI_API_HOST = "secure.vaultixpay.com"
    csp = client.get("/invoices")["Content-Security-Policy"]
    assert f"script-src 'self' 'report-sample' {COLLECT};" in csp
    assert "frame-src 'self' blob: https://secure.nmi.com https://secure.vaultixpay.com;" in csp
    # Whole hosts are never allowed for scripts: only Collect.js's own address.
    assert "script-src 'self' 'report-sample' https://secure.vaultixpay.com;" not in csp
    settings.NMI_SANDBOX_CARD_FORM_HOST = "secure.nmi.com"
    assert policy.gateway_scripts() == [COLLECT, "https://secure.nmi.com/token/Collect.js"]


def test_the_laptops_dev_server_redirect_is_left_alone(client, settings):
    settings.APP_ROOT_URL = "http://localhost:5200/"
    r = client.get("/invoices")
    assert r.status_code == 302 and "Content-Security-Policy" not in r


def test_the_switch_to_report_only_and_back(client, shell):
    out = io.StringIO()
    call_command("card_pages", "mode", "report-only", "--note", "a payer was blocked",
                 "--by", "Bryan", stdout=out)
    assert "report only" in out.getvalue()
    r = client.get("/pay/a-pay-link-token-of-some-length")
    assert "Content-Security-Policy" not in r
    assert r["Content-Security-Policy-Report-Only"] == CARD
    row = Setting.objects.get(pk=1)
    assert (row.mode, row.changed_by, row.note) == ("report-only", "Bryan", "a payer was blocked")
    call_command("card_pages", "mode", "enforce", stdout=io.StringIO())
    assert client.get("/invoices")["Content-Security-Policy"] == CARD
    with pytest.raises(Exception):
        call_command("card_pages", "mode", "off", stdout=io.StringIO())


# ------------------------------------------------------------ browsers' reports

def report_uri_body(**over):
    body = {"document-uri": "https://app.example.test/pay/AbCdEfGhIjKlMnOpQrStUv?x=1",
            "effective-directive": "script-src-elem", "violated-directive": "script-src-elem",
            "blocked-uri": "https://evil.example.test/skim.js?card=1",
            "source-file": "https://app.example.test/static/assets/index-AAAA.js",
            "line-number": 12, "disposition": "enforce", "script-sample": "",
            "original-policy": CARD, **over}
    return json.dumps({"csp-report": body})


def test_a_new_kind_of_violation_is_kept_masked_counted_and_alerts(client, platform_owner):
    r = client.post("/csp-report", report_uri_body(), content_type="application/csp-report",
                    HTTP_USER_AGENT="Chrome/131")
    assert r.status_code == 204
    v = Violation.objects.get()
    assert v.document == "/pay/:token"                      # no token, no query
    assert v.blocked == "https://evil.example.test/skim.js"  # no query
    assert v.source == "https://app.example.test/static/assets/index-AAAA.js"
    assert (v.directive, v.line, v.disposition, v.policy) == ("script-src-elem", 12, "enforce",
                                                               "card")
    assert v.user_agent == "Chrome/131" and not v.noise and v.alerted_at is not None
    notices, mail = told(platform_owner)
    assert len(notices) == 1 and len(mail) == 1
    assert "blocked https://evil.example.test/skim.js" in notices[0].text
    assert notices[0].title == "A card page blocked a script"
    # The same kind again: counted, not told again.
    client.post("/csp-report", report_uri_body(), content_type="application/csp-report")
    assert Violation.objects.get().count == 2 and len(told(platform_owner)[0]) == 1


def test_the_reporting_apis_shape_is_read_too(client, platform_owner):
    body = [{"type": "csp-violation", "url": "https://app.example.test/invoices",
             "user_agent": "Firefox", "body": {
                 "documentURL": "https://app.example.test/invoices",
                 "effectiveDirective": "script-src-elem",
                 "blockedURL": "https://cdn.plaid.com/link/v2/stable/link-initialize.js",
                 "disposition": "report", "originalPolicy": CARD}},
            {"type": "deprecation", "body": {}}]
    r = client.post("/csp-report", json.dumps(body), content_type="application/reports+json")
    assert r.status_code == 204
    v = Violation.objects.get()
    assert (v.document, v.disposition, v.user_agent) == ("/invoices", "report", "Firefox")
    assert told(platform_owner)[0][0].title == "A card page reported a script"


def test_browser_extensions_are_kept_but_never_alert(client, platform_owner):
    client.post("/csp-report", report_uri_body(**{"blocked-uri": "chrome-extension"}),
                content_type="application/csp-report")
    client.post("/csp-report", report_uri_body(**{
        "blocked-uri": "inline", "source-file": "chrome-extension://abc/content.js"}),
        content_type="application/csp-report")
    assert Violation.objects.filter(noise=True).count() == 2
    assert told(platform_owner) == ([], [])


def test_collect_js_asking_for_apples_script_is_expected_and_never_alerts(client,
                                                                         platform_owner):
    client.post("/csp-report", report_uri_body(**{
        "blocked-uri": "https://applepay.cdn-apple.com/jsapi/1.latest/apple-pay-sdk.js",
        "source-file": COLLECT}), content_type="application/csp-report")
    v = Violation.objects.get()
    assert v.noise and v.alerted_at is None and told(platform_owner) == ([], [])
    # The same script asked for by anything else is not expected.
    client.post("/csp-report", report_uri_body(**{
        "blocked-uri": "https://applepay.cdn-apple.com/jsapi/1.latest/apple-pay-sdk.js"}),
        content_type="application/csp-report")
    assert len(told(platform_owner)[0]) == 1


def test_at_most_twenty_alerts_a_day(client, platform_owner):
    for n in range(25):
        client.post("/csp-report", report_uri_body(**{
            "blocked-uri": f"https://evil{n}.example.test/x.js"}),
            content_type="application/csp-report")
    assert Violation.objects.count() == 25
    assert Violation.objects.filter(alerted_at__isnull=False).count() == reports.MOST_A_DAY
    assert len(told(platform_owner)[0]) == reports.MOST_A_DAY


def test_what_the_endpoint_refuses(client):
    assert client.get("/csp-report").status_code == 405
    big = json.dumps({"csp-report": {"blocked-uri": "x" * 20000}})
    assert client.post("/csp-report", big, content_type="application/csp-report").status_code \
        == 413
    assert client.post("/csp-report", "not json", content_type="application/csp-report") \
        .status_code == 204
    assert not Violation.objects.exists()


def test_masking():
    assert reports.masked("https://h.test/pay/AbCdEfGhIjKlMnOpQrStUv/x?y=1#z") == \
        "https://h.test/pay/:token/x"
    assert reports.masked("https://h.test/invoices/6f1c2f0e-3b7a-4c55-9a51-1b2f1f6a9d10") == \
        "https://h.test/invoices/:id"
    assert reports.masked("data:text/javascript,alert(1)") == "data:"
    assert reports.masked("inline") == "inline" and reports.masked("eval") == "eval"


# ------------------------------------------------------------ the daily check

class FakeSite:
    """What a browser gets from the server and the gateway."""

    def __init__(self, csp=CARD):
        self.csp = csp
        self.files = {
            "https://app.example.test/static/assets/index-AAAA.js":
                b'import("./nmi-pay-BBBB.js");console.log("app")',
            "https://app.example.test/static/assets/nmi-pay-BBBB.js":
                b'const m=__vite__mapDeps(["assets/part-CCCC.js"]);',
            "https://app.example.test/static/assets/part-CCCC.js": b"part",
            COLLECT: b"collect v1",
        }
        self.calls = []

    def __call__(self, url, *, accept):
        self.calls.append(url)
        if url in self.files:
            return 200, {"content-type": "text/javascript"}, self.files[url]
        if url.startswith("https://app.example.test/"):
            return 200, {"content-security-policy": self.csp,
                         "x-frame-options": "DENY"}, SHELL.encode()
        return 404, {}, b""


@pytest.fixture
def site(settings):
    settings.NMI_API_HOST = "secure.vaultixpay.com"
    settings.PUBLIC_BASE_URL = "https://app.example.test"
    return FakeSite()


def test_it_reads_every_page_and_every_script_with_its_hash(site):
    state = check.observe("https://app.example.test", fetcher=site)
    assert set(state["pages"]) == set(check.PAGES)
    page = state["pages"]["/invoices"]
    assert page["scripts"] == ["https://app.example.test/static/assets/index-AAAA.js"]
    assert page["integrity"] == {"https://app.example.test/static/assets/index-AAAA.js":
                                 "sha384-abc"}
    assert page["headers"]["content-security-policy"] == CARD
    assert set(state["scripts"]) == set(site.files)      # imports followed, Collect.js too
    assert state["scripts"][COLLECT]["ours"] is False


def test_nothing_approved_alerts_then_approve_then_quiet(site, platform_owner):
    first = check.run(fetcher=site)
    assert first.outcome == Check.Outcome.NO_BASELINE and first.alerted
    assert told(platform_owner)[0][0].title == "The card pages have no approved state"
    row, lines = check.approve(note="Release 51", by="Bryan", fetcher=site)
    assert lines == ["(the first approval)"] and row.approved_by == "Bryan"
    same = check.run(fetcher=site)
    assert same.outcome == Check.Outcome.SAME and not same.alerted
    assert len(told(platform_owner)[0]) == 1


def test_a_changed_script_or_header_alerts_once_then_weekly(site, platform_owner):
    check.approve(note="Release 51", by="Bryan", fetcher=site)
    site.files[COLLECT] = b"collect v2, changed by the gateway"
    changed = check.run(fetcher=site)
    assert changed.outcome == Check.Outcome.CHANGED and changed.alerted
    assert any(line.startswith(f"script changed: {COLLECT}") for line in changed.differences)
    notices, mail = told(platform_owner)
    assert notices[-1].title == "The card pages changed" and len(mail) == 1
    # The same difference tomorrow: not again; a week on, again.
    again = check.run(fetcher=site)
    assert again.outcome == Check.Outcome.CHANGED and not again.alerted
    Check.objects.filter(pk=changed.pk).update(ran_at=timezone.now() - timedelta(days=8))
    Check.objects.filter(pk=again.pk).update(ran_at=timezone.now() - timedelta(days=8))
    later = check.run(fetcher=site)
    assert later.alerted
    # A weaker policy is a difference too.
    site.files[COLLECT] = b"collect v1"
    check.approve(note="gateway's new Collect.js reviewed", by="Bryan", fetcher=site)
    site.csp = CARD.replace("object-src 'none'; ", "")
    weaker = check.run(fetcher=site)
    assert any("header content-security-policy is now" in line for line in weaker.differences)
    assert weaker.alerted                                   # a new finding: told at once


def test_a_deploy_not_yet_approved_is_told_apart_from_a_tampered_file(site, settings, tmp_path,
                                                                      platform_owner):
    settings.STATIC_ROOT = tmp_path
    (tmp_path / "assets").mkdir()
    check.approve(note="Release 51", by="Bryan", fetcher=site)
    new = b"part, release 52"
    site.files["https://app.example.test/static/assets/part-CCCC.js"] = new
    (tmp_path / "assets" / "part-CCCC.js").write_bytes(new)
    deployed = check.run(fetcher=site)
    assert deployed.differences[-1].startswith("ENHQ's changed scripts are exactly the files")
    (tmp_path / "assets" / "part-CCCC.js").write_bytes(b"what the release built")
    Check.objects.all().delete()
    tampered = check.run(fetcher=site)
    assert tampered.differences[-1].startswith("Some of ENHQ's scripts as served match no file")


def test_a_page_that_cant_be_read_alerts(site, platform_owner):
    def down(url, *, accept):
        raise check.Unreadable(f"{url} could not be read: refused")
    row = check.run(fetcher=down)
    assert row.outcome == Check.Outcome.ERROR and row.alerted
    assert "could not be read" in told(platform_owner)[0][0].text


def test_the_daily_job_runs_in_production_only(settings, monkeypatch):
    ran = []
    monkeypatch.setattr(check, "run", lambda **kw: ran.append(1) or Check(outcome="same"))
    settings.APP_ENVIRONMENT = "demo"
    assert tasks.daily_check() == "skipped" and ran == []
    settings.APP_ENVIRONMENT = "production"
    assert tasks.daily_check() == "same" and ran == [1]


def test_ensure_schedules_registers_the_daily_check_once(seeded_tenant):
    from django_q.models import Schedule

    call_command("ensure_schedules", stdout=io.StringIO())
    call_command("ensure_schedules", stdout=io.StringIO())
    rows = Schedule.objects.filter(name="platform.card_pages_check")
    assert rows.count() == 1
    row = rows.get()
    assert (row.func, row.schedule_type, row.args) == ("apps.cardpages.tasks.daily_check",
                                                       Schedule.DAILY, None)
    assert row.next_run.astimezone(UTC).hour == 13


def test_status_and_approve_commands(site, platform_owner):
    out = io.StringIO()
    call_command("card_pages", "approve", "--note", "Release 51", "--by", "Bryan", stdout=out)
    assert "Approved what https://app.example.test serves now: 4 scripts on 3 pages." in \
        out.getvalue()
    with pytest.raises(Exception):
        call_command("card_pages", "approve", stdout=io.StringIO())       # a note is needed
    status = io.StringIO()
    call_command("card_pages", "status", stdout=status)
    text = status.getvalue()
    assert "Mode: enforce" in text and "by Bryan (Release 51), 4 scripts" in text
    assert Baseline.objects.count() == 1


@pytest.fixture(autouse=True)
def _gateway_fetches_are_the_fake(monkeypatch):
    """The commands read through `check.fetch`: here, never the network."""
    site = FakeSite()
    monkeypatch.setattr(check, "fetch", site)


def test_alerts_without_a_platform_owner_are_logged_not_lost(caplog):
    assert alerts.tell(key="x", title="t", text="nobody to tell") == 0
    assert "nobody new to tell" in caplog.text
