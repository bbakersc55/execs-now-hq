"""Global search (FR-1.33) — Postgres full-text, tenant-scoped.

Phase 1 covers contacts and companies. Notes join the index in Phase 2, when
`note.search_vector` and PIN gating land together: FR-2.11 requires locked
notes be excluded AT INDEX TIME rather than filtered at query time, and building
the index before PINs exist would mean building it the wrong way.
"""

from __future__ import annotations

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import Q, Value
from django.db.models.functions import Coalesce

from apps.crm.models import Company, Contact

CONTACT_VECTOR = (
    SearchVector("first_name", weight="A")
    + SearchVector("last_name", weight="A")
    + SearchVector("title", weight="B")
    + SearchVector("background", weight="C")
    + SearchVector("source", weight="D")
)


def reindex_contact(contact):
    Contact.all_objects.filter(pk=contact.pk).update(search_vector=CONTACT_VECTOR)


def reindex_tenant(tenant):
    Contact.all_objects.filter(tenant=tenant).update(search_vector=CONTACT_VECTOR)


def as_typed(term):
    """What a person typing into a box means, which full text alone cannot answer.

    Full-text search matches whole words after stemming, so "Nob" never finds
    "Noble" however well the index is built — the index holds `nobl`, and a
    three-letter prefix is not that word. Email addresses are worse: they live in
    their own table and were never in the vector at all, so searching for an
    address found nobody anywhere in the app.

    So a typed fragment is also matched as a plain prefix on either name and a
    substring of an address, alongside the ranked full-text hit. Full text still
    earns the ranking — it is what searches a title, a background note or a
    source — but it no longer decides on its own whether someone exists.
    """
    term = (term or "").strip()
    if not term:
        return Q(pk__in=[])
    typed = Q(first_name__istartswith=term) | Q(last_name__istartswith=term)
    if len(term) >= 3:
        # An address is matched anywhere inside it, because the useful fragments
        # are in the middle — a domain, a surname after a dot. That only makes
        # sense from three characters up: "a" is in almost every address there is.
        typed |= Q(emails__address__icontains=term)
    parts = term.split()
    if len(parts) == 2:
        # "Dana Rey" — a first name and the start of a last name.
        typed |= Q(first_name__istartswith=parts[0], last_name__istartswith=parts[1])
    return typed


def search(tenant, term, *, limit=50):
    """Returns {"contacts": [...], "companies": [...]}. Tenant-scoped by the
    manager; the explicit tenant filter is belt and braces."""
    if not term or not term.strip():
        return {"contacts": [], "companies": []}

    query = SearchQuery(term, search_type="websearch")
    contacts = list(
        Contact.objects.filter(deleted_at__isnull=True)
        .filter(Q(search_vector=query) | Q(tags__contains=[term]) | as_typed(term))
        # A row that matched on a typed prefix has no full-text rank at all
        # (ts_rank of an unindexed vector is null), and null sorts first under
        # DESC in Postgres — which would put the weakest matches on top.
        .annotate(rank=Coalesce(SearchRank("search_vector", query), Value(0.0)))
        .order_by("-rank", "first_name", "last_name")
        .distinct()[:limit]
    )
    companies = list(
        Company.objects.filter(deleted_at__isnull=True, name__icontains=term)[:limit]
    )
    return {"contacts": contacts, "companies": companies}


def vendors_by_category(tenant, category_name):
    """FR-1.25."""
    return list(
        Contact.objects.filter(
            deleted_at__isnull=True,
            category_links__service_category__name__iexact=category_name,
        ).distinct()
    )
