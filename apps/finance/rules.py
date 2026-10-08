"""Rules remembered from the owner's own choices (`p5_finance_accounting.md`
§4.4): "lines whose description contains ADOBE are Software and
subscriptions". Applied in the next import's dry run, and shown beside the row
each one decided. No AI is used."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Max

from apps.finance.models import FinanceRule
from apps.finance.services import FinanceError, audit

As = FinanceRule.As


@transaction.atomic
def save_rule(tenant, *, actor, rule=None, contains=None, treat_as=None, category=...,
              other_account=..., account=..., payee_contact=..., is_active=None):
    made = rule is None
    if made:
        last = FinanceRule.all_objects.filter(tenant=tenant).aggregate(
            last=Max("position"))["last"]
        rule = FinanceRule(tenant=tenant, position=(last + 1) if last is not None else 0)
        if contains is None:
            raise FinanceError("A rule needs the text to look for.")
    if contains is not None:
        contains = " ".join(str(contains).split())
        if len(contains) < 3:
            raise FinanceError("The text a rule looks for is three characters or more: "
                               "anything shorter matches too much.")
        if len(contains) > 120:
            raise FinanceError("The text a rule looks for is 120 characters at most.")
        rule.contains = contains
    if treat_as is not None:
        if treat_as not in As.values:
            raise FinanceError("treat_as is category, transfer or ignore.")
        rule.treat_as = treat_as
    for field, value in (("category", category), ("other_account", other_account),
                         ("account", account), ("payee_contact", payee_contact)):
        if value is ...:
            continue
        if value is not None and value.tenant_id != tenant.pk:
            raise FinanceError("That is not in this practice.", status=404)
        setattr(rule, field, value)
    if is_active is not None:
        rule.is_active = bool(is_active)
    if rule.treat_as == As.CATEGORY:
        if rule.category is None or rule.category.archived_at is not None:
            raise FinanceError("Choose the category this rule gives a line.")
        rule.other_account = None
    elif rule.treat_as == As.TRANSFER:
        if rule.other_account is None:
            raise FinanceError("Choose the account this rule's transfers are to or from.")
        rule.category = rule.payee_contact = None
    else:
        rule.category = rule.other_account = rule.payee_contact = None
    clash = FinanceRule.all_objects.filter(tenant=tenant, contains__iexact=rule.contains,
                                           account=rule.account).exclude(pk=rule.pk)
    if clash.exists():
        if made:
            # Chosen again in a dry run: the newer choice stands.
            clash.delete()
        else:
            raise FinanceError(f"There is already a rule for “{rule.contains}”.", status=409)
    rule.save()
    audit(tenant, "rule_created" if made else "rule_changed", actor, rule,
          contains=rule.contains, treat_as=rule.treat_as,
          category=str(rule.category_id or ""))
    return rule


@transaction.atomic
def delete_rule(rule, *, actor) -> None:
    audit(rule.tenant, "rule_deleted", actor, rule, contains=rule.contains)
    rule.delete()
