"""Learning this practice's style from its edits (owner, 2026-09-29).

When a person accepts a map row or a pro or con after changing Claude's words,
or edits one already accepted, the pair — what Claude drafted, what they kept —
is stored. The most recent twelve go into the next drafting prompt as examples.

**Per practice, and only ever this practice's**: every read filters by the
tenant being drafted for, explicitly, not only through the tenant context.
The examples are the practice's own words about its own prospects, and they
must never teach another practice's drafts.
"""

from __future__ import annotations

from apps.strategy.models import StrategyStyleExample

K = StrategyStyleExample.Kind
EXAMPLES_IN_PROMPT = 12


def record(tenant, *, kind, proposed, accepted, source):
    """Keep the pair for one drafted item and kind. An edit back to Claude's
    own words removes it: there is nothing left to learn from it."""
    proposed, accepted = (proposed or "").strip(), (accepted or "").strip()
    if not proposed:
        return None                      # written by a person, not a draft
    lookup = dict(tenant=tenant, kind=kind, source_type=source._meta.db_table,
                  source_id=source.pk)
    if not accepted or accepted == proposed:
        StrategyStyleExample.all_objects.filter(**lookup).delete()
        return None
    example, _ = StrategyStyleExample.all_objects.update_or_create(
        **lookup, defaults={"proposed": proposed, "accepted": accepted})
    return example


def record_row(row):
    record(row.tenant, kind=K.MAP_HEADER, proposed=row.proposed_header,
           accepted=row.header, source=row)
    record(row.tenant, kind=K.MAP_STATEMENT, proposed=row.proposed_statement,
           accepted=row.statement, source=row)


def record_note(note):
    record(note.tenant, kind=K.PRO if note.kind == "pro" else K.CON,
           proposed=note.proposed_text, accepted=note.text, source=note)


LABELS = {K.MAP_HEADER: "map row header", K.MAP_STATEMENT: "map row focus statement",
          K.PRO: "pro", K.CON: "con"}


def prompt_block(tenant, kinds) -> str:
    """The practice's twelve most recent edits of these kinds, for the end of
    a drafting prompt. Empty when there are none."""
    pairs = list(StrategyStyleExample.all_objects.filter(tenant=tenant, kind__in=kinds)
                 .order_by("-updated_at")[:EXAMPLES_IN_PROMPT])
    if not pairs:
        return ""
    lines = ["\n\nHow this practice rewrites drafts like these — your version, then "
             "the one they kept. Write in their style: their length, their words, "
             "their tone. These are examples of style only; assert nothing from them "
             "about this prospect."]
    for pair in pairs:
        lines.append(f"- {LABELS[pair.kind]}: drafted \"{pair.proposed}\" → kept "
                     f"\"{pair.accepted}\"")
    return "\n".join(lines)
