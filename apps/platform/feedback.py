"""Feedback: the one thing that crosses the practice boundary, and only
because a person wrote it and sent it (P2, owner 2026-10-02).

Staff send it from any screen; it is stored in their practice like any other
row. The platform owner reads it here, through `all_objects`, and this module
returns nothing but the feedback itself: the practice's display name at the
time, the sender's role, the three answers, the page, and whether a
screenshot came with it.
"""

from __future__ import annotations

from apps.platform.models import Feedback
from apps.tenancy.roles import role_label

SCREENSHOT_MAX_BYTES = 5 * 1024 * 1024
FIELD_MAX = 4000


class FeedbackInvalid(ValueError):
    pass


def submit(request, *, doing: str, happened: str, expected: str, page_url: str,
           screenshot=None) -> Feedback:
    from apps.crm.services import email_layout
    from apps.tenancy import storage

    doing, happened, expected = (v.strip()[:FIELD_MAX] for v in (doing, happened, expected))
    if not (doing and happened and expected):
        raise FeedbackInvalid("Say what you were doing, what happened and what you expected.")
    stored = None
    if screenshot is not None:
        if screenshot.size > SCREENSHOT_MAX_BYTES:
            raise FeedbackInvalid("The screenshot is over 5 MB.")
        content = screenshot.read()
        try:
            content_type, _, _ = email_layout.image_size(content)
        except ValueError:
            raise FeedbackInvalid("The screenshot must be a PNG or a JPEG.") from None
        extension = "jpg" if content_type == "image/jpeg" else "png"
        stored = storage.save(
            tenant=request.tenant, content=content, content_type=content_type,
            object_key=storage.object_key(f"feedback/{request.tenant.slug}",
                                          f"screenshot.{extension}"),
            purpose="feedback_screenshot")
    brand = email_layout.branding(request.tenant)
    feedback = Feedback.objects.create(
        tenant=request.tenant, practice_name=brand.display_name or request.tenant.name,
        submitted_by=request.user, role=request.membership.role, doing=doing,
        happened=happened, expected=expected, page_url=(page_url or "")[:500],
        screenshot=stored)
    _notify(feedback)
    return feedback


def _notify(feedback) -> None:
    """Tell the platform owner: the practice's name and the words, nothing
    else. A notice that cannot be sent never loses the feedback itself."""
    from apps.crm.models import OutboxMessage
    from apps.platform import mail

    owner = mail.platform_owner()
    if owner is None:
        return
    try:
        mail._send(to=owner.email, producer=OutboxMessage.Producer.FEEDBACK_NOTICE,
                   subject=f"Feedback from {feedback.practice_name}",
                   paragraphs=[
                       f"{feedback.practice_name} ({role_label(feedback.role)}), on "
                       f"{feedback.page_url or 'an unknown page'}:",
                       f"Doing: {feedback.doing}",
                       f"What happened: {feedback.happened}",
                       f"Expected: {feedback.expected}",
                       "Screenshot attached in the Practices area." if feedback.screenshot_id
                       else "No screenshot.",
                   ])
    except mail.PlatformMailUnavailable:
        pass


def own(request):
    """What this person has sent: their own, in their own practice."""
    return [_row(f) for f in Feedback.objects.filter(submitted_by=request.user)]


def for_platform() -> list[dict]:
    return [_row(f, platform=True) for f in Feedback.all_objects.order_by("-created_at")]


def platform_get(pk):
    return Feedback.all_objects.filter(pk=pk).select_related("screenshot").first()


def _row(f: Feedback, platform: bool = False) -> dict:
    row = {"id": str(f.pk), "doing": f.doing, "happened": f.happened,
           "expected": f.expected, "page_url": f.page_url, "status": f.status,
           "has_screenshot": f.screenshot_id is not None,
           "created_at": f.created_at.isoformat()}
    if platform:
        row.update({"practice_name": f.practice_name, "role": role_label(f.role)})
    return row
