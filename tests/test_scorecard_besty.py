"""M5 part 6: the Besty feed.

Against a stand-in for Besty's MCP server that answers in the envelopes
recorded from the live server on 2026-10-28 (`tests/fixtures/besty/`): the
handshake (initialize, its session id, notifications/initialized), the
tools' answers and refusals, and the schemas of the tools the menu reads.
The rows behind each answer are invented here, and the stand-in applies the
request's filters and aggregation to them as Besty does: every measure on
the menu, in total and by team member, owner or upsell type; the practice's
time zone at a period's edges; Besty's windows (a longer period read in
pieces); download links; the connection (encrypted, owner only, Test
connection = initialize plus tools/list); the feed rules shared with the
other feeds; and that **one company's token is never used for another
company's KPI**, nor one practice's anything for another's.
"""

from __future__ import annotations

import copy
import gzip
import json
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pytest
from django.utils import timezone

from apps.scorecard import besty, feeds, setup
from apps.scorecard.models import BestyConnection, Kpi, KpiBestyFeed, KpiHubSpotFeed, KpiReading
from apps.tenancy.context import tenant_context

from . import registry_config  # noqa: F401
from .factories import ClientCompanyFactory, MembershipFactory, TenantFactory

pytestmark = pytest.mark.django_db
FIXTURES = Path(__file__).parent / "fixtures" / "besty"
B = "/api/scorecard/besty/"
OCT_1, OCT_31 = date(2026, 10, 1), date(2026, 10, 31)
TODAY = date(2026, 11, 2)
NOW = datetime(2026, 11, 2, 18, 0, tzinfo=dt_timezone.utc)
DENVER = "America/Denver"
TOKEN_A = "besty-mcp-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaacme"
TOKEN_B = "besty-mcp-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbsumm"
DANA = "0a1b2c3d-0000-4000-8000-000000000001"
LUIS = "0a1b2c3d-0000-4000-8000-000000000002"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def at(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


# ---------------------------------------------------------------- the rows behind the answers

def _task(made, done, status, due=None, who=(), by="person", seconds=0):
    return {"created_at": made, "completed_at": done, "status": status, "due_at": due,
            "assignee_subuser_ids": list(who) or None, "created_by": by,
            "time_total_seconds": seconds}


ROWS = {
    "export_ops_tasks": [
        # Open at October's end (Denver), and overdue then: due October 15.
        _task("2026-09-20T15:00:00Z", None, "todo", "2026-10-15T15:00:00Z", [DANA]),
        # Done in October, two days after it was made, an hour's work.
        _task("2026-10-05T12:00:00Z", "2026-10-07T12:00:00Z", "done", "2026-10-06T12:00:00Z",
              [LUIS], seconds=3600),
        # Done at 11 pm on October 31 in Denver (November 1 in UTC): five days.
        _task("2026-10-27T05:00:00Z", "2026-11-01T05:00:00Z", "done", None, [DANA],
              seconds=7200),
        # Made by an automation after it was done (as Besty warns): counted
        # done, never in days to close; no tracked time.
        _task("2026-10-20T12:00:00Z", "2026-10-18T12:00:00Z", "done", None, [LUIS],
              by="task_automation"),
        # Done in November: open, and overdue, at October's end.
        _task("2026-10-25T12:00:00Z", "2026-11-03T12:00:00Z", "done", "2026-10-28T12:00:00Z",
              [LUIS]),
        # Open and unassigned, due later.
        _task("2026-10-30T12:00:00Z", None, "todo", "2026-11-20T12:00:00Z"),
        # Marked done with no completion time: not counted open.
        _task("2026-10-02T12:00:00Z", None, "done"),
    ],
    "export_upsell_events": [
        {"created_at": "2026-10-03T12:00:00Z", "upsell_type": "late_checkout",
         "revenue_amount": 50.0, "is_acceptance": True},
        {"created_at": "2026-10-09T12:00:00Z", "upsell_type": "early_checkin",
         "revenue_amount": 40.0, "is_acceptance": True},
        {"created_at": "2026-10-12T12:00:00Z", "upsell_type": "late_checkout",
         "revenue_amount": 50.0, "is_acceptance": False},              # a hold
        # 11 pm on September 30 in Denver.
        {"created_at": "2026-10-01T05:00:00Z", "upsell_type": "late_checkout",
         "revenue_amount": 75.0, "is_acceptance": True},
    ],
    # One row a reply; the stand-in averages them per responder.
    "compute_response_time": [
        {"at": "2026-10-04T12:00:00Z", "label": "Dana Whitfield", "minutes": 10},
        {"at": "2026-10-05T12:00:00Z", "label": "Dana Whitfield", "minutes": 20},
        {"at": "2026-10-06T12:00:00Z", "label": "Luis Ortega", "minutes": 30},
        *({"at": f"2026-10-{d:02d}T12:00:00Z", "label": "autopilot", "minutes": 1}
          for d in (7, 8, 9, 10)),
        # The third quarter, in both of its 90-day pieces.
        {"at": "2026-07-02T12:00:00Z", "label": "Dana Whitfield", "minutes": 40},
        {"at": "2026-09-30T12:00:00Z", "label": "Dana Whitfield", "minutes": 20},
    ],
    "export_reviews": [
        {"reviewed_at": "2026-10-05T12:00:00Z", "rating": 5, "rating_denominator": 5},
        {"reviewed_at": "2026-10-10T12:00:00Z", "rating": 4, "rating_denominator": 5},
        {"reviewed_at": "2026-10-20T12:00:00Z", "rating": 9, "rating_denominator": 10},
        {"reviewed_at": "2026-10-01T05:30:00Z", "rating": 1, "rating_denominator": 5},
    ],
    "export_messages": [
        # Owner 9001's thread: two messages from Dana.
        {"created_at": "2026-10-02T12:00:00Z", "thread_id": 70000001, "is_incoming": False,
         "sender_type": "host", "subuser_id": DANA},
        {"created_at": "2026-10-15T12:00:00Z", "thread_id": 70000001, "is_incoming": False,
         "sender_type": "host", "subuser_id": DANA},
        # Owner 9002's: one from Luis, sent from the PMS; one automated; the
        # owner's reply.
        {"created_at": "2026-10-20T12:00:00Z", "thread_id": 70000002, "is_incoming": False,
         "sender_type": "host_external", "subuser_id": LUIS},
        {"created_at": "2026-10-21T12:00:00Z", "thread_id": 70000002, "is_incoming": False,
         "sender_type": "automated", "subuser_id": None},
        {"created_at": "2026-10-22T12:00:00Z", "thread_id": 70000002, "is_incoming": True,
         "sender_type": "guest", "subuser_id": None},
        # A guest's thread, not an owner's.
        {"created_at": "2026-10-23T12:00:00Z", "thread_id": 555, "is_incoming": False,
         "sender_type": "host", "subuser_id": DANA},
        # September, in a quarter's second 31-day piece.
        {"created_at": "2026-09-25T12:00:00Z", "thread_id": 70000001, "is_incoming": False,
         "sender_type": "host", "subuser_id": DANA},
    ],
    "export_calls": [
        {"created_at": "2026-10-03T12:00:00Z", "status": "answered",
         "answered_by_subuser_id": DANA},
        {"created_at": "2026-10-04T12:00:00Z", "status": "ai_answered",
         "answered_by_subuser_id": None},
        {"created_at": "2026-10-05T12:00:00Z", "status": "answered",
         "answered_by_subuser_id": LUIS},
        {"created_at": "2026-10-06T12:00:00Z", "status": "no_answer",
         "answered_by_subuser_id": None},
    ],
}
PRIMARY = {"export_ops_tasks": "created_at", "export_upsell_events": "created_at",
           "export_reviews": "reviewed_at", "export_messages": "created_at",
           "export_calls": "created_at"}


def _in(row, key, wanted):
    value = row.get(key)
    if isinstance(value, list):
        return any(v in wanted for v in value)
    return value in wanted


def _top_filter(tool, rows, flt):
    for key, wanted in (flt or {}).items():
        if key == "only_acceptances":
            rows = [r for r in rows if r["is_acceptance"] is bool(wanted)]
        elif key == "is_incoming":
            rows = [r for r in rows if r["is_incoming"] is bool(wanted)]
        elif key == "assignee_subuser_ids":
            rows = [r for r in rows if _in(r, "assignee_subuser_ids", wanted)]
        elif key == "answered_by_subuser_ids":
            rows = [r for r in rows if r["answered_by_subuser_id"] in wanted]
        elif key == "thread_ids":
            assert len(wanted) <= 100                                 # Besty pins 100
            rows = [r for r in rows if r["thread_id"] in wanted]
        elif key in ("status", "created_by", "upsell_type", "sender_type"):
            rows = [r for r in rows if r.get(key) in wanted]
        else:
            raise AssertionError(f"{tool} has no filter {key}")
    return rows


def _compare(have, op, value):
    if op == "is_null":
        return have is None
    if op == "is_not_null":
        return have is not None
    if have is None:
        return False
    if isinstance(value, str) and value.endswith("Z"):
        have, value = at(have), at(value)
    return {"eq": have == value, "neq": have != value, "lt": have < value,
            "lte": have <= value, "gt": have > value, "gte": have >= value}[op]


def _measure(rows, text):
    fn, _, rest = text.partition("(")
    name = rest.rstrip(")")
    if fn == "count":
        return "count", str(len(rows))
    values = [Decimal(str(r[name])) for r in rows if r.get(name) is not None]
    if fn == "sum":
        return f"sum_{name}", str(sum(values)) if values else None
    if fn == "avg":
        return f"avg_{name}", str(sum(values) / len(values)) if values else None
    raise AssertionError(text)


def aggregate(tool, arguments):
    """What Besty answers to one export call, from the rows above."""
    rows = list(ROWS[tool])
    window = arguments.get("time_range")
    assert window, f"{tool} is always read with a window"
    since, until = at(window["since"]), at(window["until"])
    assert until - since <= timedelta(days=besty.MOST_DAYS[tool]), "past Besty's window"
    key = window.get("field") or PRIMARY[tool]
    rows = [r for r in rows if r.get(key) and since <= at(r[key]) < until]
    rows = _top_filter(tool, rows, arguments.get("filter"))
    agg = arguments["aggregation"]
    for f in agg.get("filters") or []:
        rows = [r for r in rows if _compare(r.get(f["field"]), f["op"], f.get("value"))]
    groups = {}
    for r in rows:
        groups.setdefault(tuple(r.get(d) for d in agg.get("dimensions") or []), []).append(r)
    if not agg.get("dimensions"):
        groups = {(): rows}
    out = []
    for values, members in groups.items():
        row = dict(zip(agg.get("dimensions") or [], values))
        row.update(_measure(members, m) for m in agg["measures"])
        out.append(row)
    return out


def response_rows(arguments):
    since, until = at(arguments["since"]), at(arguments["until"])
    if until - since > timedelta(days=90):
        return None                                                   # refused, as recorded
    by = {}
    for r in ROWS["compute_response_time"]:
        if since <= at(r["at"]) < until:
            by.setdefault(r["label"], []).append(r["minutes"])
    return [{"responder_label": k, "avg_response_minutes": sum(v) / len(v),
             "response_count": str(len(v))} for k, v in by.items()]


class FakeBesty:
    """A transport answering as Besty's MCP server does, in the recorded
    envelopes. It records each request with the Authorization and
    session headers it carried, and refuses any token but its own."""

    calls: list = []
    fetched: list = []
    SESSION = "5e55e55e-0000-4000-8000-00000000be57"

    def __init__(self, token=None, status_first=None, file=None, tools=None):
        self.token = token
        self.status_first = list(status_first or [])
        self.file = file
        self.tools = tools

    def __call__(self, method, url, headers, body):
        sent = json.loads(body)
        FakeBesty.calls.append({"method": sent.get("method"), "url": url,
                                "auth": headers.get("Authorization"),
                                "session": headers.get("Mcp-Session-Id"),
                                "accept": headers.get("Accept"), "body": sent})
        assert method == "POST" and url == besty.URL
        if self.status_first:
            return self.status_first.pop(0), {}, ""
        if self.token and headers.get("Authorization") != f"Bearer {self.token}":
            return 401, {}, ""
        name = sent.get("method")
        if name == "initialize":
            got = fixture("initialize.json")
            return got["status"], got["headers"], got["body"]
        assert headers.get("Mcp-Session-Id") == self.SESSION, "every call after initialize"
        if name == "notifications/initialized":
            got = fixture("initialized.json")
            return got["status"], got["headers"], got["body"]
        if name == "tools/list":
            got = fixture("tools_list.json")
            if self.tools is not None:
                message = json.loads(got["body"].split("data: ", 1)[1])
                message["result"]["tools"] = [{"name": n} for n in self.tools]
                got["body"] = "event: message\ndata: " + json.dumps(message) + "\n\n"
            return got["status"], got["headers"], got["body"]
        assert name == "tools/call"
        return 200, {"Content-Type": "text/event-stream", "mcp-session-id": self.SESSION}, \
            self._answer(sent["id"], sent["params"]["name"], sent["params"]["arguments"])

    def _answer(self, rpc_id, tool, arguments):
        def sse(result):
            return "event: message\ndata: " + json.dumps(
                {"result": result, "jsonrpc": "2.0", "id": rpc_id}) + "\n\n"

        def text(payload):
            return sse({"content": [{"type": "text", "text": json.dumps(payload)}]})

        if tool == "list_users":
            return text(fixture("list_users.json"))
        if tool == "export_owners":
            return text(fixture("export_owners.json"))
        if self.file is not None:
            return text(self.file)
        if tool == "compute_response_time":
            rows = response_rows(arguments)
            if rows is None:
                return sse({"content": [{"type": "text",
                                         "text": fixture("refusals.json")["too_long"]}],
                            "isError": True})
        else:
            rows = aggregate(tool, arguments)
        answer = copy.deepcopy(fixture("answers.json")[tool]["answer"])
        answer["ok"][0].update(rows=rows, head=rows[:5], row_count=len(rows))
        return text(answer)


def client(token=TOKEN_A, **kw):
    return besty.BestyClient(token, transport=FakeBesty(token=token, **kw),
                             fetch=lambda url: FakeBesty.fetched.append(url) or b"",
                             sleep=lambda s: None)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    FakeBesty.calls, FakeBesty.fetched = [], []
    besty._BUDGETS.clear()
    monkeypatch.setattr(besty, "http_transport", FakeBesty())

    def no_fetch(url):
        raise AssertionError("no download link is fetched unless one is sent")

    monkeypatch.setattr(besty, "http_fetch", no_fetch)


def value(measure, **kw):
    return besty.value_for(measure, client(), OCT_1, OCT_31, zone=DENVER, now=NOW,
                           cache={}, **kw)


# ---------------------------------------------------------------- the handshake

def test_initialize_then_initialized_then_every_call_with_the_session_and_token():
    c = client()
    assert c.test() == f"Connected: {len(json.loads(fixture('tools_list.json')['body'].split('data: ', 1)[1])['result']['tools'])} read-only tools."
    assert [x["method"] for x in FakeBesty.calls] == ["initialize", "notifications/initialized",
                                                      "tools/list"]
    first, *rest = FakeBesty.calls
    assert first["session"] is None and first["body"]["params"]["protocolVersion"]
    assert all(x["session"] == FakeBesty.SESSION for x in rest)
    assert {x["auth"] for x in FakeBesty.calls} == {f"Bearer {TOKEN_A}"}
    assert all("text/event-stream" in x["accept"] for x in FakeBesty.calls)
    assert "id" not in rest[0]["body"]                                # a notification
    # One session a read: a second call doesn't initialize again.
    c.call("export_reviews", {"time_range": {"since": "2026-10-01T06:00:00Z",
                                             "until": "2026-11-01T06:00:00Z"},
                              "aggregation": {"measures": ["count(*)"]}})
    assert [x["method"] for x in FakeBesty.calls].count("initialize") == 1


def test_test_connection_names_tools_the_token_cant_see():
    got = client(tools=["export_reviews", "list_users"]).test()
    assert got.startswith("Connected: 2 tools, but not export_ops_tasks")
    assert "export_reviews" not in got.split("but not", 1)[1]


def test_an_expired_session_is_opened_again_once():
    c = client()
    c.open()

    class Expire:
        def __init__(self, inner):
            self.inner, self.done = inner, False

        def __call__(self, method, url, headers, body):
            if not self.done and json.loads(body).get("method") == "tools/call":
                self.done = True
                return 404, {}, ""
            return self.inner(method, url, headers, body)

    c.transport = Expire(c.transport)
    assert besty.value_for("reviews_received", c, OCT_1, OCT_31, zone=DENVER, now=NOW) == 3
    assert [x["method"] for x in FakeBesty.calls].count("initialize") == 2


# ---------------------------------------------------------------- the menu, by the numbers

@pytest.mark.parametrize("measure,kw,expected", [
    ("tasks_open", {}, Decimal(3)), ("tasks_open", {"member": DANA}, Decimal(1)),
    ("tasks_open", {"member": LUIS}, Decimal(1)),
    ("tasks_overdue", {}, Decimal(2)), ("tasks_overdue", {"member": DANA}, Decimal(1)),
    ("tasks_completed", {}, Decimal(3)), ("tasks_completed", {"member": DANA}, Decimal(1)),
    # Two days and five, of the tasks a person made, in minutes.
    ("tasks_days_to_close", {}, Decimal("3.5") * 1440),
    ("tasks_days_to_close", {"member": LUIS}, Decimal(2) * 1440),
    # An hour and two, in minutes; the automation's untracked task not counted.
    ("tasks_work_time", {}, Decimal(90)),
    ("upsell_revenue", {}, Decimal("90.00")),
    ("upsell_revenue", {"param": "late_checkout"}, Decimal("50.00")),
    ("upsell_count", {}, Decimal(2)), ("upsell_count", {"param": "damage_waiver"}, Decimal(0)),
    ("reviews_received", {}, Decimal(3)),
    # 5, 4, and 9 of 10 as 4.5.
    ("average_rating", {}, Decimal("4.50")),
    ("owner_messages", {}, Decimal(3)), ("owner_messages", {"member": DANA}, Decimal(2)),
    ("owner_messages", {"owner": "9002"}, Decimal(1)),
    ("owner_messages", {"owner": "9002", "member": DANA}, Decimal(0)),
    ("owners_contacted", {}, Decimal(2)), ("owners_contacted", {"member": LUIS}, Decimal(1)),
    ("calls_answered", {}, Decimal(2)), ("calls_answered", {"member": LUIS}, Decimal(1)),
])
def test_every_measure_for_a_month(measure, kw, expected):
    assert value(measure, **kw) == expected


def test_response_time_for_everyone_people_autopilot_and_one_member():
    assert value("response_time") == Decimal(64) / 7                  # weighted by replies
    assert value("response_time", param="people") == Decimal(20)
    assert value("response_time", param="autopilot") == Decimal(1)
    assert value("response_time", member=DANA, member_name="Dana Whitfield") == Decimal(15)
    assert value("response_time", member="someone-else", member_name="Nobody") is None


def test_nothing_to_average_is_no_reading():
    november = (date(2026, 11, 10), date(2026, 11, 30))
    for measure in ("tasks_days_to_close", "tasks_work_time", "average_rating",
                    "response_time"):
        assert besty.value_for(measure, client(), *november, zone=DENVER, now=NOW) is None


def test_a_period_closes_at_the_practices_midnight():
    # The review at 11:30 pm on September 30 in Denver is October's in UTC.
    assert besty.value_for("reviews_received", client(), OCT_1, OCT_31, zone="UTC",
                           now=NOW) == 4
    start, end = besty.window(OCT_1, OCT_31, DENVER)
    assert start == at("2026-10-01T06:00:00Z") and end == at("2026-11-01T06:00:00Z")
    # An open period ends now.
    _, end = besty.window(date(2026, 11, 1), date(2026, 11, 30), DENVER, NOW)
    assert end == NOW


def test_a_longer_period_is_read_in_pieces_within_besty_windows():
    q3 = (date(2026, 7, 1), date(2026, 9, 30))
    # 92 days: response time in a 90-day piece and a 2-day one, both counted.
    assert besty.value_for("response_time", client(), *q3, zone=DENVER, now=NOW,
                           member=DANA, member_name="Dana Whitfield") == Decimal(30)
    windows = [x["body"]["params"]["arguments"] for x in FakeBesty.calls
               if x["method"] == "tools/call"]
    assert [at(w["until"]) - at(w["since"]) for w in windows] == [timedelta(days=90),
                                                                 timedelta(days=2)]
    # Messages: 31 days at most a call; September's message is in the third piece.
    FakeBesty.calls = []
    assert besty.value_for("owner_messages", client(), *q3, zone=DENVER, now=NOW) == 1
    spans = [at(x["body"]["params"]["arguments"]["time_range"]["until"])
             - at(x["body"]["params"]["arguments"]["time_range"]["since"])
             for x in FakeBesty.calls if x["method"] == "tools/call"
             and x["body"]["params"]["name"] == "export_messages"]
    assert len(spans) == 3 and max(spans) <= timedelta(days=31)


def test_the_stand_in_refuses_as_besty_does_and_it_is_said_in_besty_words():
    c = client()
    start, end = besty.window(date(2026, 7, 1), date(2026, 9, 30), DENVER)
    with pytest.raises(besty.BestyRefused) as exc:
        c.rows("compute_response_time", {"since": besty._iso(start), "until": besty._iso(end),
                                         "aggregate_window": True})
    assert str(exc.value) == ("Besty refused the read: compute_response_time window is 92 "
                              "days; max is 90 days")


def test_a_member_or_owner_is_asked_of_besty_not_only_filtered_here():
    value("tasks_completed", member=DANA)
    value("owner_messages", member=DANA, owner="9001")
    value("calls_answered", member=DANA)
    args = [x["body"]["params"]["arguments"] for x in FakeBesty.calls
            if x["method"] == "tools/call"]
    assert {"assignee_subuser_ids": [DANA], "status": ["done"]} in [a.get("filter") for a in args]
    messages = [a for a in args if a.get("filter", {}).get("thread_ids")]
    assert messages and all(a["filter"]["thread_ids"] == [70000001]
                            and a["filter"]["sender_type"] == ["host", "host_external"]
                            and a["aggregation"]["filters"] == [
                                {"field": "subuser_id", "op": "eq", "value": DANA}]
                            for a in messages)
    assert any(a.get("filter", {}).get("answered_by_subuser_ids") == [DANA] for a in args)


def test_an_owner_no_longer_in_besty_is_refused_in_words():
    with pytest.raises(besty.BestyRefused, match="no longer in Besty"):
        value("owner_messages", owner="1234")


def test_every_field_the_menu_reads_is_in_besty_recorded_schemas():
    schemas = {s["tool"]: {f["name"] for f in s["fields"]} for s in fixture("schemas.json")}
    used = {"export_ops_tasks": {"created_at", "completed_at", "status", "due_at",
                                 "assignee_subuser_ids", "created_by", "time_total_seconds"},
            "export_upsell_events": {"created_at", "upsell_type", "revenue_amount",
                                     "is_acceptance"},
            "compute_response_time": {"responder_label", "avg_response_minutes",
                                      "response_count"},
            "export_reviews": {"reviewed_at", "rating", "rating_denominator"},
            "export_messages": {"created_at", "thread_id", "is_incoming", "subuser_id",
                                "sender_type"},
            "export_owners": {"owner_id", "name", "thread_id"},
            "export_calls": {"created_at", "status", "answered_by_subuser_id"}}
    for tool, fields in used.items():
        assert fields <= schemas[tool], (tool, fields - schemas[tool])
    for tool, days in besty.MOST_DAYS.items():
        limits = next((s.get("limits") or {}) for s in fixture("schemas.json")
                      if s["tool"] == tool)
        if limits.get("max_window_days"):
            assert days == limits["max_window_days"], tool


# ---------------------------------------------------------------- downloads, refusals

def test_a_download_link_is_fetched_without_the_token_read_and_dropped():
    rows = [{"count": "4"}]
    raw = gzip.compress("\n".join(json.dumps(r) for r in rows).encode())
    fetched = []

    def fetch(url):
        fetched.append(url)
        return raw

    c = besty.BestyClient(TOKEN_A, transport=FakeBesty(token=TOKEN_A, file={
        "ok": [{"mode": "file", "format": "ndjson", "presigned_url":
                "https://besty-mcp-exports.s3.amazonaws.com/x.ndjson.gz?sig=1"}],
        "failed": []}), fetch=fetch, sleep=lambda s: None)
    assert c.rows("export_reviews", {}) == rows
    assert fetched == ["https://besty-mcp-exports.s3.amazonaws.com/x.ndjson.gz?sig=1"]
    assert TOKEN_A not in fetched[0]
    # Besty's answer as recorded: a Parquet file, which the feed doesn't read.
    c = client(file=fixture("file_answer.json"))
    with pytest.raises(besty.BestyRefused, match="as a parquet file"):
        c.rows("export_reviews", {})
    assert FakeBesty.fetched == []


def test_refusals_are_said_in_words_and_never_carry_the_token():
    for status, words in ((401, "refused the token"), (403, "refused the token"),
                          (500, "answered 500")):
        c = client(status_first=[status])
        with pytest.raises(besty.BestyUnavailable) as exc:
            c.test()
        assert words in str(exc.value) and TOKEN_A not in str(exc.value)
    # A JSON-RPC error and an isError answer are Besty's own words.
    c = client()
    with pytest.raises(besty.BestyRefused) as exc:
        c.rows("compute_response_time", {"since": "2026-01-01T00:00:00Z",
                                         "until": "2026-12-01T00:00:00Z",
                                         "aggregate_window": True})
    assert "max is 90 days" in str(exc.value)


def test_429s_are_waited_out_and_a_read_is_bounded():
    slept = []
    c = besty.BestyClient(TOKEN_A, transport=FakeBesty(token=TOKEN_A, status_first=[429, 429]),
                          sleep=slept.append)
    c.open()
    assert slept[:2] == [10.0, 10.0]
    c.calls = besty.MOST_CALLS
    with pytest.raises(besty.BestyUnavailable, match="carry on tomorrow"):
        c.tools()


# ---------------------------------------------------------------- the company, the KPI

@pytest.fixture
def practice(seeded_tenant, ff, api):
    t = seeded_tenant
    company = ClientCompanyFactory(tenant=t, name="Alpine Rentals Co.", seat_count=5)
    owner = MembershipFactory(tenant=t, role="FCC", client_company=company)
    with tenant_context(t.pk):
        card = setup.ensure(company, ff.user)
        page = card.pages.get()

        def kpi(name, kind, rollup="sum", **extra):
            return setup.create_kpi(card, {"name": name, "kind": kind, "cadence": "monthly",
                                           "rollup": rollup, "page": str(page.pk),
                                           "reading_owner": str(owner.user_id), **extra},
                                    ff.user)

        kpis = {"reviews": kpi("Reviews", "count", target_value=5),
                "rating": kpi("Rating", "rating", rollup="average"),
                "close": kpi("Days to close", "duration", rollup="average",
                             duration_unit="days"),
                "revenue": kpi("Upsell revenue", "money")}
    return {"t": t, "company": company, "owner": owner, "card": card, "kpis": kpis,
            "client": api.as_(ff)}


def connect(p, *, token=TOKEN_A, who=None, company=None):
    return (who or p["client"]).put(f"{B}connection/", json.dumps({
        "company": str((company or p["company"]).pk), "token": token}),
        content_type="application/json")


def set_feed(p, kpi, measure, company=None, **extra):
    # The read runs at NOW, the day after October closed in Denver.
    run = feeds.run_besty
    with mock.patch("apps.scorecard.views_besty._today", return_value=TODAY), \
            mock.patch.object(feeds, "run_besty",
                              lambda feed, today, **kw: run(feed, today, **{"now": NOW, **kw})):
        return p["client"].put(f"{B}feed/", json.dumps({
            "company": str((company or p["company"]).pk), "kpi": str(kpi.pk),
            "measure": measure, **extra}), content_type="application/json")


def notices(p, who):
    from django.test import Client

    c = Client()
    c.force_login(p[who].user)
    return c.get(f"/api/scorecard/notices/?company={p['company'].pk}").json()


def test_the_connection_is_the_practice_owners_and_its_token_is_never_shown(
        practice, seeded_tenant, api):
    p = practice
    assert connect(p, token="not a token").status_code == 400
    response = connect(p)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["connected"] and body["token_last4"] == "acme"
    assert TOKEN_A not in json.dumps(body)
    stored = BestyConnection.all_objects.get(company=p["company"])
    assert TOKEN_A.encode() not in bytes(stored.token_ciphertext)    # encrypted at rest
    tested = p["client"].post(f"{B}connection/test/", json.dumps(
        {"company": str(p["company"].pk)}), content_type="application/json").json()
    assert tested["check_ok"] is True and tested["check_detail"].startswith("Connected: ")
    assert [c["method"] for c in FakeBesty.calls] == ["initialize", "notifications/initialized",
                                                      "tools/list"]
    assert {c["auth"] for c in FakeBesty.calls} == {f"Bearer {TOKEN_A}"}
    assert TOKEN_A not in json.dumps(tested)
    # Associates and assistants don't connect it; a client never reaches it.
    for role in ("CF", "VA"):
        m = MembershipFactory(tenant=seeded_tenant, role=role)
        assert connect(p, who=api.as_(m)).status_code in (403, 404)
    assert connect(p, who=api.as_(p["owner"])).status_code == 403
    # Disconnecting takes the token with it.
    assert p["client"].delete(f"{B}connection/?company={p['company'].pk}").status_code == 200
    assert not BestyConnection.all_objects.filter(company=p["company"]).exists()


def test_the_demo_never_connects(practice, monkeypatch):
    from config import environment

    monkeypatch.setattr(environment, "is_demo", lambda: True)
    assert connect(practice).status_code == 409
    with pytest.raises(besty.BestyUnavailable, match="demo"):
        feeds.besty_client(practice["company"])


def test_a_measure_reads_closed_periods_by_the_feed_rules(practice):
    p = practice
    connect(p)
    reviews = p["kpis"]["reviews"]
    refused = set_feed(p, reviews, "upsell_revenue")
    assert refused.status_code == 400 and "fits a KPI of kind Money" in refused.json()["measure"]
    # A month typed by hand before the feed.
    with tenant_context(p["t"].pk):
        KpiReading.objects.create(tenant=p["t"], kpi=reviews, period_start=date(2026, 9, 1),
                                  value=Decimal("7"), entered_at=timezone.now())
    saved = set_feed(p, reviews, "reviews_received")
    assert saved.status_code == 200, saved.content
    assert saved.json()["run"]["ok"] is True
    got = {r.period_start: r for r in KpiReading.all_objects.filter(kpi=reviews)}
    assert got[OCT_1].value == 3 and got[OCT_1].source == "besty"
    assert got[date(2026, 9, 1)].value == 7 and got[date(2026, 9, 1)].source == "hand"
    assert date(2026, 11, 1) not in got                               # a sum: not read open
    feed = KpiBestyFeed.all_objects.get(kpi=reviews)
    assert feed.last_counts and feed.last_success_at
    # A failed read keeps every reading and tells the reading owner once.
    before = {s: r.value for s, r in got.items()}
    failing = client(status_first=[401] * 20)
    result = feeds.run_besty(feed, TODAY, client=failing)
    assert result["ok"] is False and "refused the token" in result["error"]
    feeds.run_besty(feed, TODAY, client=failing)
    assert {r.period_start: r.value for r in KpiReading.all_objects.filter(kpi=reviews)} == before
    owner_notices = [n for n in notices(p, "owner") if n["kind"] == "feed"]
    assert len(owner_notices) == 1 and owner_notices[0]["kpi"] == "Reviews"
    assert TOKEN_A not in json.dumps(owner_notices)
    # The tile's back names the source.
    board = p["client"].get(f"/api/scorecard/?company={p['company'].pk}&window=last_year").json()
    tile = next(t for t in board["kpis"] if t["name"] == "Reviews")
    assert tile["feed"]["kind"] == "besty"
    assert tile["feed"]["text"] == ("From Besty: Reviews received, the whole account, "
                                    "computed once a day")
    # Stopping keeps the readings.
    p["client"].delete(f"{B}feed/?company={p['company'].pk}&kpi={reviews.pk}")
    assert KpiReading.all_objects.filter(kpi=reviews).count() == len(before)
    reviews.refresh_from_db()
    assert reviews.feed == Kpi.Feed.HAND


def test_the_open_period_is_read_as_it_goes(practice):
    p = practice
    connect(p)
    rating = p["kpis"]["rating"]                                      # an average: on by default
    saved = set_feed(p, rating, "average_rating")
    assert saved.status_code == 200, saved.content
    assert saved.json()["feed"]["read_open"] is True
    assert saved.json()["feed"]["text"].endswith("the open period so far")
    got = {r.period_start: r for r in KpiReading.all_objects.filter(kpi=rating)}
    assert got[OCT_1].value == Decimal("4.5") and not got[OCT_1].provisional
    # November has no review yet: nothing to average, nothing written.
    assert date(2026, 11, 1) not in got
    ROWS["export_reviews"].append({"reviewed_at": "2026-11-02T12:00:00Z", "rating": 4,
                                   "rating_denominator": 5})
    try:
        feed = KpiBestyFeed.all_objects.get(kpi=rating)
        assert feeds.run_besty(feed, TODAY, now=NOW)["ok"]
        nov = KpiReading.all_objects.get(kpi=rating, period_start=date(2026, 11, 1))
        assert nov.value == Decimal(4) and nov.provisional
    finally:
        ROWS["export_reviews"].pop()


def test_days_to_close_is_in_the_kpis_unit_and_scope_is_kept_to_the_measure(practice):
    p = practice
    connect(p)
    close = p["kpis"]["close"]
    saved = set_feed(p, close, "tasks_days_to_close", member_id=LUIS, member_name="Luis Ortega",
                     owner_id="9001", param="late_checkout")
    assert saved.status_code == 200, saved.content
    feed = KpiBestyFeed.all_objects.get(kpi=close)
    assert (feed.member_id, feed.owner_id, feed.param) == (LUIS, "", "")
    assert KpiReading.all_objects.get(kpi=close, period_start=OCT_1).value == Decimal("2.0")
    assert saved.json()["feed"]["text"].startswith(
        "From Besty: Ops tasks: average days to close (tasks made by a person), Luis Ortega")
    revenue = p["kpis"]["revenue"]
    assert set_feed(p, revenue, "upsell_revenue", param="nope").status_code == 400
    saved = set_feed(p, revenue, "upsell_revenue", param="late_checkout", member_id=DANA)
    feed = KpiBestyFeed.all_objects.get(kpi=revenue)
    assert (feed.member_id, feed.param) == ("", "late_checkout")
    assert saved.json()["feed"]["text"] == ("From Besty: Upsell revenue, late checkout, the "
                                            "whole account, computed once a day")
    assert KpiReading.all_objects.get(kpi=revenue, period_start=OCT_1).value == Decimal("50")


def test_the_picker_offers_the_menu_team_owners_and_types(practice):
    p = practice
    connect(p)
    got = p["client"].get(f"{B}options/?company={p['company'].pk}").json()
    assert {m["key"] for m in got["measures"]} == set(besty.MEASURES)
    assert [m["name"] for m in got["members"]] == ["Dana Whitfield", "Luis Ortega",
                                                   "Priya Raman"]
    # An owner with no thread can't be messaged, so isn't offered.
    assert [o["id"] for o in got["owners"]] == ["9001", "9002"]
    assert {u["id"] for u in got["upsell_types"]} == set(besty.UPSELL_TYPES)
    assert got["error"] == ""


def test_a_per_person_kpi_is_refused(practice):
    p = practice
    connect(p)
    with tenant_context(p["t"].pk):
        rep = MembershipFactory(tenant=p["t"], role="ECC", client_company=p["company"])
        per = setup.create_kpi(p["card"], {"name": "Calls per person", "kind": "count",
                                           "cadence": "monthly", "per_person": True,
                                           "people": [str(rep.pk)],
                                           "page": str(p["card"].pages.get().pk)},
                               p["owner"].user)
    assert "reading per person" in set_feed(p, per, "calls_answered").json()["measure"]


def test_a_kpi_has_one_feed(practice):
    p = practice
    connect(p)
    reviews = p["kpis"]["reviews"]
    other = KpiHubSpotFeed.all_objects.create(tenant=p["t"], kpi=reviews, measure="deals_won")
    set_feed(p, reviews, "reviews_received")
    other.refresh_from_db()
    assert other.active is False
    assert KpiBestyFeed.all_objects.get(kpi=reviews).active


def test_the_daily_pass_reads_each_feed_once_a_day(practice):
    p = practice
    connect(p)
    set_feed(p, p["kpis"]["reviews"], "reviews_received")
    later = NOW + timedelta(hours=2)
    assert feeds.run_due_besty(p["t"].pk, TODAY, now=later) == {"ran": 0, "failed": 0}
    assert feeds.run_due_besty(p["t"].pk, TODAY, now=NOW + timedelta(days=1)) == {
        "ran": 1, "failed": 0}


def test_nothing_besty_answers_is_kept_beyond_the_readings(practice):
    from django.apps import apps

    p = practice
    connect(p)
    set_feed(p, p["kpis"]["reviews"], "reviews_received")
    feed = KpiBestyFeed.all_objects.get(kpi=p["kpis"]["reviews"])
    # The feed row holds counts of what it wrote, never Besty's rows.
    assert feed.last_counts and all(isinstance(v, int) for v in feed.last_counts.values())
    assert not [m for m in apps.get_app_config("scorecard").get_models()
                if "besty" in m._meta.db_table and m not in (BestyConnection, KpiBestyFeed)]


# ---------------------------------------------------------------- isolation

def test_one_companys_token_is_never_used_for_another_companys_kpi(practice, ff, monkeypatch):
    p = practice
    connect(p)
    other = ClientCompanyFactory(tenant=p["t"], name="Summit Lodges", seat_count=3)
    connect(p, token=TOKEN_B, company=other)
    with tenant_context(p["t"].pk):
        card = setup.ensure(other, ff.user)
        theirs = setup.create_kpi(card, {"name": "Summit reviews", "kind": "count",
                                         "cadence": "monthly", "page": str(card.pages.get().pk)},
                                  ff.user)
    FakeBesty.calls = []
    set_feed(p, p["kpis"]["reviews"], "reviews_received")
    ours = {c["auth"] for c in FakeBesty.calls}
    FakeBesty.calls = []
    set_feed(p, theirs, "reviews_received", company=other)
    assert ours == {f"Bearer {TOKEN_A}"}
    assert {c["auth"] for c in FakeBesty.calls} == {f"Bearer {TOKEN_B}"}
    # A KPI of one company can't be pointed at through another's route.
    assert set_feed(p, theirs, "reviews_received").status_code == 404
    # The daily pass reads each feed with its own company's token only.
    FakeBesty.calls = []
    feeds.run_besty(KpiBestyFeed.all_objects.get(kpi=theirs), TODAY, now=NOW)
    assert {c["auth"] for c in FakeBesty.calls} == {f"Bearer {TOKEN_B}"}
    # A stand-in that knows only A's token refuses B's: B's KPI fails, A's is untouched.
    monkeypatch.setattr(besty, "http_transport", FakeBesty(token=TOKEN_A))
    assert feeds.run_besty(KpiBestyFeed.all_objects.get(kpi=theirs), TODAY, now=NOW)["ok"] \
        is False
    assert feeds.run_besty(KpiBestyFeed.all_objects.get(kpi=p["kpis"]["reviews"]), TODAY,
                           now=NOW)["ok"] is True
    # Each company keeps its own request budget.
    assert {f"company:{p['company'].pk}", f"company:{other.pk}"} <= set(besty._BUDGETS)


def test_another_practice_never_reaches_a_connection_or_a_feed(practice):
    from django.test import Client

    from apps.crm.seed import seed_tenant

    p = practice
    connect(p)
    set_feed(p, p["kpis"]["reviews"], "reviews_received")
    other = TenantFactory()
    seed_tenant(other)
    b = Client()
    b.force_login(MembershipFactory(tenant=other, role="FF").user)
    q = f"?company={p['company'].pk}"
    assert b.get(f"{B}connection/{q}").status_code == 404
    assert b.put(f"{B}connection/", json.dumps({"company": str(p["company"].pk),
                                                "token": TOKEN_B}),
                 content_type="application/json").status_code == 404
    assert b.post(f"{B}connection/test/", json.dumps({"company": str(p["company"].pk)}),
                  content_type="application/json").status_code == 404
    assert b.get(f"{B}options/{q}").status_code == 404
    assert b.get(f"{B}feed/{q}&kpi={p['kpis']['reviews'].pk}").status_code == 404
    assert b.delete(f"{B}feed/{q}&kpi={p['kpis']['reviews'].pk}").status_code == 404
    with tenant_context(other.pk):
        assert not BestyConnection.objects.exists() and not KpiBestyFeed.objects.exists()
