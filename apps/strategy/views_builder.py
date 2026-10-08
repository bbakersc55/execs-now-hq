"""The template builder's API (P3; matrix 10.1a, 10.1b).

Reading is for the practice's staff, as the template list is. Every write is
the practice owner's. A template from another practice is not found, through
the tenant manager; a classic or focused template is refused, because those
keep the existing editor.
"""

from __future__ import annotations

from django.http import Http404
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.strategy import builder, examples, services
from apps.strategy.models import StrategyTemplate
from apps.strategy.views import CF, FF, VA, StrategyViewSet
from apps.tenancy.models import AuditEvent

OWNER_ONLY = "Only the practice owner can manage the templates."


class TemplateBuilderViewSet(StrategyViewSet):

    def _template(self, pk, *, write):
        """`(template, refusal)`. Staff read; the practice owner writes."""
        role = self._role()
        if role not in {FF, CF, VA}:
            raise Http404
        if write and role != FF:
            return None, Response({"detail": OWNER_ONLY}, status=403)
        template = StrategyTemplate.objects.filter(pk=pk).first()
        if template is None:
            raise Http404
        if not builder.is_v3(template):
            return None, Response(
                {"detail": f"“{template.name}” is not a builder template. It is edited "
                           "in the template editor, as before."}, status=409)
        return template, None

    def _audit(self, verb, template, payload=None):
        AuditEvent.all_objects.create(
            tenant=self.request.tenant, actor=self.request.user, verb=verb,
            target_type="strategy_template", target_id=template.pk,
            payload=payload or {})

    def _write(self, pk, fn, verb, payload=None, status=200):
        template, refused = self._template(pk, write=True)
        if refused:
            return refused
        try:
            result = fn(template)
        except services.SessionError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        self._audit(verb, template, payload(result) if callable(payload) else payload)
        template.refresh_from_db()
        return Response(examples.represent(template), status=status)

    def create(self, request):
        role = self._role()
        if role not in {FF, CF, VA}:
            raise Http404
        if role != FF:
            return Response({"detail": OWNER_ONLY}, status=403)
        # Absent means blank, as before (P3 §9.4). An example is named.
        start_from = request.data.get("start_from")
        payload = {}
        try:
            if start_from is None:
                template = builder.create_blank(request.tenant,
                                                name=request.data.get("name"))
            else:
                template, version = examples.create(
                    request.tenant, name=request.data.get("name"), start_from=start_from)
                payload = {"start_from": start_from, "example_version": version}
        except services.SessionError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        self._audit("strategy.template_created", template,
                    {"name": template.name, **payload})
        return Response(examples.represent(template), status=201)

    def retrieve(self, request, pk=None):
        template, refused = self._template(pk, write=False)
        if refused:
            return refused
        return Response(examples.represent(template))

    # Not `settings`: that name is the framework's own on every view.
    @action(detail=True, methods=["post"], url_path="settings")
    def template_settings(self, request, pk=None):
        changes = request.data.get("settings")
        return self._write(
            pk, lambda t: builder.update_settings(t, changes),
            "strategy.template_settings_edited",
            {"keys": sorted(changes) if isinstance(changes, dict) else []})

    @action(detail=True, methods=["post"])
    def section(self, request, pk=None):
        data = request.data
        fields = {}
        if "title" in data:
            fields["title"] = data["title"]
        if "time_budget_minutes" in data:
            fields["time_budget_minutes"] = data["time_budget_minutes"]
        return self._write(
            pk, lambda t: builder.update_section(t, code=data.get("code"), **fields),
            "strategy.template_section_edited",
            {"code": data.get("code"), "fields": sorted(fields)})

    @action(detail=True, methods=["post"])
    def include(self, request, pk=None):
        data = request.data
        included = data.get("included")
        if not isinstance(included, bool):
            return Response({"detail": "included is true or false."}, status=400)
        return self._write(
            pk, lambda t: builder.set_included(t, kind=data.get("kind"),
                                               included=included),
            "strategy.template_section_included" if included
            else "strategy.template_section_removed", {"kind": data.get("kind")})

    @action(detail=True, methods=["post"])
    def questions(self, request, pk=None):
        data = request.data
        return self._write(
            pk, lambda t: builder.add_question(
                t, section=data.get("section"), prompt=data.get("prompt"),
                label=data.get("label") or "", pdf_chip=data.get("pdf_chip") is True,
                is_financial=data.get("is_financial") is True,
                must_ask=data.get("must_ask") is True),
            "strategy.template_question_added",
            lambda question: {"key": question.key, "section": data.get("section")},
            status=201)

    @action(detail=True, methods=["post"])
    def question(self, request, pk=None):
        data = request.data
        changes = {field: data[field] for field in builder.EDITABLE if field in data}
        return self._write(
            pk, lambda t: builder.edit_question(t, key=data.get("key"), **changes),
            "strategy.template_edited",
            {"questions": [data.get("key")], "fields": sorted(changes)})

    @action(detail=True, methods=["post"], url_path="remove-question")
    def remove_question(self, request, pk=None):
        return self._write(
            pk, lambda t: builder.remove_question(t, key=request.data.get("key")),
            "strategy.template_question_removed",
            lambda question: {"key": question.key, "prompt": question.prompt})

    @action(detail=True, methods=["post"])
    def reorder(self, request, pk=None):
        data = request.data
        return self._write(
            pk, lambda t: builder.reorder(t, section=data.get("section"),
                                          keys=data.get("keys")),
            "strategy.template_reordered",
            lambda keys: {"section": data.get("section"), "keys": keys})
