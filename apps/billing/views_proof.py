"""The token proof's page (P4 part 1): NMI's own card fields, on the laptop,
against the sandbox. **Not a product screen.** It exists only where
APP_ENVIRONMENT is local, NMI_ENVIRONMENT is sandbox and NMI_LIVE_CALLS is on;
anywhere else both addresses are 404. `scripts/nmi_token_proof.py` drives it.

The card is typed into NMI's frames, never into this page, so this server
receives only the one-time tokens NMI's Payment Component returns. With two
of them it runs the path the product will: a sale on a token, a partial
refund, the sale read back by our reference, a card stored in the vault, a
sale on the vault record, its refund, and the record deleted.
"""

from __future__ import annotations

import json
import uuid

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.utils.html import json_script
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.billing import gateway as gw

#: NMI's Payment Component, pinned. Part 2 bundles the same package.
COMPONENT = ("https://cdn.jsdelivr.net/npm/@nmipayments/nmi-pay@1.1.1/dist/"
             "nmi-payments-cdn.iife.js")

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>NMI token proof</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="%(component)s"></script></head>
<body style="font-family: sans-serif; max-width: 40rem; margin: 2rem auto">
<h1>NMI token proof (sandbox)</h1>
<p id="step">Card 1 of 2: the sale.</p>
<div id="pc"></div>
<pre id="result"></pre>
%(config)s
<script>
const config = JSON.parse(document.getElementById("nmi-config").textContent);
const tokens = [];
function mount() {
  const box = document.getElementById("pc");
  box.innerHTML = "";
  mountNmiPayments(box, {
    tokenizationKey: config.public_key, paymentMethods: ["card"], payButtonText: "Pay",
    onPay: async (event) => {
      tokens.push(event.token);
      if (tokens.length < 2) {
        document.getElementById("step").textContent = "Card 2 of 2: the vault.";
        setTimeout(mount, 0);
        return true;
      }
      document.getElementById("step").textContent = "Running the proof.";
      const response = await fetch(config.run_url, {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({sale_token: tokens[0], vault_token: tokens[1]})});
      document.getElementById("result").textContent = await response.text();
      return true;
    },
  });
}
mount();
</script></body></html>"""


def _allowed() -> bool:
    return (settings.APP_ENVIRONMENT == "local" and settings.NMI_ENVIRONMENT == "sandbox"
            and gw.live_calls_allowed())


@require_GET
def proof_page(request):
    if not _allowed():
        raise Http404
    config = json_script({"public_key": gw.platform_account().public_key,
                          "run_url": "/dev/nmi-proof/run"}, "nmi-config")
    return HttpResponse(PAGE % {"component": COMPONENT, "config": config})


@csrf_exempt
@require_POST
def proof_run(request):
    if not _allowed():
        raise Http404
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"detail": "Not JSON."}, status=400)
    sale_token, vault_token = data.get("sale_token"), data.get("vault_token")
    if not isinstance(sale_token, str) or not isinstance(vault_token, str):
        return JsonResponse({"detail": "Two tokens are needed."}, status=400)

    gateway, account = gw.gateway(), gw.platform_account()
    reference = f"proof-{uuid.uuid4().hex[:12]}"
    # NMI refuses the same card for the same amount again within minutes as
    # a duplicate, so each run's amounts differ: $10.00–$18.99 and $1.01–$1.99.
    seed = uuid.uuid4().int
    amount, on_vault_amount = 1000 + seed % 900, 101 + (seed >> 16) % 99
    steps = []

    def step(name, txn=None, **extra):
        row = {"step": name, **extra}
        if txn is not None:
            row.update(transaction_id=txn.id, approved=txn.approved, status=txn.status,
                       response_code=txn.response_code, amount_cents=txn.amount_cents,
                       reference=txn.reference, card=f"{txn.card_type} {txn.last4}".strip())
        steps.append(row)

    try:
        sale = gateway.sale(account, amount_cents=amount, reference=reference,
                            payment_token=sale_token)
        step("sale on a token", sale)
        step("partial refund, unsettled",
             gateway.refund(account, transaction_id=sale.id, amount_cents=200))
        step("sale read back", gateway.get_transaction(account, sale.id))
        step("refund of the rest",
             gateway.refund(account, transaction_id=sale.id, amount_cents=amount - 200))
        record = gateway.vault_add(account, payment_token=vault_token,
                                   billing=gw.Billing("Sandbox", "Proof"))
        step("card stored in the vault", vault_id=record.id, last4=record.last4,
             card_exp=record.card_exp)
        on_vault = gateway.sale(account, amount_cents=on_vault_amount,
                                reference=f"{reference}-vault",
                                vault_id=record.id)
        step("sale on the vault record", on_vault)
        step("its refund", gateway.refund(account, transaction_id=on_vault.id,
                                          amount_cents=on_vault_amount))
        gateway.vault_delete(account, record.id)
        step("vault record deleted", vault_id=record.id)
    except gw.GatewayError as exc:
        return JsonResponse({"ok": False, "reference": reference, "steps": steps,
                             "error": account.scrub(str(exc))}, status=502)
    return JsonResponse({"ok": True, "reference": reference, "environment": account.environment,
                         "steps": steps})
