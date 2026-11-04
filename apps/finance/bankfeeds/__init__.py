"""Bank feeds (`docs/p6_bank_feeds.md`): the practice owner's own bank
accounts, feeding Finance.

- `providers/`: the one place a bank-data provider is spoken to. Plaid is the
  first; a second is added there, behind the same interface, and nothing else
  changes.
- `connections.py`: connecting, mapping each account to a ledger account,
  Check now, Reconnect, Disconnect, and the notices.
- `sync.py`: what a sync does to the books.
- `views.py`: the owner's routes, and the provider's webhook.
"""
