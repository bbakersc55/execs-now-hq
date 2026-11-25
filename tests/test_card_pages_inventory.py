"""The card pages' script inventory (P16; PCI DSS 6.4.3).

docs/card_page_scripts.md lists every script source a card page may load and
why. This fails if a new script source appears there without being added to
the list: in the policy the server sends, in the app's own code, or in its
page; and if the list names one the code doesn't. No database."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from apps.billing import gateway as gw
from apps.cardpages import policy

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "card_page_scripts.md"
FRONTEND = ROOT / "frontend"


def listed() -> dict[str, str]:
    """The inventory's rows: source -> the "On" column."""
    rows = {}
    for line in DOC.read_text().splitlines():
        m = re.match(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+)\|", line)
        if m:
            rows[m.group(1)] = m.group(2).strip()
    return rows


def sources_of(header: str) -> list[str]:
    for part in header.split(";"):
        name, *values = part.split()
        if name == "script-src":
            return [v for v in values if v != "'report-sample'"]
    raise AssertionError("no script-src")


def app_sources() -> dict[Path, str]:
    return {path: path.read_text() for path in (FRONTEND / "src").rglob("*.ts*")
            if ".test." not in path.name and "/test/" not in str(path)}


def test_the_list_and_the_code_agree():
    rows = listed()
    assert set(rows) == {s["source"] for s in policy.SCRIPTS}, \
        "docs/card_page_scripts.md and apps/cardpages/policy.py SCRIPTS must name the same sources"
    for s in policy.SCRIPTS:
        on = rows[s["source"]]
        assert ("bank pages only" in on) == (s["pages"] == (policy.BANK,)), s["source"]


@pytest.mark.parametrize("api_host,sandbox_host", [
    ("secure.nmi.com", ""), ("secure.vaultixpay.com", ""),
    ("secure.vaultixpay.com", "secure.nmi.com"), ("secure.nmi.com", "secure.vaultixpay.com")])
def test_every_source_the_policy_can_allow_is_listed(settings, api_host, sandbox_host):
    settings.NMI_API_HOST = api_host
    settings.NMI_SANDBOX_CARD_FORM_HOST = sandbox_host
    rows = listed()
    card = sources_of(policy.value(policy.CARD, "https://x.test/csp-report"))
    bank = sources_of(policy.value(policy.BANK, "https://x.test/csp-report"))
    for source in card:
        assert source in rows and "bank pages only" not in rows[source], \
            f"the card policy allows {source}, which docs/card_page_scripts.md doesn't list"
    assert set(bank) - set(card) == {policy.PLAID_SCRIPT}
    # Never a whole host, never inline or eval.
    for source in card + bank:
        assert source == "'self'" or source.endswith(".js"), source
        assert source not in ("'unsafe-inline'", "'unsafe-eval'", "*", "https:"), source


def test_the_bank_pages_and_the_gateway_hosts_are_the_same_in_the_app():
    text = (FRONTEND / "src" / "lib" / "pagePolicy.ts").read_text()
    paths = re.search(r"BANK_PATHS = \[([^\]]*)\]", text).group(1)
    assert re.findall(r'"([^"]+)"', paths) == list(policy.BANK_PATHS)
    hosts = re.search(r"GATEWAY_SCRIPT_HOSTS = \[([^\]]*)\]", text).group(1)
    assert re.findall(r'"([^"]+)"', hosts) == list(gw.API_HOSTS)


def test_the_app_has_no_new_way_to_load_a_script():
    """Each place the app's code adds a script element, and each script
    address written in it, is one the list knows."""
    loaders = sorted(path.name for path, text in app_sources().items()
                     if re.search(r"createElement\(\s*[\"'`]script[\"'`]", text))
    assert loaders == ["BankConnections.tsx", "NmiCardForm.tsx"], (
        "A new place adds a script to the page: list its source in docs/card_page_scripts.md "
        "and apps/cardpages/policy.py, or don't.")
    rows = listed()
    for path, text in app_sources().items():
        for url in re.findall(r"https://[A-Za-z0-9.-]+/[^\s\"'`]*\.js\b", text):
            assert url in rows, f"{path.name} names the script {url}, which isn't listed"
        assert "document.write(" not in text, path.name
        assert not re.search(r"\beval\(|new Function\(", text), path.name


def test_the_page_itself_has_one_script_and_nothing_inline():
    html = (FRONTEND / "index.html").read_text()
    tags = re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S)
    assert tags == [""], "index.html: one script element, with no code in it"
    assert re.findall(r'<script\b[^>]*\bsrc="([^"]+)"', html) == ["/src/main.tsx"]


def test_the_payment_component_is_pinned_and_its_hash_checked():
    package = json.loads((FRONTEND / "package.json").read_text())
    assert package["dependencies"]["@nmipayments/nmi-pay"] == "1.1.1", "pinned exactly"
    lock = json.loads((FRONTEND / "package-lock.json").read_text())
    entry = lock["packages"]["node_modules/@nmipayments/nmi-pay"]
    assert entry["version"] == "1.1.1" and entry["integrity"].startswith("sha512-")


def test_the_build_puts_an_integrity_hash_on_the_entry_script():
    config = (FRONTEND / "vite.config.ts").read_text()
    assert "subresourceIntegrity()" in config and 'createHash("sha384")' in config
