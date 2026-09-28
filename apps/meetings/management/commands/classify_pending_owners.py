"""Give the meeting queue's still-pending action items their owner
classification (owner, 2026-09-28).

Dry run by default: says how many proposals and items, and what the Claude
pass would cost. Nothing is changed and nothing is called without --run.

    manage.py classify_pending_owners              # count and estimate
    manage.py classify_pending_owners --run        # with Claude, one call per proposal
    manage.py classify_pending_owners --run --no-ai  # names and records only, free
"""

from django.core.management.base import BaseCommand

from apps.meetings import ownership
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Classify who owns each pending meeting action item."

    def add_arguments(self, parser):
        parser.add_argument("--run", action="store_true")
        parser.add_argument("--no-ai", action="store_true")
        parser.add_argument("--tenant", default="")

    def handle(self, *args, **options):
        tenants = Tenant.objects.filter(slug=options["tenant"]) if options["tenant"] \
            else Tenant.objects.all()
        for tenant in tenants:
            with tenant_context(tenant.pk):
                plan = ownership.plan_reclassification()
                self.stdout.write(
                    f"{tenant.name}: {plan['placed_free']} placed by the free rules; "
                    f"{plan['items']} need Claude, on "
                    f"{plan['proposals']} proposals. With Claude: {plan['proposals']} "
                    f"calls, about ${plan['estimated_cost_usd']:.2f} "
                    f"({'measured from calls already made' if plan['measured'] else 'modelled'}). "
                    "Without: free.")
                if options["run"]:
                    result = ownership.reclassify(tenant, use_claude=not options["no_ai"])
                    self.stdout.write(f"  {result['placed_free']} placed free; "
                                      f"classified {result['items']} with Claude; "
                                      f"{result['claude_calls']} calls, ${result['cost_usd']}; "
                                      f"{len(result['failed'])} proposals failed and stay "
                                      "unclassified")
