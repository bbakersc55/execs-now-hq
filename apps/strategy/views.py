"""Module 4 API — sessions, the live view, the tray, the PDF and conversion.

Access matrix §10 in one place, because scattering it is how a row gets missed:

| | FF | CF | VA |
|---|---|---|---|
| create / schedule, send the invite, view §1–8, generate the PDF | ✅ | their own | ✅ |
| run the live view, draft, accept rows, toggle a flag, send, convert | ✅ | their own | ❌ |
| **§9 investment fields** | ✅ | their own | **absent from the payload** |

A client role reaches none of it, and out-of-scope is 404 rather than 403 — a
403 would confirm the session exists.
"""

from __future__ import annotations

from django.http import Http404, HttpResponse
from django.utils.dateparse import parse_date
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.crm import permissions as crm_perms
from apps.crm.models import Contact
from apps.strategy import ai, conversion, emails, pdf as pdf_service
from apps.strategy import prep as prep_service
from apps.strategy import rewording
from apps.strategy import services
from apps.strategy import serializers as strategy_serializers
from apps.strategy.models import (
    AskWhen, StrategyAnswer, StrategyMapRow, StrategyPathNote, StrategyPrepQuestion,
    StrategySession, StrategySessionPrep, StrategyTemplate, PDF_FLAG_KEYS,
)
from apps.tenancy.models import CLIENT_ROLES, AuditEvent

FF = crm_perms.Role.FF
CF = crm_perms.Role.CF
VA = crm_perms.Role.VA

# Matrix 10.4/10.5/10.6/10.10/10.11/10.12 — everything a VA may not do.
FRACTIONAL_ONLY = {FF, CF}


def _may_see_financial(request) -> bool:
    """Matrix 10.8. `CLAUDE.md`: a VA has no financials, anywhere."""
    return crm_perms.role_of(request) in FRACTIONAL_ONLY


class StrategyViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def _role(self):
        return crm_perms.role_of(self.request)

    def sessions(self):
        qs = StrategySession.objects.select_related(
            "contact", "company", "visionary_contact", "integrator_contact", "owner")
        role = self._role()
        if role in CLIENT_ROLES or role is None:
            return qs.none()
        if role == CF:
            # 🔸 their own prospects: a session they own, or one on a company
            # they are assigned. Either limb, because a CF's own prospect may
            # not be an assigned account yet.
            from django.db.models import Q

            companies = crm_perms.assigned_company_ids(self.request)
            return qs.filter(Q(owner=self.request.user) | Q(company_id__in=companies))
        return qs

    def load(self, pk) -> StrategySession:
        session = self.sessions().filter(pk=pk).first()
        if session is None:
            raise Http404
        return session

    def _fractional_only(self, what):
        if self._role() not in FRACTIONAL_ONLY:
            return Response({"detail": f"A VA cannot {what}."}, status=403)
        return None


class SessionViewSet(StrategyViewSet):

    def list(self, request):
        state = request.query_params.get("state")
        qs = self.sessions()
        if state and state != "all":
            qs = qs.filter(state__in=state.split(","))
        return Response([strategy_serializers.represent_session(s)
                         for s in qs.order_by("-created_at")[:200]])

    def retrieve(self, request, pk=None):
        session = self.load(pk)
        return Response(strategy_serializers.represent_session(
            session, include_financial=_may_see_financial(request), full=True,
            # Prep is the fractional's preparation for their own call. A VA's
            # payload does not contain it at all, on the same standard as §9.
            include_prep=_may_see_financial(request)))

    def create(self, request):
        """Matrix 10.2 — a VA may set a session up; only the call itself is
        fractional-only."""
        if self._role() not in {FF, CF, VA}:
            raise Http404
        serializer = strategy_serializers.SessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        contact = Contact.objects.filter(pk=data["contact"]).first()
        if contact is None:
            return Response({"detail": "That contact is not in this practice."},
                            status=404)
        template = None
        if data.get("template"):
            template = StrategyTemplate.objects.filter(pk=data["template"]).first()
        try:
            session = services.start(
                tenant=request.tenant, contact=contact, template=template,
                owner=request.user,
                company=(Contact.objects.filter(pk=data["company"]).first()
                         if data.get("company") else None) or contact.company,
                visionary_contact=(Contact.objects.filter(
                    pk=data["visionary_contact"]).first()
                    if data.get("visionary_contact") else None),
                integrator_contact=(Contact.objects.filter(
                    pk=data["integrator_contact"]).first()
                    if data.get("integrator_contact") else None),
                scheduled_at=data.get("scheduled_at"),
            )
        except services.SessionError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="strategy.session_started",
            target_type="strategy_session", target_id=session.pk,
            payload={"contact": str(contact.pk)})
        return Response(strategy_serializers.represent_session(session, full=True),
                        status=201)

    def partial_update(self, request, pk=None):
        session = self.load(pk)
        if (refused := self._fractional_only("change a session")) is not None:
            return refused
        data = request.data
        fields = []
        for field in ("scheduled_at",):
            if field in data:
                setattr(session, field, data[field] or None)
                fields.append(field)
        for field in ("visionary_contact", "integrator_contact"):
            if field in data:
                contact = (Contact.objects.filter(pk=data[field]).first()
                           if data[field] else None)
                setattr(session, f"{field}_id", contact.pk if contact else None)
                fields.append(f"{field}_id")
        # FR-4.19 — accepting the mirror is a person copying it across, and the
        # proposal is left alone so the two are always comparable.
        for field in ("mirror_goal", "mirror_unlocks"):
            if field in data:
                setattr(session, field, (data[field] or "").strip())
                fields.append(field)
        # FR-4.15 — "we are on this section now". One field and its clock; the
        # previous section's elapsed is not kept, because nothing reads it.
        if "current_section" in data:
            from django.utils import timezone

            code = (data["current_section"] or "").strip()
            known = {s["code"] for s in session.template_snapshot.get("sections", [])}
            if code and code not in known:
                return Response({"detail": "That section is not in this session."},
                                status=400)
            session.current_section = code
            session.current_section_at = timezone.now() if code else None
            fields += ["current_section", "current_section_at"]
        if "state" in data and data["state"] in StrategySession.State.values:
            session.state = data["state"]
            fields.append("state")
        if fields:
            session.save(update_fields=[*fields, "updated_at"])
        return Response(strategy_serializers.represent_session(
            session, include_financial=_may_see_financial(request), full=True))

    # ------------------------------------------------------------ the invite

    @action(detail=True, methods=["post"], url_path="send-invite")
    def send_invite(self, request, pk=None):
        """Matrix 10.3 — a VA may send this one, it carries nothing private."""
        session = self.load(pk)
        try:
            message = emails.send_precall_invite(session, actor=request.user,
                                                 role=self._role())
        except services.SessionError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        session.refresh_from_db()
        return Response({"outbox_message": str(message.pk),
                         "session": strategy_serializers.represent_session(
                             session, include_financial=_may_see_financial(request),
                             full=True)}, status=201)

    # -------------------------------------------------------- the live view

    @action(detail=True, methods=["post"])
    def answers(self, request, pk=None):
        """Matrix 10.4 — capture in the call. **No Claude call happens here**
        beyond the one automatic trigger (FR-4.18a), which fires only when an
        area has just been completed."""
        session = self.load(pk)
        if (refused := self._fractional_only("run the live session")) is not None:
            return refused
        serializer = strategy_serializers.AnswerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        question = services.question_in(session.template_snapshot, data["question_key"])
        if question is not None and question.get("is_financial") \
                and not _may_see_financial(request):
            raise Http404
        try:
            answer = services.save_answer(
                session, question_key=data["question_key"], value=data["value"],
                answered_by=StrategyAnswer.AnsweredBy.FRACTIONAL,
                fractional_note=data.get("fractional_note"))
        except services.AnswerInvalid as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        if session.state in (StrategySession.State.DRAFT,
                             StrategySession.State.PRECALL_SENT,
                             StrategySession.State.PRECALL_COMPLETE):
            from django.utils import timezone

            session.state = StrategySession.State.IN_CALL
            session.started_at = session.started_at or timezone.now()
            session.save(update_fields=["state", "started_at", "updated_at"])
        drafted = ai.draft_for_newly_completed_areas(session)
        # The second automatic trigger (owner, 2026-09-21): once, when §8 is
        # captured. Like the first, it cannot re-fire — `drafted_areas` records
        # that it ran.
        path_notes = ai.draft_paths_once_captured(session)
        return Response({
            "answer": strategy_serializers.represent_answer(answer),
            "six_key_components": services.six_key_components(session),
            "drafted": [strategy_serializers.represent_map_row(r) for r in drafted],
            "path_notes": [strategy_serializers.represent_path_note(n)
                           for n in path_notes],
        })

    @action(detail=True, methods=["post"])
    def prepare(self, request, pk=None):
        """One Claude call, with the web open, over the site and what the
        fractional already knows (owner, 2026-09-21).

        **Nothing it produces is applied.** A reworded question is copied into
        the template editor by the fractional; an extra question is pinned by
        them. The app never edits the template on Claude's say-so.
        """
        session = self.load(pk)
        if (refused := self._fractional_only("prepare a session")) is not None:
            return refused
        result = prep_service.prepare(
            session, website_url=request.data.get("website_url") or "",
            notes=request.data.get("notes") or "", actor=request.user)
        if result is None:
            return Response({"detail": "Claude could not be reached. The call is "
                                       "recorded on AI usage; nothing was saved."},
                            status=502)
        if result.state == StrategySessionPrep.State.FAILED:
            return Response({"detail": "Claude answered with something this could not "
                                       "read. Nothing was saved; the call is on AI "
                                       "usage."}, status=502)
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="strategy.prepared",
            target_type="strategy_session", target_id=session.pk,
            payload={"website": result.website_url,
                     "searches": result.ai_call.web_searches if result.ai_call_id else 0})
        return Response(strategy_serializers.represent_prep(result), status=201)

    @action(detail=True, methods=["get"], url_path="send-preview")
    def send_preview(self, request, pk=None):
        """What will go out, before it goes out (incident, 2026-09-22).

        `which` is `questions`, `invite` or `pdf`. The panel shows the whole
        body — not the part the fractional typed — because the part they did
        not type is where the six broken questions were.
        """
        session = self.load(pk)
        which = request.query_params.get("which", "questions")
        if which == "questions":
            if (refused := self._fractional_only("send the questions")) is not None:
                return refused
            return Response(emails.preview_precall_questions(
                session, intro=request.query_params.get("intro") or "",
                actor=request.user))
        if which == "invite":
            # Matrix 10.3 — a VA sends this one, so a VA may see it first.
            return Response(emails.preview_precall_invite(session, actor=request.user))
        if which == "pdf":
            if (refused := self._fractional_only("send the map")) is not None:
                return refused
            return Response(emails.preview_strategy_pdf(
                session, note=request.query_params.get("note") or "",
                actor=request.user))
        return Response({"detail": "which is 'questions', 'invite' or 'pdf'."},
                        status=400)

    @action(detail=True, methods=["patch"], url_path="prep-rewordings")
    def prep_rewordings(self, request, pk=None):
        """Keep the fractional's edit of a suggested rewording.

        They simplify a few before applying them, and the edit has to survive
        the trip to the template editor — which reads the prep rather than
        being handed text in a URL. **Still not applied**: this changes what
        prep suggests, never what the template says.
        """
        session = self.load(pk)
        if (refused := self._fractional_only("edit a prep suggestion")) is not None:
            return refused
        prep = StrategySessionPrep.objects.filter(session=session).first()
        if prep is None:
            raise Http404
        edits = {str(row.get("key")): str(row.get("suggested") or "").strip()
                 for row in (request.data.get("rewordings") or [])
                 if isinstance(row, dict) and row.get("key")}
        prep.rewordings = [
            {**row, "suggested": edits.get(row["key"]) or row["suggested"]}
            for row in prep.rewordings
        ]
        prep.save(update_fields=["rewordings", "updated_at"])
        return Response(strategy_serializers.represent_prep(prep))

    @action(detail=True, methods=["post"], url_path="send-questions")
    def send_questions(self, request, pk=None):
        """The questions in the body of an email, for a prospect who will not
        click a link (owner, 2026-09-21).

        **Not a VA's to send**, unlike the invite. H7a lets a VA send that one
        because it is template-only with nothing discretionary in it; this
        carries an intro a person wrote and goes from their own address.
        """
        session = self.load(pk)
        if (refused := self._fractional_only(
                "send the questions from your own address")) is not None:
            return refused
        try:
            message = emails.send_precall_questions(
                session, actor=request.user, role=self._role(),
                intro=request.data.get("intro") or "")
        except services.SessionError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        return Response({"outbox_message": str(message.pk),
                         "from_address": message.from_address}, status=201)

    @action(detail=True, methods=["post"], url_path="draft-rows")
    def draft_rows(self, request, pk=None):
        """Matrix 10.5 — the button. It costs money against the tenant's key."""
        session = self.load(pk)
        if (refused := self._fractional_only("run a Claude draft")) is not None:
            return refused
        rows = ai.draft_map_rows(session, trigger="button")
        return Response({"drafted": [strategy_serializers.represent_map_row(r)
                                     for r in rows]}, status=201 if rows else 200)

    @action(detail=True, methods=["post"], url_path="draft-paths")
    def draft_paths(self, request, pk=None):
        """The pros and cons of the two paths, on demand (owner, 2026-09-21).

        The other half of the same trigger pair the map rows have: this button,
        and once when §8 is captured. Nothing else calls it.
        """
        session = self.load(pk)
        if (refused := self._fractional_only("run a Claude draft")) is not None:
            return refused
        notes = ai.draft_path_notes(session, trigger="button")
        return Response({"drafted": [strategy_serializers.represent_path_note(n)
                                     for n in notes]}, status=201 if notes else 200)

    @action(detail=True, methods=["post"], url_path="draft-mirror")
    def draft_mirror(self, request, pk=None):
        session = self.load(pk)
        if (refused := self._fractional_only("run a Claude draft")) is not None:
            return refused
        ai.draft_mirror(session)
        session.refresh_from_db()
        return Response({"proposed_mirror": {"goal": session.proposed_mirror_goal,
                                             "unlocks": session.proposed_mirror_unlocks}})

    # --------------------------------------------------------------- the PDF

    @action(detail=True, methods=["patch"], url_path="pdf-flags")
    def pdf_flags(self, request, pk=None):
        """Matrix 10.10 — each toggle puts something private in front of a
        prospect, so a VA may not move one."""
        session = self.load(pk)
        if (refused := self._fractional_only("change what the PDF includes")) is not None:
            return refused
        flags = dict(session.pdf_include_flags or {})
        for key in PDF_FLAG_KEYS:
            if key in request.data:
                flags[key] = bool(request.data[key])
        session.pdf_include_flags = flags
        session.save(update_fields=["pdf_include_flags", "updated_at"])
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="strategy.pdf_flags_changed",
            target_type="strategy_session", target_id=session.pk, payload=flags)
        return Response({"pdf_include_flags": flags})

    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        """Matrix 10.9 — generating is not sending, so a VA may preview it.

        `?as=html` is the on-screen preview; the default is the real file, so
        what is reviewed is what would be attached.
        """
        session = self.load(pk)
        if request.query_params.get("as") == "html":
            return HttpResponse(pdf_service.render_html(session),
                                content_type="text/html; charset=utf-8")
        return HttpResponse(pdf_service.render_pdf(session),
                            content_type="application/pdf")

    @action(detail=True, methods=["post"], url_path="send-pdf")
    def send_pdf(self, request, pk=None):
        session = self.load(pk)
        if (refused := self._fractional_only("send the map to a prospect")) is not None:
            return refused
        try:
            message = emails.send_strategy_pdf(session, actor=request.user,
                                               role=self._role(),
                                               note=request.data.get("note", ""))
        except services.SessionError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        if session.state == StrategySession.State.IN_CALL:
            session.state = StrategySession.State.COMPLETE
            session.save(update_fields=["state", "updated_at"])
        return Response({"outbox_message": str(message.pk)}, status=201)

    # ---------------------------------------------------------- conversion

    @action(detail=True, methods=["get"], url_path="conversion-preview")
    def conversion_preview(self, request, pk=None):
        """AC-4.11 — what it would make. Writes nothing."""
        session = self.load(pk)
        if (refused := self._fractional_only("convert a session")) is not None:
            return refused
        return Response({"rows": conversion.preview(session)})

    @action(detail=True, methods=["post"])
    def convert(self, request, pk=None):
        session = self.load(pk)
        if (refused := self._fractional_only("convert a session")) is not None:
            return refused
        choices = request.data.get("choices") or {}
        for choice in choices.values():
            if isinstance(choice, dict) and choice.get("baseline_at"):
                choice["baseline_at"] = parse_date(str(choice["baseline_at"]))
        try:
            made = conversion.convert(session, choices=choices, actor=request.user,
                                      role=self._role())
        except conversion.ConversionRefused as exc:
            # `rows` names the map rows that are not ready, so the card can mark
            # them where the fractional is looking rather than only at the top.
            return Response({"detail": str(exc), "rows": exc.rows}, status=exc.status)
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="strategy.converted",
            target_type="strategy_session", target_id=session.pk,
            payload={"created": [{"as": kind, "id": str(obj.pk)} for kind, obj in made]})
        return Response({"created": [{"as": kind, "id": str(obj.pk),
                                      "title": obj.title} for kind, obj in made]},
                        status=201)


class MapRowViewSet(StrategyViewSet):
    """Matrix 10.6 — the tray. Accepting, editing and discarding are the
    fractional's judgement, never a VA's and never Claude's."""

    def rows(self):
        return StrategyMapRow.objects.filter(
            session__in=self.sessions()).select_related("session")

    def load_row(self, pk):
        row = self.rows().filter(pk=pk).first()
        if row is None:
            raise Http404
        return row

    def partial_update(self, request, pk=None):
        row = self.load_row(pk)
        if (refused := self._fractional_only("edit a map row")) is not None:
            return refused
        serializer = strategy_serializers.MapRowSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(row, field, value)
        row.save()
        return Response(strategy_serializers.represent_map_row(row))

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        return self._set_state(request, pk, StrategyMapRow.State.ACCEPTED,
                               "accept a map row")

    @action(detail=True, methods=["post"])
    def discard(self, request, pk=None):
        return self._set_state(request, pk, StrategyMapRow.State.DISCARDED,
                               "discard a map row")

    def _set_state(self, request, pk, state, what):
        row = self.load_row(pk)
        if (refused := self._fractional_only(what)) is not None:
            return refused
        row.state = state
        row.save(update_fields=["state", "updated_at"])
        return Response(strategy_serializers.represent_map_row(row))

    def create(self, request):
        """A row the fractional writes themselves — the tray is not the only
        way onto the map."""
        if (refused := self._fractional_only("add a map row")) is not None:
            return refused
        session = self.load(request.data.get("session"))
        serializer = strategy_serializers.MapRowSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if not (data.get("bottleneck") or "").strip():
            return Response({"detail": "A row needs a bottleneck."}, status=400)
        row = StrategyMapRow.objects.create(
            tenant=request.tenant, session=session,
            state=StrategyMapRow.State.ACCEPTED,
            position=data.get("position", StrategyMapRow.objects.filter(
                session=session).count()),
            **{k: v for k, v in data.items() if k != "position"})
        return Response(strategy_serializers.represent_map_row(row), status=201)

    @action(detail=False, methods=["post"])
    def reorder(self, request):
        """FR-4.20 — "what has to happen first for the rest to work?" """
        if (refused := self._fractional_only("reorder the map")) is not None:
            return refused
        order = request.data.get("order") or []
        rows = {str(row.pk): row for row in self.rows().filter(pk__in=order)}
        for position, row_id in enumerate(order):
            row = rows.get(str(row_id))
            if row is not None:
                row.position = position
                row.save(update_fields=["position", "updated_at"])
        return Response({"ok": True})


# Matrix 10.1 / FR-4.2 — what Beta's editor may change, and no more. Reordering,
# adding and deleting questions, and the flags that carry privacy
# (`is_financial`, `has_fractional_note`) are V1's, with the multi-discipline
# work: Beta has one template, seeded correctly, and the risk of a half-built
# editor rewriting it is worse than the inconvenience of an API call.
EDITABLE_QUESTION_FIELDS = ("prompt", "ask_when", "must_ask")


class PrepQuestionViewSet(StrategyViewSet):
    """The five extra questions. Pinning one is the fractional's act, and a
    pinned question is a **prompt with a note**, never a scored answer — it
    carries no `question_key` and never enters the session's snapshot."""

    def questions(self):
        return StrategyPrepQuestion.objects.filter(
            session__in=self.sessions()).select_related("session")

    def load_question(self, pk):
        found = self.questions().filter(pk=pk).first()
        if found is None:
            raise Http404
        return found

    def partial_update(self, request, pk=None):
        question = self.load_question(pk)
        if (refused := self._fractional_only("change a prep question")) is not None:
            return refused
        for field in ("is_pinned", "note"):
            if field in request.data:
                setattr(question, field, request.data[field])
        question.save()
        return Response(strategy_serializers.represent_prep_question(question))


class PathNoteViewSet(StrategyViewSet):
    """§8's tray. Matrix 10.6's rule, applied to the same kind of judgement:
    accepting, editing and discarding a pro or a con is the fractional's, never
    a VA's and never Claude's."""

    def notes(self):
        return StrategyPathNote.objects.filter(
            session__in=self.sessions()).select_related("session")

    def load_note(self, pk):
        note = self.notes().filter(pk=pk).first()
        if note is None:
            raise Http404
        return note

    def create(self, request):
        """One the fractional writes themselves. Accepted on arrival — a person
        typing it has already made the judgement the tray exists for."""
        if (refused := self._fractional_only("add a pro or a con")) is not None:
            return refused
        session = self.load(request.data.get("session"))
        serializer = strategy_serializers.PathNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if not (data.get("text") or "").strip():
            return Response({"detail": "A pro or a con needs some words."}, status=400)
        if not data.get("path") or not data.get("kind"):
            return Response({"detail": "Say which path, and whether it is a pro or "
                                       "a con."}, status=400)
        note = StrategyPathNote.objects.create(
            tenant=request.tenant, session=session, from_ai=False,
            state=StrategyPathNote.State.ACCEPTED,
            position=data.get("position", StrategyPathNote.objects.filter(
                session=session, path=data["path"], kind=data["kind"]).count()),
            **{k: v for k, v in data.items() if k != "position"})
        return Response(strategy_serializers.represent_path_note(note), status=201)

    def partial_update(self, request, pk=None):
        note = self.load_note(pk)
        if (refused := self._fractional_only("edit a pro or a con")) is not None:
            return refused
        serializer = strategy_serializers.PathNoteSerializer(data=request.data,
                                                             partial=True)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(note, field, value)
        note.save()
        return Response(strategy_serializers.represent_path_note(note))

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        return self._set_state(request, pk, StrategyPathNote.State.ACCEPTED,
                               "accept a pro or a con")

    @action(detail=True, methods=["post"])
    def discard(self, request, pk=None):
        return self._set_state(request, pk, StrategyPathNote.State.DISCARDED,
                               "discard a pro or a con")

    def _set_state(self, request, pk, state, what):
        note = self.load_note(pk)
        if (refused := self._fractional_only(what)) is not None:
            return refused
        note.state = state
        note.save(update_fields=["state", "updated_at"])
        return Response(strategy_serializers.represent_path_note(note))


class TemplateViewSet(StrategyViewSet):
    """Matrix 10.1 — the template is the FF's to edit. Everyone else reads it,
    because the live view has to render its own session.

    **Editing here can never reach a session already under way** (FR-4.5): a
    session renders from the snapshot it took at `start`, and nothing in it
    points at these rows.
    """

    def list(self, request):
        if self._role() not in {FF, CF, VA}:
            raise Http404
        return Response([{
            "id": str(t.pk), "name": t.name, "discipline": t.discipline,
            "version": t.version, "is_default": t.is_default,
            "sections": services.snapshot_of(t)["sections"],
        } for t in StrategyTemplate.objects.order_by("name", "version")])

    def partial_update(self, request, pk=None):
        if self._role() != FF:
            return Response({"detail": "Only the founder fractional may edit the "
                                       "template."}, status=403)
        from apps.strategy.models import StrategyQuestion

        template = StrategyTemplate.objects.filter(pk=pk).first()
        if template is None:
            raise Http404
        changed = []
        for edit in request.data.get("questions") or []:
            question = StrategyQuestion.objects.filter(
                template=template, key=edit.get("key"), deleted_at__isnull=True).first()
            if question is None:
                continue
            for field in EDITABLE_QUESTION_FIELDS:
                if field not in edit:
                    continue
                if field == "ask_when" and edit[field] not in AskWhen.values:
                    return Response({"detail": "ask_when is 'precall' or 'live'."},
                                    status=400)
                if field == "prompt":
                    if not (edit[field] or "").strip():
                        return Response({"detail": "A question needs a prompt."},
                                        status=400)
                    # A rewording changes the words, never the shape (incident,
                    # 2026-09-22). The same rule prep is held to, enforced here
                    # as well, because the editor is the last gate before a
                    # question reaches a prospect.
                    refusal = rewording.refusal(question.key, question.response_schema,
                                                edit[field])
                    if refusal:
                        return Response({"detail": refusal, "key": question.key},
                                        status=400)
                setattr(question, field, edit[field])
            question.save()
            changed.append(question.key)
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="strategy.template_edited",
            target_type="strategy_template", target_id=template.pk,
            payload={"questions": changed})
        return Response({"changed": changed})
