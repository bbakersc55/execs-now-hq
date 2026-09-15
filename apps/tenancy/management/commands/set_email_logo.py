"""Set (or clear) the images in app-originated email.

    manage.py set_email_logo path/to/logo.png [--tenant SLUG] [--dry-run]
    manage.py set_email_logo path/to/mark.png --mark [--tenant SLUG] [--dry-run]
    manage.py set_email_logo --clear [--mark] [--tenant SLUG]

- The **logo** sits in the white header of the base layout, fitted into
  220 x 80 px.
- The **mark** (``--mark``) is the square symbol beside the sign-off on mail
  from a person, fitted into 56 x 56 px.

PNG or JPEG, at most 500 KB. Supply each at about twice the size it should show;
it is never enlarged. Files are kept in media storage like the marketing flyer;
a replaced file is left in place (storage never overwrites or deletes on a
re-upload).

Beta sets these from the terminal, as the colours are set on the tenant row; a
Settings screen for them is V1.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Set or clear the email header logo, or the sign-off mark, for a tenant."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", help="PNG or JPEG file")
        parser.add_argument("--mark", action="store_true",
                            help="The sign-off mark rather than the header logo")
        parser.add_argument("--tenant", help="Tenant slug (optional when there is one tenant)")
        parser.add_argument("--clear", action="store_true", help="Remove it")
        parser.add_argument("--dry-run", action="store_true",
                            help="Check the file and show the size it will display at")

    def handle(self, *args, **options):
        from apps.crm.services import email_layout
        from apps.tenancy import storage
        from apps.tenancy.models import Tenant

        tenant = self._tenant(Tenant, options["tenant"])
        mark = options["mark"]
        field = "email_mark" if mark else "email_logo"
        what = "sign-off mark" if mark else "logo"
        fields = [field, f"{field}_width", f"{field}_height", "updated_at"]

        if options["clear"]:
            if options["path"]:
                raise CommandError("Give a file or --clear, not both.")
            setattr(tenant, field, None)
            setattr(tenant, f"{field}_width", 0)
            setattr(tenant, f"{field}_height", 0)
            tenant.save(update_fields=fields)
            self.stdout.write(f"{tenant.name}: {what} cleared.")
            return
        if not options["path"]:
            raise CommandError("Give the image file, or --clear.")

        path = Path(options["path"]).expanduser()
        if not path.is_file():
            raise CommandError(f"No file at {path}.")
        content = path.read_bytes()
        if len(content) > email_layout.LOGO_MAX_BYTES:
            raise CommandError(
                f"{path.name} is {len(content) // 1024} KB; the limit is "
                f"{email_layout.LOGO_MAX_BYTES // 1024} KB. Large images slow every email "
                "and some clients clip them.")
        try:
            content_type, width, height = email_layout.image_size(content)
            if mark:
                display = email_layout.logo_display_size(
                    width, height, max_width=email_layout.MARK_MAX,
                    max_height=email_layout.MARK_MAX)
            else:
                display = email_layout.logo_display_size(width, height)
        except ValueError as exc:
            raise CommandError(f"{path.name}: {exc}") from exc

        summary = (f"{path.name}: {content_type}, {width} x {height} px, "
                   f"shown at {display[0]} x {display[1]} px")
        if options["dry_run"]:
            self.stdout.write(f"{tenant.name}: would set the {what} — {summary}.")
            return

        extension = "jpg" if content_type == "image/jpeg" else "png"
        name = "email-mark" if mark else "email-logo"
        stored = storage.save(
            tenant=tenant, content=content,
            object_key=storage.object_key(f"branding/{tenant.slug}", f"{name}.{extension}"),
            content_type=content_type, purpose=field,
        )
        setattr(tenant, field, stored)
        setattr(tenant, f"{field}_width", display[0])
        setattr(tenant, f"{field}_height", display[1])
        tenant.save(update_fields=fields)
        self.stdout.write(f"{tenant.name}: {what} set — {summary}.")

    def _tenant(self, Tenant, slug):
        if slug:
            tenant = Tenant.objects.filter(slug=slug).first()
            if tenant is None:
                raise CommandError(f"No tenant with slug {slug!r}.")
            return tenant
        tenants = list(Tenant.objects.all()[:2])
        if len(tenants) != 1:
            raise CommandError("More than one tenant (or none): pass --tenant SLUG.")
        return tenants[0]
