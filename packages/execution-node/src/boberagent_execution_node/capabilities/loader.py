"""Failure-isolated static manifest discovery."""

import json
from pathlib import Path

from pydantic import ValidationError

from .registry import CapabilityManifest, CapabilityProvider, LocalCapabilityRegistry

MANIFEST_NAME = "capability.json"


class CapabilityLoader:
    def discover(
        self, paths: tuple[Path, ...], registry: LocalCapabilityRegistry
    ) -> tuple[CapabilityProvider, ...]:
        loaded: list[CapabilityProvider] = []
        manifests = sorted(
            manifest for root in paths if root.exists() for manifest in root.rglob(MANIFEST_NAME)
        )
        for manifest_path in manifests:
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest = CapabilityManifest.model_validate(raw)
                provider = CapabilityProvider(manifest, manifest_path)
                registry.register(provider)
            except (OSError, json.JSONDecodeError, ValidationError, ValueError) as error:
                registry.failures.append(f"{manifest_path}: {type(error).__name__}: {error}")
                continue
            loaded.append(provider)
        return tuple(loaded)
