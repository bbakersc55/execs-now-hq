"""The invoice as a document (`docs/p4a_client_invoicing.md` §2).

Made once, when the invoice is made ready, and stored. It is never made again
for a sent invoice: what a client downloads next year is what they were
emailed. Payment status is shown beside it on screen and is not printed on it.
"""

from __future__ import annotations

from django.template.loader import render_to_string

from apps.billing import money
from apps.billing.models import ClientInvoiceLine

PURPOSE = "invoice_pdf"


def context_for(invoice) -> dict:
    from apps.crm.services import email_layout

    brand = email_layout.branding(invoice.tenant)
    lines = [{
        "description": line.description,
        # 1.00 reads as 1; 1.50 stays 1.5.
        "quantity": f"{line.quantity.normalize():f}",
        "unit_price": money.dollars(line.unit_price_cents),
        "amount": money.dollars(line.amount_cents),
    } for line in ClientInvoiceLine.all_objects.filter(invoice=invoice)
        .order_by("position", "created_at")]
    long_date = lambda day: f"{day:%B} {day.day}, {day.year}"  # noqa: E731
    return {
        "brand": brand,
        "practice": brand.display_name or brand.practice_name,
        "number": invoice.number,
        "issue_date": long_date(invoice.issue_date),
        "due_date": long_date(invoice.due_date),
        "bill_to": invoice.bill_to or {},
        "lines": lines,
        "subtotal": money.dollars(invoice.subtotal_cents),
        "tax": money.dollars(invoice.tax_cents) if invoice.tax_cents else "",
        "total": money.dollars(invoice.total_cents),
        "notes": invoice.notes,
        "terms": invoice.terms,
        "pay_instructions": invoice.pay_instructions,
        # Empty until P4's NMI phase; nothing prints for it while it is.
        "pay_url": invoice.pay_url,
    }


def render_html(invoice) -> str:
    from apps.crm.services import email_layout

    html = render_to_string("billing/invoice.html", context_for(invoice))
    html, _inline = email_layout.with_logo(html, invoice.tenant, as_data_uri=True)
    return html


def render_pdf(invoice) -> bytes:
    from weasyprint import HTML

    return HTML(string=render_html(invoice)).write_pdf()


def store(invoice):
    from apps.tenancy import storage

    name = f"Invoice-{invoice.number}.pdf"
    return storage.save(
        tenant=invoice.tenant, content=render_pdf(invoice),
        object_key=storage.object_key("invoices", name), purpose=PURPOSE,
        content_type="application/pdf")
