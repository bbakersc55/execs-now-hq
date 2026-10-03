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
from apps.strategy import services, session_admin, style, template_admin
from apps.strategy import serializers as strategy_serializers
from apps.strategy.models import (
    AskWhen, StrategyAnswer, StrategyDiagnosticProposal, StrategyMapRow, StrategyPathNote,
    StrategyPrepQuestion,
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
            return Response({"detail": f"Assistants can't {what}."}, status=403)
        return None


class SessionViewSet(StrategyViewSet):

    def list(self, request):
        state = request.query_params.get("state")
        qs = self.sessions()
        if state and state != "all":
            qs = qs.filter(state__in=state.split(","))
        # Archived sessions are their own list, not a state: any session can be
        # archived, whatever state it reached.
        archived = request.query_params.get("archived") in ("1", "true")
        qs = qs.filter(archived_at__isnull=not archived)
        return Response([self._managed(strategy_serializers.represent_session(s), s)
                         for s in qs.order_by("-created_at")[:200]])

    def retrieve(self, request, pk=None):
        session = self.load(pk)
        return Response(self._managed(strategy_serializers.represent_session(
            session, include_financial=_may_see_financial(request), full=True,
            # Prep is the fractional's preparation for their own call. A VA's
            # payload does not contain it at all, on the same standard as §9.
            include_prep=_may_see_financial(request)), session))

    # --------------------------------------- archive, delete, reset questions

    def _may_archive(self, session) -> bool:
        """The FF, or a CF on a session they own."""
        role = self._role()
        return role == FF or (role == CF and session.owner_id == self.request.user.pk)

    def _managed(self, payload, session):
        """What this person may do to the session itself, said by the server
        so the screen never offers a control the API would refuse."""
        payload["archived_at"] = (session.archived_at.isoformat()
                                  if session.archived_at else None)
        payload["may_archive"] = self._may_archive(session)
        payload["may_delete"] = self._role() == FF
        payload["delete_refusal"] = session_admin.delete_refusal(session)
        payload["reset_refusal"] = session_admin.reset_refusal(session)
        return payload

    def _session_audit(self, verb, session_id, payload):
        AuditEvent.all_objects.create(
            tenant=self.request.tenant, actor=self.request.user, verb=verb,
            target_type="strategy_session", target_id=session_id, payload=payload)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        session = self.load(pk)
        if not self._may_archive(session):
            return Response({"detail": "Only the practice owner, or the person "
                                       "who owns this session, can archive it."},
                            status=403)
        session_admin.archive(session)
        self._session_audit("strategy.session_archived", session.pk,
                            {"state": session.state})
        return Response(self._managed(strategy_serializers.represent_session(session),
                                      session))

    @action(detail=True, methods=["post"])
    def unarchive(self, request, pk=None):
        session = self.load(pk)
        if not self._may_archive(session):
            return Response({"detail": "Only the practice owner, or the person "
                                       "who owns this session, can restore it."},
                            status=403)
        session_admin.unarchive(session)
        self._session_audit("strategy.session_unarchived", session.pk,
                            {"state": session.state})
        return Response(self._managed(strategy_serializers.represent_session(session),
                                      session))

    def destroy(self, request, pk=None):
        session = self.load(pk)
        if self._role() != FF:
            return Response({"detail": "Only the practice owner can delete a "
                                       "session."}, status=403)
        session_id = session.pk
        try:
            record = session_admin.delete(session)
        except services.SessionError as exc:
            self._session_audit("strategy.session_delete_refused", session_id,
                                {"reason": str(exc)})
            return Response({"detail": str(exc)}, status=exc.status)
        self._session_audit("strategy.session_deleted", session_id, record)
        return Response(status=204)

    @action(detail=True, methods=["get"], url_path="reset-preview")
    def reset_preview(self, request, pk=None):
        """What a reload or a seed restore would change, counted. Writes
        nothing; the confirm reads it so it can say how many questions move."""
        session = self.load(pk)
        if (refused := self._fractional_only("reset a session's questions")) is not None:
            return refused
        from apps.strategy import seed

        try:
            if request.query_params.get("source") == "seed":
                snapshot = seed.seed_snapshot(session_admin.seed_discipline(session))
            else:
                template = self._reset_template(request.query_params.get("template"))
                snapshot = services.snapshot_of(template)
        except services.SessionError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        return Response({**session_admin.compare(session, snapshot),
                         "refusal": session_admin.reset_refusal(session)})

    def _reset_template(self, template_id):
        if template_id:
            template = StrategyTemplate.objects.filter(pk=template_id).first()
            if template is None:
                raise services.SessionError("That template is not in this practice.",
                                            status=404)
            return template
        template = template_admin.default_template()
        if template is None:
            raise services.SessionError("Choose a template.")
        return template

    @action(detail=True, methods=["post"], url_path="restore-seed")
    def restore_seed(self, request, pk=None):
        """The seed's own wording for this session's discipline. Audited either
        way, like a reload."""
        session = self.load(pk)
        if (refused := self._fractional_only("reset a session's questions")) is not None:
            return refused
        was = (session.template_snapshot.get("template") or {}).get("name", "")
        try:
            session_admin.restore_seed(session)
        except services.SessionError as exc:
            self._session_audit("strategy.session_seed_restore_refused", session.pk,
                                {"reason": str(exc)})
            return Response({"detail": str(exc)}, status=exc.status)
        self._session_audit("strategy.session_seed_restored", session.pk,
                            {"was": was,
                             "now": session.template_snapshot["template"]["name"]})
        return Response(self._managed(strategy_serializers.represent_session(
            session, include_financial=_may_see_financial(request), full=True,
            include_prep=_may_see_financial(request)), session))

    @action(detail=True, methods=["post"], url_path="reset-questions")
    def reset_questions(self, request, pk=None):
        """Re-snapshot a draft nobody has been asked yet. Audited either way:
        a refusal here is someone trying to change what a person was asked."""
        session = self.load(pk)
        if (refused := self._fractional_only("reset a session's questions")) is not None:
            return refused
        template = None
        if request.data.get("template"):
            template = StrategyTemplate.objects.filter(pk=request.data["template"]).first()
            if template is None:
                return Response({"detail": "That template is not in this practice."},
                                status=404)
        else:
            template = template_admin.default_template()
        if template is None:
            return Response({"detail": "Choose a template."}, status=400)
        was = (session.template_snapshot.get("template") or {}).get("name", "")
        try:
            session_admin.reset_questions(session, template)
        except services.SessionError as exc:
            self._session_audit("strategy.session_questions_reset_refused", session.pk,
                                {"template": str(template.pk), "reason": str(exc)})
            return Response({"detail": str(exc)}, status=exc.status)
        self._session_audit("strategy.session_questions_reset", session.pk,
                            {"was": was, "now": template.name,
                             "template": str(template.pk)})
        return Response(self._managed(strategy_serializers.represent_session(
            session, include_financial=_may_see_financial(request), full=True,
            include_prep=_may_see_financial(request)), session))

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
            # Asked for one that is not here: say so, rather than start the
            # session from the default and let it look like the one chosen.
            if template is None:
                return Response({"detail": "That template is not in this practice."},
                                status=404)
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
            payload={"contact": str(contact.pk), "template": str(session.template_id),
                     "template_name": session.template_snapshot["template"]["name"]})
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

    @action(detail=True, methods=["get"], url_path="pdf-cover")
    def pdf_cover(self, request, pk=None):
        """The covering note, drafted from the session, for the fractional to
        edit (owner, 2026-09-29). Writes nothing."""
        session = self.load(pk)
        if (refused := self._fractional_only("send the map")) is not None:
            return refused
        return Response({"body_html": emails.default_pdf_cover(session)})

    @action(detail=True, methods=["get", "post"], url_path="send-preview")
    def send_preview(self, request, pk=None):
        """What will go out, before it goes out (incident, 2026-09-22).

        `which` is `questions`, `invite` or `pdf`. The panel shows the whole
        body — not the part the fractional typed — because the part they did
        not type is where the six broken questions were.
        """
        session = self.load(pk)
        # POST carries a body too long for a query string: the covering note
        # as it is being edited (owner, 2026-09-29). Nothing is written.
        params = request.data if request.method == "POST" else request.query_params
        which = params.get("which", "questions")
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
                session, note=params.get("note") or "",
                body_html=params.get("body_html") if "body_html" in params else None,
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
        if services.is_v3(session):
            from apps.strategy import v3

            if v3.map_room(session) <= 0:         # said, rather than a silent nothing
                return Response({"drafted": [], "detail": v3.MAP_FULL})
        rows = ai.draft_map_rows(session, trigger="button")
        return Response({"drafted": [strategy_serializers.represent_map_row(r)
                                     for r in rows]}, status=201 if rows else 200)

    @action(detail=True, methods=["post"])
    def consolidate(self, request, pk=None):
        """Merge the map and the tray into 3–5 main targets (10 at most), each
        citing what it merges — **proposed into the tray**, never applied
        (dry run 2, 2026-09-26). Costs money against the tenant's key."""
        session = self.load(pk)
        if (refused := self._fractional_only("run a Claude draft")) is not None:
            return refused
        # Past the estimated balance, ask first (owner, 2026-09-28). The
        # figures are AI spend, which is the FF's (FR-0.9); a CF is asked the
        # same question without them.
        from apps.tenancy import ai_budget

        ask = ai_budget.over_balance(request.tenant, ai_budget.call_estimate(
            ai.CONSOLIDATE_PURPOSE, ai.CONSOLIDATE_ESTIMATE_TOKENS))
        if ask and not request.data.get("confirm_over_balance"):
            if request.membership.role == "FF":
                return Response({**ask, "detail": (
                    f"Consolidating should cost about ${ask['estimated_cost']}, more than "
                    f"the estimated ${ask['estimated_balance']} left on the Anthropic "
                    "account. Consolidate anyway?")}, status=409)
            return Response({"needs_confirmation": True, "detail": (
                "The practice's AI credit may be running low. Consolidate anyway?")},
                status=409)
        rows = ai.consolidate_map_rows(session)
        self._session_audit("strategy.map_consolidation_proposed", session.pk,
                            {"proposed": [str(r.pk) for r in rows]})
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

    @action(detail=True, methods=["post"], url_path="propose-diagnostic")
    def propose_diagnostic(self, request, pk=None):
        """Claude's diagnostic questions from the pre-call form, on demand
        (owner, 2026-09-29). The other trigger is the form's completion."""
        from apps.strategy import diagnostic

        session = self.load(pk)
        if (refused := self._fractional_only("run a Claude draft")) is not None:
            return refused
        if services.is_v3(session):
            # v3 (P3): on demand as well, and once the ratings are taken on the
            # call, "Propose from the ratings" for the two lowest.
            from apps.strategy import v3

            from_ratings = request.data.get("from_ratings") is True
            if from_ratings and len(v3.ratings(session)) < 2:
                return Response({"detail": "Take at least two ratings first."},
                                status=409)
            if v3.diagnostic_room(session) <= 0:
                return Response({"detail": v3.accept_refusal(
                    session, v3.DIAGNOSTIC_CEILING)}, status=409)
            made = v3.propose(session, trigger="button", from_ratings=from_ratings)
            return Response({"proposed": [diagnostic.represent(p) for p in made]},
                            status=201 if made else 200)
        if not services.is_focused(session):
            return Response({"detail": "Proposed diagnostic questions belong to the "
                                       "focused template."}, status=409)
        made = diagnostic.propose(session, trigger="button")
        return Response({"proposed": [diagnostic.represent(p) for p in made]},
                        status=201 if made else 200)

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
            message = emails.send_strategy_pdf(
                session, actor=request.user, role=self._role(),
                note=request.data.get("note", ""),
                body_html=(request.data.get("body_html")
                           if "body_html" in request.data else None))
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
        if row.state == StrategyMapRow.State.ACCEPTED:
            style.record_row(row)        # edited after acceptance: still their style
        return Response(strategy_serializers.represent_map_row(row))

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        row = self.load_row(pk)
        # The focused map holds five (owner, 2026-09-29).
        if (services.has_card_map(row.session) and row.state != StrategyMapRow.State.ACCEPTED
                and StrategyMapRow.objects.filter(
                    session=row.session, state=StrategyMapRow.State.ACCEPTED
                ).count() >= ai.FOCUSED_MAP_CAP):
            return Response({"detail": f"The map holds {ai.FOCUSED_MAP_CAP} rows. Remove "
                                       "one, or Consolidate, before accepting another."},
                            status=409)
        response = self._set_state(request, pk, StrategyMapRow.State.ACCEPTED,
                                   "accept a map row")
        if response.status_code == 200:
            style.record_row(self.load_row(pk))
        return response

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

    @action(detail=True, methods=["post"])
    def remove(self, request, pk=None):
        """Take an accepted row off the map (dry run 2, 2026-09-26), so the map
        can be pruned after a consolidation. It goes back to `discarded`, not
        away: the row and its history stay. Refused once converted — a goal or
        project links back to it."""
        row = self.load_row(pk)
        if (refused := self._fractional_only("remove a map row")) is not None:
            return refused
        if row.state != StrategyMapRow.State.ACCEPTED:
            return Response({"detail": "Only a row on the map can be removed from it."},
                            status=400)
        if row.converted_to:
            return Response({"detail": f"This row was converted to a {row.converted_to}, "
                                       f"which links back to it. It stays on the map."},
                            status=409)
        row.state = StrategyMapRow.State.DISCARDED
        row.save(update_fields=["state", "updated_at"])
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user, verb="strategy.map_row_removed",
            target_type="strategy_map_row", target_id=row.pk,
            payload={"session": str(row.session_id), "bottleneck": row.bottleneck})
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


# Matrix 10.1 / FR-4.2 — what an existing question's row may have changed in
# place. Adding, removing (archiving) and reordering have their own actions
# (owner, 2026-09-26); the privacy flags (`is_financial`, `has_fractional_note`)
# are set when a question is added, not flipped on one that has been asked.
EDITABLE_QUESTION_FIELDS = ("prompt", "ask_when", "must_ask", "ask_if_time")


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
        if note.state == StrategyPathNote.State.ACCEPTED:
            style.record_note(note)
        return Response(strategy_serializers.represent_path_note(note))

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        response = self._set_state(request, pk, StrategyPathNote.State.ACCEPTED,
                                   "accept a pro or a con")
        if response.status_code == 200:
            style.record_note(self.load_note(pk))
        return response

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


class DiagnosticProposalViewSet(StrategyViewSet):
    """The focused template's diagnostic tray (owner, 2026-09-29). Accepting,
    editing and discarding are the fractional's, as the map's tray is."""

    def proposals(self):
        return StrategyDiagnosticProposal.objects.filter(
            session__in=self.sessions()).select_related("session")

    def load_proposal(self, pk):
        proposal = self.proposals().filter(pk=pk).first()
        if proposal is None:
            raise Http404
        return proposal

    def create(self, request):
        """A diagnostic question typed in during a v3 session (P3, D4; matrix
        10.5b). It joins the session, not the template."""
        from django.db import transaction

        from apps.strategy import diagnostic, v3

        session = self.load(request.data.get("session"))
        if (refused := self._fractional_only("add a diagnostic question")) is not None:
            return refused
        if not services.is_v3(session):
            return Response({"detail": "A question is added by hand only in a session "
                                       "started from a builder template."}, status=409)
        try:
            with transaction.atomic():
                proposal = v3.add_question(session, prompt=request.data.get("prompt"))
        except diagnostic.Refused as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user,
            verb="strategy.diagnostic_question_added",
            target_type="strategy_session", target_id=session.pk,
            payload={"proposal": str(proposal.pk), "key": proposal.question_key})
        return Response(diagnostic.represent(proposal), status=201)

    def partial_update(self, request, pk=None):
        from apps.strategy import diagnostic

        proposal = self.load_proposal(pk)
        if (refused := self._fractional_only("edit a proposed question")) is not None:
            return refused
        if proposal.state != StrategyDiagnosticProposal.State.PROPOSED:
            return Response({"detail": "Only a proposed question can be edited here."},
                            status=409)
        prompt = " ".join(str(request.data.get("prompt") or "").split())
        if not prompt:
            return Response({"detail": "A question needs some words."}, status=400)
        proposal.prompt = prompt
        proposal.save(update_fields=["prompt", "updated_at"])
        return Response(diagnostic.represent(proposal))

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        from django.db import transaction

        from apps.strategy import diagnostic

        proposal = self.load_proposal(pk)
        if (refused := self._fractional_only("accept a proposed question")) is not None:
            return refused
        try:
            with transaction.atomic():
                diagnostic.accept(proposal)
        except diagnostic.Refused as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user,
            verb="strategy.diagnostic_question_accepted",
            target_type="strategy_session", target_id=proposal.session_id,
            payload={"proposal": str(proposal.pk), "key": proposal.question_key,
                     "edited": proposal.prompt != proposal.proposed_prompt})
        return Response(diagnostic.represent(proposal))

    @action(detail=True, methods=["post"])
    def remove(self, request, pk=None):
        """An accepted question back out of the session and into the tray
        (backlog, 2026-10-03). Refused once answered or once the session is
        finished."""
        from django.db import transaction

        from apps.strategy import diagnostic

        proposal = self.load_proposal(pk)
        if (refused := self._fractional_only("remove a diagnostic question")) is not None:
            return refused
        key = proposal.question_key
        try:
            with transaction.atomic():
                diagnostic.remove(proposal)
        except diagnostic.Refused as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        AuditEvent.all_objects.create(
            tenant=request.tenant, actor=request.user,
            verb="strategy.diagnostic_question_removed",
            target_type="strategy_session", target_id=proposal.session_id,
            payload={"proposal": str(proposal.pk), "key": key})
        return Response(diagnostic.represent(proposal))

    @action(detail=True, methods=["post"])
    def discard(self, request, pk=None):
        from apps.strategy import diagnostic

        proposal = self.load_proposal(pk)
        if (refused := self._fractional_only("discard a proposed question")) is not None:
            return refused
        if proposal.state != StrategyDiagnosticProposal.State.PROPOSED:
            return Response({"detail": "Only a proposed question can be discarded."},
                            status=409)
        proposal.state = StrategyDiagnosticProposal.State.DISCARDED
        proposal.save(update_fields=["state", "updated_at"])
        return Response(diagnostic.represent(proposal))


def represent_template(t) -> dict:
    payload = {
        "id": str(t.pk), "name": t.name, "discipline": t.discipline,
        "version": t.version, "is_default": t.is_default,
        "archived_at": t.archived_at.isoformat() if t.archived_at else None,
        "sessions": t.sessions.count(),
        "sections": services.snapshot_of(t)["sections"],
    }
    # Only a builder template (P3) says so, and whether it can start a
    # session: a classic or focused template's payload is what it always was.
    if t.format == StrategyTemplate.Format.V3:
        from apps.strategy import builder

        missing = builder.readiness(t)
        payload.update(format=t.format, ready=not missing, missing=missing)
    return payload


BUILDER_ONLY = ("This template was made in the template builder, and its questions "
                "are edited there.")


class TemplateViewSet(StrategyViewSet):
    """Matrix 10.1 — the templates are the FF's to manage. Everyone else reads
    them, because the live view has to render its own session and the start
    form has to offer a choice.

    **Nothing here can reach a session already under way** (FR-4.5): a session
    renders from the snapshot it took at `start`, and nothing in it points at
    these rows. Renaming, archiving or changing the default moves no session.
    """

    def list(self, request):
        if self._role() not in {FF, CF, VA}:
            raise Http404
        return Response([represent_template(t) for t in StrategyTemplate.objects
                         .order_by("archived_at", "-is_default", "name", "version")])

    def _ff_template(self, pk):
        """The FF's, or a refusal. Returns `(template, refusal)`."""
        if self._role() != FF:
            return None, Response({"detail": "Only the practice owner can manage "
                                             "the templates."}, status=403)
        template = StrategyTemplate.objects.filter(pk=pk).first()
        if template is None:
            raise Http404
        return template, None

    def _editor_template(self, pk):
        """As `_ff_template`, for the editor's question and section verbs: a
        builder template (P3) is refused, because each of its sections holds
        one shape of question and the builder is what keeps it so."""
        template, refused = self._ff_template(pk)
        if not refused and template.format == StrategyTemplate.Format.V3:
            return None, Response({"detail": BUILDER_ONLY}, status=409)
        return template, refused

    def _audit(self, verb, template, payload=None):
        AuditEvent.all_objects.create(
            tenant=self.request.tenant, actor=self.request.user, verb=verb,
            target_type="strategy_template", target_id=template.pk,
            payload=payload or {})

    def _run(self, fn, verb, template, payload=None, status=200):
        try:
            result = fn()
        except services.SessionError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        self._audit(verb, result, payload)
        return Response(represent_template(result), status=status)

    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        source, refused = self._ff_template(pk)
        if refused:
            return refused
        name = request.data.get("name") or f"{source.name} (copy)"
        return self._run(lambda: template_admin.duplicate(source, name=name),
                         "strategy.template_duplicated", source,
                         {"from": str(source.pk), "from_name": source.name}, status=201)

    @action(detail=False, methods=["post"], url_path="restore-from-seed")
    def restore_from_seed(self, request):
        if self._role() != FF:
            return Response({"detail": "Only the practice owner can manage the "
                                       "templates."}, status=403)
        # P3, D3: the seed is Executives Now's own Operations template. A
        # practice that was never given it builds its own.
        if not StrategyTemplate.objects.exclude(
                format=StrategyTemplate.Format.V3).exists():
            return Response({"detail": "This practice builds its own templates. "
                                       "Start one with New template."}, status=403)
        name = request.data.get("name") or "Operations — generic"
        variant = request.data.get("variant") or ""
        return self._run(lambda: template_admin.restore_from_seed(
                             request.tenant, name=name, variant=variant),
                         "strategy.template_restored_from_seed", None,
                         {"source": "docs/strategy_session_seed.md",
                          "variant": variant}, status=201)

    @action(detail=True, methods=["post"])
    def questions(self, request, pk=None):
        """Add a question. The rewording guard applies, as to any wording."""
        template, refused = self._editor_template(pk)
        if refused:
            return refused
        data = request.data
        fields = {f: data[f] for f in template_admin.QUESTION_FLAGS if f in data}
        try:
            question = template_admin.add_question(
                template, section=data.get("section"), prompt=data.get("prompt"),
                response_schema=data.get("response_schema") or "free_text",
                ask_when=data.get("ask_when") or "live", area=data.get("area") or "",
                **fields)
        except services.SessionError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        self._audit("strategy.template_question_added", template,
                    {"key": question.key, "section": data.get("section")})
        return Response(represent_template(template), status=201)

    @action(detail=True, methods=["post"], url_path="remove-question")
    def remove_question(self, request, pk=None):
        template, refused = self._editor_template(pk)
        if refused:
            return refused
        try:
            question = template_admin.remove_question(template,
                                                      key=request.data.get("key"))
        except services.SessionError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        self._audit("strategy.template_question_removed", template,
                    {"key": question.key, "prompt": question.prompt})
        return Response(represent_template(template))

    @action(detail=True, methods=["post"])
    def reorder(self, request, pk=None):
        template, refused = self._editor_template(pk)
        if refused:
            return refused
        try:
            keys = template_admin.reorder(template, section=request.data.get("section"),
                                          keys=request.data.get("keys"))
        except services.SessionError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        self._audit("strategy.template_reordered", template,
                    {"section": request.data.get("section"), "keys": keys})
        return Response(represent_template(template))

    @action(detail=True, methods=["post"], url_path="set-default")
    def set_default(self, request, pk=None):
        template, refused = self._ff_template(pk)
        if refused:
            return refused
        was = template_admin.default_template(template.discipline)
        return self._run(lambda: template_admin.set_default(template),
                         "strategy.template_set_default", template,
                         {"was": str(was.pk) if was else None})

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        template, refused = self._ff_template(pk)
        if refused:
            return refused
        return self._run(lambda: template_admin.archive(template),
                         "strategy.template_archived", template)

    @action(detail=True, methods=["post"])
    def unarchive(self, request, pk=None):
        template, refused = self._ff_template(pk)
        if refused:
            return refused
        return self._run(lambda: template_admin.unarchive(template),
                         "strategy.template_unarchived", template)

    def partial_update(self, request, pk=None):
        template, refused = self._ff_template(pk)
        if refused:
            return refused
        from apps.strategy.models import StrategyQuestion

        # Renaming is the same for every template; a builder template's
        # sections and questions are edited in the builder (P3).
        if template.format == StrategyTemplate.Format.V3 and (
                request.data.get("sections") or request.data.get("questions")):
            return Response({"detail": BUILDER_ONLY}, status=409)

        if "name" in request.data:
            was = template.name
            try:
                template_admin.rename(template, name=request.data["name"])
            except services.SessionError as exc:
                return Response({"detail": str(exc)}, status=exc.status)
            if template.name != was:
                self._audit("strategy.template_renamed", template,
                            {"was": was, "now": template.name})
        budgets = {}
        for edit in request.data.get("sections") or []:
            if "time_budget_minutes" not in edit:
                continue
            try:
                section = template_admin.set_budget(
                    template, section=edit.get("code"),
                    minutes=edit["time_budget_minutes"])
            except services.SessionError as exc:
                return Response({"detail": str(exc)}, status=exc.status)
            budgets[section.code] = section.time_budget_minutes
        if budgets:
            self._audit("strategy.template_budgets_edited", template, {"budgets": budgets})
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
        if changed:
            self._audit("strategy.template_edited", template, {"questions": changed})
        return Response({"changed": changed, "template": represent_template(template)})
