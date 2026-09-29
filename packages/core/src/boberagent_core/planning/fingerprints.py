"""Pure semantic fingerprints; no state lookup, side effects or authorization."""

from boberagent_contracts.plan_canonical import canonical_digest

from .models import DecisionContext, PlanningRequest


def planning_request_fingerprint(request: PlanningRequest) -> str:
    return canonical_digest(request)


def decision_context_fingerprint(context: DecisionContext) -> str:
    return canonical_digest(context)
