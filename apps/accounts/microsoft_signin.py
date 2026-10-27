"""Staff sign-in with Microsoft, for practices whose mail runs through
Microsoft 365 (2026-10-27; docs/m365_transport.md D1).

The same rules as Google sign-in (`adapters.py`, `google_external.py`):
**invite-only**. An address must already belong to a live staff member (the
practice owner, an associate or an assistant) of a practice that is not
archived, and here that practice's mail provider is Microsoft 365. Nobody is
signed up. Clients never use this: they sign in by magic link.

Same Entra app registration as connecting mail, and the same redirect URI:
the callback there hands a sign-in on to `callback` by its state.

**Which address counts.** Microsoft's `email` claim is not verified, and any
directory's administrator can put any address on one of their users (the
"nOAuth" problem). So an address is believed only when its domain is a
**verified domain of the signing-in account's own directory** (Graph
`/organization`), it is that account's mailbox address or sign-in name, and,
once a user has signed in with Microsoft, it is the same work account
(directory and object id) every time after.
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import login
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.crm.services import microsoft_oauth

STATE_KEY = "enhq_microsoft_signin_state"
#: `User.Read` reads the account's addresses and its directory's verified
#: domains; nothing else is asked for, and no refresh token is kept.
SIGN_IN_SCOPES = ["openid", "email", "profile", "User.Read"]
STAFF_ROLES = ("FF", "CF", "VA")
NO_ACCESS = ("That account has no access to this workspace. It is invite-only; ask "
             "the practice owner to invite you.")


def _staff(email: str):
    """A live staff membership of a Microsoft practice for this address."""
    from apps.tenancy.models import Membership

    if not email:
        return None
    return (Membership.all_objects.select_related("user", "tenant")
            .filter(user__email__iexact=email, revoked_at__isnull=True,
                    role__in=STAFF_ROLES, tenant__mail_provider="microsoft")
            .exclude(tenant__status="archived").first())


def offered(tenant=None) -> bool:
    """Whether the sign-in page shows "Sign in with Microsoft": the server has
    the registration, and the practice the page is for (or, when the page
    knows none, some practice) runs its mail through Microsoft 365."""
    from apps.tenancy.models import Tenant

    if not microsoft_oauth.is_configured():
        return False
    if tenant is not None:
        return tenant.mail_provider == "microsoft" and tenant.status != "archived"
    return Tenant.objects.filter(mail_provider="microsoft").exclude(status="archived").exists()


@require_http_methods(["GET"])
def start(request):
    """Email first, as Google's: the address is the login hint. Any address
    goes to Microsoft, known or not, so the form says nothing about who has
    access; the callback decides."""
    if not microsoft_oauth.is_configured():
        return _refuse(request, "Sign in with Microsoft isn't set up yet. Contact support.")
    email = (request.GET.get("email") or "").strip().lower()
    state = microsoft_oauth.new_state()
    request.session[STATE_KEY] = state
    params = {"client_id": settings.MICROSOFT_CLIENT_ID, "response_type": "code",
              "redirect_uri": microsoft_oauth.redirect_uri(), "response_mode": "query",
              "scope": " ".join(SIGN_IN_SCOPES), "state": state, "prompt": "select_account"}
    if email:
        params["login_hint"] = email
    return HttpResponseRedirect(
        f"{microsoft_oauth.LOGIN}/{microsoft_oauth.authority()}/oauth2/v2.0/authorize?"
        + urlencode(params))


def is_sign_in(request) -> bool:
    """Whether this redirect answers a sign-in this browser started, rather
    than a mail connection (the two share the registration's redirect URI)."""
    expected = request.session.get(STATE_KEY)
    return bool(expected) and request.GET.get("state") == expected


def believed_addresses(me: dict, organization: dict) -> list[str]:
    """The account's mailbox address and sign-in name, each only when its
    domain is one the account's own directory has verified."""
    verified = {(d.get("name") or "").lower()
                for org in organization.get("value") or []
                for d in org.get("verifiedDomains") or []}
    out = []
    for address in (me.get("mail"), me.get("userPrincipalName")):
        address = (address or "").strip().lower()
        if "@" in address and address.rsplit("@", 1)[1] in verified and address not in out:
            out.append(address)
    return out


def callback(request):
    """Reached from `views_microsoft.microsoft_callback` when `is_sign_in`."""
    request.session.pop(STATE_KEY, None)
    if request.GET.get("error") or not request.GET.get("code"):
        return _refuse(request, "Microsoft did not complete the sign-in. Start again.")
    try:
        tokens = microsoft_oauth.exchange_code(request.GET["code"], scopes=SIGN_IN_SCOPES)
        token = tokens["access_token"]
        me = microsoft_oauth.graph_get(token, "/me", {"$select": "id,mail,userPrincipalName"})
        organization = microsoft_oauth.graph_get(token, "/organization",
                                                 {"$select": "id,verifiedDomains"})
    except (microsoft_oauth.MicrosoftOAuthError, KeyError, ValueError):
        return _refuse(request, "Microsoft could not confirm who you are. Start again.")

    claims = microsoft_oauth.id_claims(tokens)
    directory = str(claims.get("tid") or "")
    account = str(claims.get("oid") or me.get("id") or "")
    found = [m for m in (_staff(a) for a in believed_addresses(me, organization)) if m]
    users = {m.user_id for m in found}
    if len(users) != 1 or not directory or not account:
        return _refuse(request, NO_ACCESS)
    user = found[0].user
    if not user.is_active:
        return _refuse(request, NO_ACCESS)
    bound = (user.microsoft_directory_id, user.microsoft_object_id)
    if any(bound) and bound != (directory, account):
        # The address is right but the work account is not the one this
        # person signed in with before: refused, and said plainly.
        return _refuse(request, "That Microsoft account is not the one this address signed "
                                "in with before. Ask the practice owner.")
    user.microsoft_directory_id, user.microsoft_object_id = directory, account
    user.last_login_at = timezone.now()
    user.save(update_fields=["microsoft_directory_id", "microsoft_object_id",
                             "last_login_at", "updated_at"])
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return HttpResponseRedirect(settings.APP_ROOT_URL)


def _refuse(request, message: str):
    from django.contrib import messages

    messages.error(request, message)
    return HttpResponseRedirect(reverse("login-refused"))
