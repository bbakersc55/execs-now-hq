"""The SOP studio's routes (P10). Every company route goes through the plans
engine's reach rule (`apps.sops.access`): 404 for anyone who doesn't reach the
company, and for every practice with no Command Center on. A client user
reaches a published SOP only when they are in its audience (or own the
company); anything else is 404.

GET    /api/sops/?company=&q=&status=&category=&kpi=   the shelf, or a company's card
POST   /api/sops/                               {company, title, ...}: a new draft
GET    /api/sops/<id>/                          the practice's whole view; the portal's version
PATCH  /api/sops/<id>/                          edit the working copy
POST   /api/sops/<id>/<publish|archive|restore|ack|remind|suggest>/
POST   /api/sops/<id>/comments/<cid>/resolve/
POST   /api/sops/<id>/attachments/              an image or a PDF (multipart "file")
GET    /api/sops/<id>/attachments/<aid>/        the file
DELETE /api/sops/<id>/attachments/<aid>/
GET    /api/sops/<id>/files/<pdf|docx>/?version=n
POST   /api/sops/map/                           {text} -> {svg, errors}; {steps} -> {text}

GET    /api/sops/brainstorms/?company=
POST   /api/sops/brainstorms/                   {company, title?, sop?, note?, run?}
GET    /api/sops/brainstorms/<id>/
PATCH  /api/sops/brainstorms/<id>/              {title, tier}
POST   /api/sops/brainstorms/<id>/price/        {kind, message}: the price first
POST   /api/sops/brainstorms/<id>/send/         {text}
POST   /api/sops/brainstorms/<id>/act/<draft|map|checklist|measures>/
POST   /api/sops/brainstorms/<id>/sources/      {kind: pasted|note|run|sop, ...} or a file
DELETE /api/sops/brainstorms/<id>/sources/<sid>/
POST   /api/sops/brainstorms/<id>/sources/<sid>/read/   a video or audio file, read on
POST   /api/sops/brainstorms/<id>/media/        a video or audio file (multipart: file, seconds, keep)
POST   /api/sops/brainstorms/<id>/proposals/<pid>/<accept|discard>/   {edits}

GET    /api/sops/pack/?company=                 what may go in; the prompts
POST   /api/sops/pack/                          {company, runs, documents}: the zip
PUT    /api/sops/pack/prompts/                  {prompts} (practice owner)
DELETE /api/sops/pack/prompts/                  back to the Command Center's

GET    /api/ai-media-key/                       the media key's state (practice owner)
POST   /api/ai-media-key/                       {key}: tested, then saved
POST   /api/ai-media-key/test/
DELETE /api/ai-media-key/
"""

from __future__ import annotations

from django.http import Http404, HttpResponse
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tenancy.models import CLIENT_ROLES, Role, TENANT_ROLES

from . import access as A
from . import brainstorm as B
from . import exports, flow, media, pack, services
from .models import Brainstorm, Sop, SopAttachment, SopVersion


class Base(APIView):
    permission_classes = [permissions.IsAuthenticated]


def _refused(exc):
    body = {"detail": str(exc)}
    if getattr(exc, "errors", None):
        body["errors"] = exc.errors
    return Response(body, status=getattr(exc, "status", 400))


REFUSALS = (services.SopRefused, B.BrainstormRefused, media.MediaRefused, pack.PackRefused)


def _staff(request):
    membership = getattr(request, "membership", None)
    if membership is None or membership.role not in TENANT_ROLES \
            or not A.available(membership.tenant_id):
        raise Http404
    return membership


def _file(content, mime, name, inline=False):
    response = HttpResponse(content, content_type=mime)
    response["Content-Disposition"] = f'{"inline" if inline else "attachment"}; filename="{name}"'
    response["Cache-Control"] = "no-store"
    return response


DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ------------------------------------------------------------------ SOPs

class SopsView(Base):
    def get(self, request):
        membership = getattr(request, "membership", None)
        if membership is None or not A.available(membership.tenant_id):
            raise Http404
        params = request.query_params
        company = None
        if params.get("company") and membership.role not in CLIENT_ROLES:
            company = A.company_for(request, params["company"])
        rows = services.list_for(request, company=company, q=(params.get("q") or "").strip(),
                                 status=params.get("status") or "",
                                 category=params.get("category") or "")
        kpi = params.get("kpi")
        if kpi:
            if not A._is_uuid(kpi):
                raise Http404
            linked = {str(s) for s in Sop.objects.filter(kpi_links__kpi_id=kpi)
                      .values_list("pk", flat=True)}
            rows = [r for r in rows if r["id"] in linked]
        out = {"sops": rows, "may_create": membership.role in (Role.FF, Role.CF, Role.VA)}
        if membership.role not in CLIENT_ROLES:
            out["categories"] = sorted({r["category"] for r in rows if r["category"]},
                                       key=str.lower)
        return Response(out)

    def post(self, request):
        _staff(request)
        access = A.access_for(request, request.data.get("company") or "")
        if not access.drafts:
            return Response({"detail": "The practice writes SOPs."}, status=403)
        try:
            sop = services.create(access.company, actor=request.user,
                                  title=request.data.get("title"),
                                  data={k: v for k, v in request.data.items()
                                        if k not in ("company", "title")} or None)
        except services.SopRefused as exc:
            return _refused(exc)
        return Response(services.full(sop, access), status=201)


class SopView(Base):
    def get(self, request, pk):
        sop, access = A.sop_for(request, pk)
        if access.is_client:
            return Response(services.portal_view(sop, request.membership, access))
        return Response(services.full(sop, access))

    def patch(self, request, pk):
        sop, access = A.sop_for(request, pk)
        if not access.drafts:
            return Response({"detail": "The practice edits an SOP."}, status=403)
        if sop.status == Sop.Status.ARCHIVED:
            return Response({"detail": "Restore it before editing."}, status=409)
        try:
            services.update(sop, request.data, actor=request.user)
        except services.SopRefused as exc:
            return _refused(exc)
        sop.refresh_from_db()
        return Response(services.full(sop, access))


class SopActionView(Base):
    def post(self, request, pk, action):
        sop, access = A.sop_for(request, pk)
        try:
            if action == "ack":
                if not access.is_client:
                    return Response({"detail": "Someone the SOP is published to reads it."},
                                    status=403)
                done = services.acknowledge(sop, membership=request.membership,
                                            user=request.user)
                return Response({**done, "sop": services.portal_view(
                    sop, request.membership, access)})
            if action == "suggest":
                comment = services.suggest(sop, membership=request.membership,
                                           user=request.user, text=request.data.get("text"))
                return Response({"id": str(comment.pk)}, status=201)
            if action == "remind":
                if not access.reminds:
                    return Response({"detail": "The practice, or the client owner, reminds."},
                                    status=403)
                return Response(services.remind(sop, actor=request.user, role=access.role),
                                status=201)
            if access.is_client:
                raise Http404
            if action == "publish":
                if not access.publishes:
                    return Response({"detail": "The practice owner or an associate publishes; "
                                               "an assistant drafts."}, status=403)
                services.publish(sop, actor=request.user,
                                 change_note=request.data.get("change_note") or "",
                                 minor=bool(request.data.get("minor")))
            elif action in ("archive", "restore"):
                if not access.publishes:
                    return Response({"detail": "The practice owner or an associate archives."},
                                    status=403)
                (services.archive if action == "archive" else services.restore)(
                    sop, actor=request.user)
            else:
                raise Http404
        except REFUSALS as exc:
            return _refused(exc)
        sop.refresh_from_db()
        return Response(services.full(sop, access))


class SopCommentView(Base):
    def post(self, request, pk, cid):
        sop, access = A.sop_for(request, pk)
        if not access.drafts:
            raise Http404
        try:
            services.resolve(sop, cid, actor=request.user)
        except services.SopRefused as exc:
            return _refused(exc)
        return Response(services.full(sop, access))


class AttachmentsView(Base):
    def post(self, request, pk):
        sop, access = A.sop_for(request, pk)
        if not access.drafts:
            return Response({"detail": "The practice edits an SOP."}, status=403)
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "Choose a file."}, status=400)
        try:
            a = services.attach(sop, upload, actor=request.user)
        except services.SopRefused as exc:
            return _refused(exc)
        return Response({"id": str(a.pk), "name": a.name, "kind": a.kind,
                         "url": f"/api/sops/{sop.pk}/attachments/{a.pk}/"}, status=201)


class AttachmentView(Base):
    def get(self, request, pk, aid):
        from apps.tenancy import storage

        sop, access = A.sop_for(request, pk)
        if not A._is_uuid(aid):
            raise Http404
        if access.is_client:
            version = services.latest(sop)
            if str(aid) not in {a["id"] for a in version.snapshot.get("attachments", [])}:
                raise Http404
        a = SopAttachment.objects.filter(sop=sop, pk=aid).select_related("file").first()
        if a is None:
            raise Http404
        try:
            content = storage.read(a.file)
        except storage.StorageError as exc:
            return Response({"detail": f"The file couldn't be read just now: {exc}"},
                            status=503)
        return _file(content, a.file.content_type or "application/octet-stream", a.name,
                     inline=True)

    def delete(self, request, pk, aid):
        sop, access = A.sop_for(request, pk)
        if not access.drafts:
            return Response({"detail": "The practice edits an SOP."}, status=403)
        try:
            services.detach(sop, aid, actor=request.user)
        except services.SopRefused as exc:
            return _refused(exc)
        return Response(status=204)


class SopFileView(Base):
    def get(self, request, pk, kind):
        sop, access = A.sop_for(request, pk)
        version = None
        if access.is_client:
            version = services.latest(sop)
        elif request.query_params.get("version"):
            version = SopVersion.objects.filter(
                sop=sop, number=request.query_params["version"]).first() \
                if str(request.query_params["version"]).isdigit() else None
            if version is None:
                raise Http404
        if kind == "pdf":
            return _file(exports.pdf(sop, request.user, version), "application/pdf",
                         exports.filename(sop, "pdf", version))
        if kind == "docx":
            return _file(exports.docx(sop, version), DOCX, exports.filename(sop, "docx", version))
        raise Http404


class MapView(Base):
    def post(self, request):
        _staff(request)
        if "steps" in request.data:
            return Response({"text": flow.from_steps(request.data.get("steps") or [])})
        text = str(request.data.get("text") or "")
        errors = flow.check(text) if text.strip() else []
        return Response({"errors": errors,
                         "svg": None if errors or not text.strip() else flow.svg(text)})


# ------------------------------------------------------------------ brainstorms

def _brainstorm_for(request, pk) -> tuple[Brainstorm, A.SopAccess]:
    _staff(request)
    if not A._is_uuid(pk):
        raise Http404
    found = Brainstorm.objects.filter(pk=pk, archived_at__isnull=True) \
        .select_related("company", "sop").first()
    if found is None:
        raise Http404
    access = A.access_for(request, "practice" if found.company.is_practice else found.company_id)
    if not access.drafts:
        raise Http404
    return found, access


class BrainstormsView(Base):
    def get(self, request):
        _staff(request)
        access = A.access_for(request, request.query_params.get("company") or "")
        rows = Brainstorm.objects.filter(company=access.company, archived_at__isnull=True) \
            .select_related("sop")
        return Response({"brainstorms": [
            {"id": str(b.pk), "title": b.title, "updated_at": b.updated_at.isoformat(),
             "sop": {"id": str(b.sop_id), "title": b.sop.title} if b.sop_id else None}
            for b in rows]})

    def post(self, request):
        from apps.notes.models import Note
        from apps.tools.models import ToolRun

        _staff(request)
        data = request.data
        note = run = sop = None
        company_id = data.get("company") or ""
        if data.get("note"):
            note = Note.objects.filter(pk=data["note"], deleted_at__isnull=True).first() \
                if A._is_uuid(data["note"]) else None
            if note is None:
                raise Http404
            if note.pin_hash:
                return Response({"detail": "A PIN-locked note is never a source."}, status=409)
            if not company_id:
                company_id = str(note.company_id) if note.company_id else "practice"
        if data.get("run"):
            run = ToolRun.objects.filter(pk=data["run"], archived_at__isnull=True) \
                .select_related("company").first() if A._is_uuid(data["run"]) else None
            if run is None:
                raise Http404
            company_id = "practice" if run.company.is_practice else str(run.company_id)
        if data.get("sop"):
            sop, _ = A.sop_for(request, data["sop"])
            company_id = "practice" if sop.company.is_practice else str(sop.company_id)
        access = A.access_for(request, company_id)
        if not access.drafts:
            return Response({"detail": "The practice brainstorms an SOP."}, status=403)
        if run is not None and run.company_id != access.company.pk:
            raise Http404
        title = data.get("title") or (f"SOP from {note.title}" if note is not None and note.title
                                      else run.name if run is not None else "")
        try:
            found = B.start(access.company, actor=request.user, title=title, sop=sop,
                            tier=data.get("tier"))
            if note is not None:
                B.add_note(found, note, actor=request.user)
            if run is not None:
                B.add_tool_run(found, run, actor=request.user)
        except B.BrainstormRefused as exc:
            return _refused(exc)
        return Response(B.represent(found), status=201)


class BrainstormView(Base):
    def get(self, request, pk):
        found, _ = _brainstorm_for(request, pk)
        return Response(B.represent(found))

    def patch(self, request, pk):
        found, _ = _brainstorm_for(request, pk)
        if "title" in request.data:
            title = " ".join(str(request.data.get("title") or "").split())[:200]
            if not title:
                return Response({"detail": "A brainstorm needs a title."}, status=400)
            found.title = title
        if "tier" in request.data:
            if request.data["tier"] not in Brainstorm.Tier.values:
                return Response({"detail": "The tier is Standard or Deep."}, status=400)
            found.tier = request.data["tier"]
        found.save()
        return Response(B.represent(found))

    def delete(self, request, pk):
        from django.utils import timezone

        found, _ = _brainstorm_for(request, pk)
        found.archived_at = timezone.now()
        found.save(update_fields=["archived_at", "updated_at"])
        return Response(status=204)


class BrainstormActionView(Base):
    def post(self, request, pk, action, kind=None):
        found, access = _brainstorm_for(request, pk)
        try:
            if action == "price":
                kind = request.data.get("kind") or "chat"
                if kind not in B.PURPOSE_OF:
                    return Response({"detail": "That isn't one of the brainstorm's actions."},
                                    status=400)
                return Response({**B.price(found, kind, request.data.get("message") or ""),
                                 "refused": B.refusal(found.company.tenant),
                                 "spent_usd": str(B.spent(found))})
            if action == "send":
                B.send(found, request.data.get("text"), actor=request.user)
            elif action == "act":
                B.act(found, kind, actor=request.user)
            elif action == "media":
                upload = request.FILES.get("file")
                if upload is None:
                    return Response({"detail": "Choose a video or audio file."}, status=400)
                media.upload(found, upload, seconds=request.data.get("seconds"),
                             keep=str(request.data.get("keep") or "").lower() in ("1", "true",
                                                                                 "yes", "on"),
                             actor=request.user)
            elif action == "sources":
                self._source(request, found)
            else:
                raise Http404
        except REFUSALS as exc:
            return _refused(exc)
        found.refresh_from_db()
        return Response(B.represent(found), status=201 if action != "price" else 200)

    def _source(self, request, found):
        from apps.notes.models import Note
        from apps.tools.models import ToolRun

        upload = request.FILES.get("file")
        if upload is not None:
            return B.add_upload(found, upload, actor=request.user)
        kind = request.data.get("kind")
        ident = request.data.get("id")
        if kind == "pasted":
            return B.add_pasted(found, title=request.data.get("title"),
                                text=request.data.get("text"), actor=request.user)
        if kind == "note":
            note = Note.objects.filter(pk=ident, deleted_at__isnull=True).first() \
                if A._is_uuid(ident) else None
            if note is None or (note.company_id and note.company_id != found.company_id
                                and not found.company.is_practice):
                raise B.BrainstormRefused("That note isn't one of this company's.", 404)
            return B.add_note(found, note, actor=request.user)
        if kind == "run":
            run = ToolRun.objects.filter(pk=ident, company=found.company,
                                         archived_at__isnull=True).first() \
                if A._is_uuid(ident) else None
            if run is None:
                raise B.BrainstormRefused("That run isn't one of this company's.", 404)
            return B.add_tool_run(found, run, actor=request.user)
        if kind == "sop":
            sop = Sop.objects.filter(pk=ident, company=found.company).first() \
                if A._is_uuid(ident) else None
            if sop is None:
                raise B.BrainstormRefused("That SOP isn't one of this company's.", 404)
            return B.add_sop(found, sop, actor=request.user)
        raise B.BrainstormRefused("Paste text, or add a file, a note, a run or an SOP.")


class BrainstormSourceView(Base):
    def delete(self, request, pk, sid):
        found, _ = _brainstorm_for(request, pk)
        try:
            B.remove_source(found, sid)
        except B.BrainstormRefused as exc:
            return _refused(exc)
        return Response(status=204)

    def post(self, request, pk, sid):
        """Read a video or audio file on: still being read, failed, or ready."""
        from .models import BrainstormSource

        found, _ = _brainstorm_for(request, pk)
        source = BrainstormSource.objects.filter(brainstorm=found, pk=sid).first() \
            if A._is_uuid(sid) else None
        if source is None:
            raise Http404
        try:
            media.read(source)
        except media.MediaRefused as exc:
            return _refused(exc)
        found.refresh_from_db()
        return Response(B.represent(found))


class ProposalView(Base):
    def post(self, request, pk, pid, decision):
        found, access = _brainstorm_for(request, pk)
        try:
            if decision == "accept":
                B.accept(found, pid, actor=request.user, role=access.role,
                         edits=request.data.get("edits"))
            elif decision == "discard":
                B.discard(found, pid, actor=request.user)
            else:
                raise Http404
        except REFUSALS as exc:
            return _refused(exc)
        found.refresh_from_db()
        return Response(B.represent(found))


# ------------------------------------------------------------------ the Notebook pack

def _packer(request, company_id):
    _staff(request)
    access = A.access_for(request, company_id)
    if access.role not in (Role.FF, Role.CF):
        raise Http404
    return access


class PackView(Base):
    def get(self, request):
        access = _packer(request, request.query_params.get("company") or "")
        return Response({**pack.choices(access.company),
                         "prompts": pack.prompts(access.company.tenant_id),
                         "may_edit_prompts": access.role == Role.FF})

    def post(self, request):
        access = _packer(request, request.data.get("company") or "")
        try:
            content, _ = pack.build(access.company, actor=request.user,
                                    runs=request.data.get("runs") or [],
                                    documents=request.data.get("documents") or [])
        except pack.PackRefused as exc:
            return _refused(exc)
        return _file(content, "application/zip", pack.filename(access.company))


class PackPromptsView(Base):
    def put(self, request):
        membership = _staff(request)
        if membership.role != Role.FF:
            return Response({"detail": "The practice owner edits the prompts."}, status=403)
        try:
            return Response({"prompts": pack.save_prompts(membership.tenant,
                                                          request.data.get("prompts"),
                                                          actor=request.user)})
        except pack.PackRefused as exc:
            return _refused(exc)

    def delete(self, request):
        membership = _staff(request)
        if membership.role != Role.FF:
            return Response({"detail": "The practice owner edits the prompts."}, status=403)
        return Response({"prompts": pack.reset_prompts(membership.tenant)})


# ------------------------------------------------------------------ the media key

class MediaKeyView(Base):
    def _owner(self, request):
        membership = getattr(request, "membership", None)
        if membership is None or membership.role != Role.FF:
            raise Http404
        return membership

    def get(self, request):
        membership = self._owner(request)
        return Response(media.status(membership.tenant))

    def post(self, request, action=None):
        membership = self._owner(request)
        try:
            if action == "test":
                return Response(media.check_saved(membership.tenant))
            return Response(media.save_key(membership.tenant, request.data.get("key") or "",
                                           actor=request.user))
        except media.MediaRefused as exc:
            body = {"detail": str(exc) + ("" if action == "test" else
                                          " The key, if one was set, is unchanged.")}
            return Response(body, status=exc.status)

    def delete(self, request):
        membership = self._owner(request)
        return Response(media.remove_key(membership.tenant, actor=request.user))
