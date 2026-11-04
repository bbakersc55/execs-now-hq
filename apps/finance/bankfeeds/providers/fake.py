"""A provider with no bank behind it: the tests' (and the demo seed's).

It keeps one login's accounts and a list of change sets; `changes` hands them
out from the cursor it is given, a page at a time, so cursor handling is
exercised exactly as Plaid's is. Never used for a real connection.
"""

from __future__ import annotations

from .base import Account, Changes, Event, Linked, Provider, ProviderError, WebhookRefused


class FakeProvider(Provider):
    name = "fake"

    def __init__(self):
        self.accounts_list: list[Account] = []
        #: Each a dict {added: [...], modified: [...], removed: [...]}, one page.
        self.pages: list[dict] = []
        self.calls: list[tuple] = []
        self.removed_items: list[str] = []
        #: Raise this from `changes` (once), e.g. ITEM_LOGIN_REQUIRED.
        self.fail_with: ProviderError | None = None
        self.next_item = 1
        self.events: dict[str, Event] = {}

    # The cursor is the number of pages already handed out.
    def changes(self, access_token: str, cursor: str) -> Changes:
        self.calls.append(("changes", cursor))
        if self.fail_with is not None:
            failure, self.fail_with = self.fail_with, None
            raise failure
        start = int(cursor or 0)
        out = Changes(cursor=cursor)
        for number, page in enumerate(self.pages[start:], start=start + 1):
            out.pages += 1
            out.added += page.get("added", [])
            out.modified += page.get("modified", [])
            out.removed += page.get("removed", [])
            out.cursor = str(number)
        return out

    def link_token(self, *, user_ref: str, webhook_url: str, access_token: str = "") -> str:
        self.calls.append(("link_token", "update" if access_token else "new", webhook_url))
        return "link-fake-update" if access_token else "link-fake-new"

    def exchange(self, public_token: str) -> Linked:
        self.calls.append(("exchange",))
        if public_token != "public-fake":
            raise ProviderError("That public token is not one this provider made.",
                                code="INVALID_PUBLIC_TOKEN")
        item = f"item-fake-{self.next_item}"
        self.next_item += 1
        return Linked(access_token=f"access-fake-{item}", item_id=item,
                      institution_id="ins_fake", institution_name="First Fake Bank")

    def accounts(self, access_token: str) -> list[Account]:
        self.calls.append(("accounts",))
        return list(self.accounts_list)

    def remove(self, access_token: str) -> None:
        self.calls.append(("remove",))
        self.removed_items.append(access_token)

    def read_webhook(self, body: bytes, headers) -> Event:
        key = headers.get("Plaid-Verification") or ""
        if key not in self.events:
            raise WebhookRefused("Not one of the fake's events.")
        return self.events[key]
