"""Global search (FR-1.33) — Postgres full-text, tenant-scoped.

Phase 1 covers contacts and companies. Notes join the index in Phase 2, when
`note.search_vector` and PIN gating land together: FR-2.11 requires locked
notes be excluded AT INDEX TIME rather than filtered at query time, and building
the index before PINs exist would mean building it the wrong way.
"""

from __future__ import annotations

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import Q, Value

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


def search(tenant, term, *, limit=50):
    """Returns {"contacts": [...], "companies": [...]}. Tenant-scoped by the
    manager; the explicit tenant filter is belt and braces."""
    if not term or not term.strip():
        return {"contacts": [], "companies": []}

    query = SearchQuery(term, search_type="websearch")
    contacts = list(
        Contact.objects.filter(deleted_at__isnull=True)
        .filter(Q(search_vector=query) | Q(tags__contains=[term]))
        .annotate(rank=SearchRank("search_vector", query))
        .order_by("-rank")[:limit]
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
