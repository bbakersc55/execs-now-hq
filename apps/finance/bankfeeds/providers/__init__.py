"""The provider behind each connection, by name.

Adding a second provider: a module beside `plaid.py` implementing
`base.Provider`, one line in `_FACTORIES`, and its settings. Connections
remember their provider's name, so both can run side by side.
"""

from __future__ import annotations

from .base import (  # noqa: F401  (the interface, from one place)
    LOGIN_CODES, Account, Changes, Event, Linked, NotConfigured, Provider, ProviderError,
    Transaction, WebhookRefused,
)

#: The provider a new connection uses.
DEFAULT = "plaid"


def _plaid():
    from .plaid import PlaidProvider

    return PlaidProvider()


_FACTORIES = {"plaid": _plaid}
#: Set by the tests (and the demo seed) to stand in for every provider.
_override: Provider | None = None


def get(name: str = DEFAULT) -> Provider:
    if _override is not None:
        return _override
    factory = _FACTORIES.get(name)
    if factory is None:
        raise NotConfigured(f"No bank-feed provider called {name!r}.")
    return factory()


def configured(name: str = DEFAULT) -> bool:
    """Whether this server can make a connection: the provider's keys are set
    (or a stand-in is in place)."""
    if _override is not None:
        return True
    if name == "plaid":
        from .plaid import configured as plaid_configured

        return plaid_configured()
    return False


class use:
    """`with providers.use(fake):` — every provider is `fake` inside."""

    def __init__(self, provider: Provider):
        self.provider = provider

    def __enter__(self):
        global _override
        self.before, _override = _override, self.provider
        return self.provider

    def __exit__(self, *exc):
        global _override
        _override = self.before
        return False
