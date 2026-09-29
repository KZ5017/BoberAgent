"""Pure identities of persisted inspection configuration; no evidence access."""

import hashlib
import json

from .classification_models import ClassificationInspectionLimits
from .evidence_models import InspectionLimits
from .semantic_models import SemanticInspectionLimits


def evidence_config_fingerprint(
    limits: InspectionLimits | SemanticInspectionLimits, selected_paths: tuple[str, ...]
) -> str:
    config = {"limits": limits.model_dump(mode="json"), "selected_paths": selected_paths}
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def classification_config_fingerprint(limits: ClassificationInspectionLimits) -> str:
    return hashlib.sha256(
        json.dumps(limits.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
