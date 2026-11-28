#!/usr/bin/env python3
"""The gate's dependency audit (2026-11-27, docs/security_updates.md).

    .venv/bin/python scripts/dependency_audit.py

Fails (exit 1) when a package we pin or ship has a known **high or critical**
advisory **that has a fix**, unless a dated entry in
`scripts/audit_allowlist.toml` covers it. Everything else is listed and
passes: a moderate or low advisory, or one with no fixed version yet.

What it reads:
- **Python**: every `name==version` pin in requirements.txt and
  requirements-dev.txt (what production runs and what the laptop runs),
  checked against OSV (osv.dev, Google's open vulnerability database, which
  carries the Python Packaging Authority's advisories and GitHub's).
- **Frontend**: the packages that ship to browsers, by `npm audit --omit=dev`
  (npm's registry, GitHub's advisories). The build and test tools are left
  to Dependabot (.github/dependabot.yml) and the routine in the doc.

The rank: GitHub's severity (critical, high, moderate, low), read from the
advisory or from its GitHub alias. An advisory with no rating counts as high,
so nothing unrated passes for want of a label. When an advisory service can't
be reached, the audit fails: "couldn't check" is not "clean".

Standard library only, so the audit needs nothing installed to run.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ("requirements.txt", "requirements-dev.txt")
ALLOWLIST = ROOT / "scripts" / "audit_allowlist.toml"
OSV = "https://api.osv.dev/v1"
BLOCKING = ("CRITICAL", "HIGH")
#: An exception lasts at most this long: the same 30 days the doc gives a
#: critical or high fix to go live.
MOST_DAYS = 30
RANK = {"CRITICAL": 0, "HIGH": 1, "UNRATED": 1, "MODERATE": 2, "LOW": 3}


class AuditError(Exception):
    """The audit could not be completed; the message says why."""


@dataclass
class Advisory:
    where: str              # "python" or "frontend"
    package: str
    version: str
    id: str
    severity: str           # CRITICAL, HIGH, MODERATE, LOW, or UNRATED
    fixed: list[str]
    summary: str = ""
    aliases: list[str] = field(default_factory=list)

    @property
    def names(self) -> set[str]:
        return {self.id, *self.aliases}

    @property
    def blocking(self) -> bool:
        return (self.severity in BLOCKING or self.severity == "UNRATED") and bool(self.fixed)

    def line(self) -> str:
        fix = f"fixed in {', '.join(self.fixed)}" if self.fixed else "no fix yet"
        return (f"{self.severity:<8} {self.where:<8} {self.package} {self.version}  {self.id}  "
                f"{fix}  {self.summary[:90]}")


# --- the allow-list ------------------------------------------------------------

@dataclass
class Allowed:
    id: str
    package: str
    reason: str
    added: dt.date
    until: dt.date


def load_allowlist(text: str, today: dt.date) -> list[Allowed]:
    """The exceptions, each checked: an id, the package, a reason, and dates no
    more than MOST_DAYS apart. An expired one is an error, so it can't sit
    there unnoticed."""
    data = tomllib.loads(text)
    out, problems = [], []
    for n, row in enumerate(data.get("allow", []), start=1):
        missing = [k for k in ("id", "package", "reason", "added", "until")
                   if not str(row.get(k, "")).strip()]
        if missing:
            problems.append(f"entry {n}: missing {', '.join(missing)}")
            continue
        added, until = row["added"], row["until"]
        if not isinstance(added, dt.date) or not isinstance(until, dt.date):
            problems.append(f"entry {n} ({row['id']}): added and until must be dates (2026-11-27)")
            continue
        if until < added:
            problems.append(f"entry {n} ({row['id']}): until is before added")
        elif (until - added).days > MOST_DAYS:
            problems.append(f"entry {n} ({row['id']}): lasts {(until - added).days} days; "
                            f"the most is {MOST_DAYS}")
        elif until < today:
            problems.append(f"entry {n} ({row['id']}): expired on {until}. Apply the fix, "
                            "or renew it with a new reason and dates")
        else:
            out.append(Allowed(str(row["id"]).strip(), str(row["package"]).strip(),
                               str(row["reason"]).strip(), added, until))
    if problems:
        raise AuditError("the allow-list (scripts/audit_allowlist.toml): " + "; ".join(problems))
    return out


def allowed_by(advisory: Advisory, allowlist: list[Allowed]) -> Allowed | None:
    for entry in allowlist:
        if entry.id in advisory.names:
            return entry
    return None


# --- Python, by OSV ------------------------------------------------------------

_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;#]+)")


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pins(texts: list[str]) -> dict[str, str]:
    """Every `name==version` line, by canonical name."""
    out = {}
    for text in texts:
        for raw in text.splitlines():
            match = _PIN.match(raw.strip())
            if match:
                out[canonical(match.group(1))] = match.group(2)
    return out


def http_json(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "dependency-audit"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise AuditError(f"couldn't reach {url.split('/v1')[0]} ({type(exc).__name__}: {exc}). "
                         "The audit can't pass without checking; try again when online.") from None


def severity_of(record: dict, fetch) -> str:
    """GitHub's rating: on the record, or on its GHSA alias."""
    rating = (record.get("database_specific") or {}).get("severity")
    if rating:
        return str(rating).upper()
    for alias in record.get("aliases") or []:
        if alias.startswith("GHSA-"):
            rating = (fetch(f"{OSV}/vulns/{alias}").get("database_specific") or {}).get("severity")
            if rating:
                return str(rating).upper()
    return "UNRATED"


def fixed_versions(record: dict, package: str) -> list[str]:
    out = []
    for affected in record.get("affected") or []:
        pkg = affected.get("package") or {}
        if pkg.get("ecosystem") != "PyPI" or canonical(pkg.get("name", "")) != package:
            continue
        for rng in affected.get("ranges") or []:
            out += [e["fixed"] for e in rng.get("events") or [] if "fixed" in e]
    return sorted(set(out))


def python_advisories(pinned: dict[str, str], fetch=http_json) -> list[Advisory]:
    names = sorted(pinned)
    queries = [{"package": {"name": n, "ecosystem": "PyPI"}, "version": pinned[n]} for n in names]
    results = fetch(f"{OSV}/querybatch", {"queries": queries}).get("results", [])
    if len(results) != len(names):
        raise AuditError("OSV answered for a different number of packages than were asked.")
    out = []
    for name, result in zip(names, results):
        if result.get("next_page_token"):
            raise AuditError(f"OSV has more advisories for {name} than one answer holds.")
        for hit in result.get("vulns") or []:
            record = fetch(f"{OSV}/vulns/{hit['id']}")
            out.append(Advisory(
                where="python", package=name, version=pinned[name], id=record.get("id", hit["id"]),
                severity=severity_of(record, fetch), fixed=fixed_versions(record, name),
                summary=(record.get("summary") or record.get("details") or "").splitlines()[0]
                if (record.get("summary") or record.get("details")) else "",
                aliases=list(record.get("aliases") or [])))
    return one_each(out)


def one_each(advisories: list[Advisory]) -> list[Advisory]:
    """One line per flaw: OSV lists many under two ids (PYSEC and GHSA) that
    name each other as aliases. The worse-rated copy is kept."""
    kept: list[Advisory] = []
    for a in sorted(advisories, key=lambda a: RANK.get(a.severity, 1)):
        if not any(k.package == a.package and k.names & a.names for k in kept):
            kept.append(a)
    return kept


# --- the frontend, by npm audit --------------------------------------------------

def npm_audit_json(frontend: Path = ROOT / "frontend") -> dict:
    """`npm audit --omit=dev --json`: it exits non-zero when it finds anything,
    so the answer is judged by its content, and an answer with no report in it
    is an error."""
    done = subprocess.run(["npm", "audit", "--omit=dev", "--json"], cwd=frontend,
                          capture_output=True, text=True, timeout=180)
    try:
        report = json.loads(done.stdout or "{}")
    except ValueError:
        raise AuditError(f"npm audit gave no report: {done.stderr.strip()[:300]}") from None
    if "error" in report or "vulnerabilities" not in report:
        detail = (report.get("error") or {}).get("summary") or done.stderr.strip()[:300]
        raise AuditError(f"npm audit couldn't check: {detail}")
    return report


def frontend_advisories(report: dict) -> list[Advisory]:
    out = []
    for name, entry in sorted((report.get("vulnerabilities") or {}).items()):
        fix = entry.get("fixAvailable")
        if isinstance(fix, dict):
            fixed = [f"{fix.get('name')}@{fix.get('version')}"
                     + (" (a major version)" if fix.get("isSemVerMajor") else "")]
        else:
            fixed = ["npm audit fix"] if fix else []
        for via in entry.get("via") or []:
            if not isinstance(via, dict):       # another package's entry carries it
                continue
            url = str(via.get("url") or "")
            ghsa = url.rsplit("/", 1)[-1] if "/advisories/GHSA-" in url else ""
            out.append(Advisory(
                where="frontend", package=name, version=str(via.get("range") or entry.get("range")),
                id=ghsa or f"npm-{via.get('source')}",
                severity=str(via.get("severity") or entry.get("severity") or "").upper() or "UNRATED",
                fixed=fixed, summary=str(via.get("title") or ""),
                aliases=[f"npm-{via.get('source')}"] if ghsa else []))
    return out


# --- the verdict ---------------------------------------------------------------

def verdict(advisories: list[Advisory], allowlist: list[Allowed]) -> tuple[list, list, list]:
    """(blocking, allowed, informational), each sorted worst first."""
    blocking, allowed, info = [], [], []
    for a in sorted(advisories, key=lambda a: (RANK.get(a.severity, 1), a.where, a.package, a.id)):
        if not a.blocking:
            info.append(a)
        elif (entry := allowed_by(a, allowlist)) is not None:
            allowed.append((a, entry))
        else:
            blocking.append(a)
    return blocking, allowed, info


def main(today: dt.date | None = None) -> int:
    today = today or dt.datetime.now(dt.timezone.utc).date()
    try:
        allowlist = load_allowlist(ALLOWLIST.read_text() if ALLOWLIST.exists() else "", today)
        pinned = pins([(ROOT / f).read_text() for f in REQUIREMENTS])
        advisories = python_advisories(pinned) + frontend_advisories(npm_audit_json())
    except AuditError as exc:
        print(f"audit: couldn't complete: {exc}", file=sys.stderr)
        return 2
    blocking, allowed, info = verdict(advisories, allowlist)
    for a in blocking:
        print(f"BLOCKING  {a.line()}")
    for a, entry in allowed:
        print(f"ALLOWED   {a.line()}\n          until {entry.until}: {entry.reason}")
    for a in info:
        print(f"noted     {a.line()}")
    used = {e.id for _, e in allowed}
    for entry in allowlist:
        if entry.id not in used:
            print(f"unused    allow-list entry {entry.id} ({entry.package}) matches nothing now; "
                  "remove it")
    print(f"audit: {len(pinned)} Python pins and the shipped frontend packages: "
          f"{len(blocking)} blocking, {len(allowed)} allowed, {len(info)} noted.")
    if blocking:
        print("audit: REFUSED. Update each blocking package to a fixed version "
              "(docs/security_updates.md), or add a dated exception with its reason.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
