"""Core-owned canonical Secret storage and explicit resolution boundary."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from uuid import uuid4

from boberagent_contracts import (
    ArtifactRef,
    CapabilityRunRef,
    JsonObject,
    MissionRef,
    ObservationRef,
    SecretRef,
)
from boberagent_transport import SecretGrant

from boberagent_core.clock import utc_now
from boberagent_core.models import SecretAccessRecord, SecretMetadata, SecretStatus
from boberagent_core.persistence import CoreDatabase


class SecretAccessDenied(PermissionError):
    """A Secret is absent, unavailable, or owned by another Mission."""


class RevealedSecret:
    """Explicitly revealed bytes whose ordinary display remains redacted."""

    __slots__ = ("__value",)

    def __init__(self, value: bytes) -> None:
        self.__value = bytes(value)

    def reveal_bytes(self) -> bytes:
        return self.__value

    def reveal_text(self, *, encoding: str = "utf-8") -> str:
        return self.__value.decode(encoding)

    def __repr__(self) -> str:
        return "RevealedSecret(<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"

    def __format__(self, format_spec: str) -> str:
        del format_spec
        return "<redacted>"


class CoreSecretService:
    """Store values in Core and issue only explicit, Run-scoped execution grants."""

    def __init__(
        self,
        database: CoreDatabase,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._database = database
        self._clock = clock

    def store(
        self,
        *,
        mission_ref: MissionRef,
        value: bytes,
        secret_type: str,
        metadata: JsonObject | None = None,
        created_by_run_ref: CapabilityRunRef | None = None,
        source_observation_ref: ObservationRef | None = None,
        source_artifact_refs: Iterable[ArtifactRef] = (),
        secret_ref: SecretRef | None = None,
    ) -> SecretMetadata:
        now = self._now()
        ref = secret_ref or SecretRef(f"secret:{uuid4()}")
        artifact_refs = tuple(source_artifact_refs)
        record = SecretMetadata(
            secret_ref=ref,
            mission_ref=mission_ref,
            secret_type=secret_type,
            status=SecretStatus.AVAILABLE,
            created_at=now,
            created_by_run_ref=created_by_run_ref,
            source_observation_ref=source_observation_ref,
            source_artifact_refs=artifact_refs,
            metadata={} if metadata is None else metadata,
        )
        with self._database.unit_of_work() as work:
            if work.missions.get(mission_ref) is None:
                raise KeyError(f"unknown Mission: {mission_ref}")
            if created_by_run_ref is not None:
                run = work.runs.get(created_by_run_ref)
                if run is None or run.mission_ref != mission_ref:
                    raise SecretAccessDenied("producing Run does not belong to the Secret Mission")
            if source_observation_ref is not None:
                observation = work.observations.get(source_observation_ref)
                if observation is None:
                    raise KeyError(f"unknown Observation: {source_observation_ref}")
                observation_run = work.runs.get(observation.observation.run_ref)
                if observation_run is None or observation_run.mission_ref != mission_ref:
                    raise SecretAccessDenied(
                        "source Observation does not belong to the Secret Mission"
                    )
            for artifact_ref in artifact_refs:
                artifact = work.artifacts.get(artifact_ref)
                if artifact is None:
                    raise KeyError(f"unknown Artifact: {artifact_ref}")
                artifact_run = work.runs.get(artifact.created_by_run)
                if artifact_run is None or artifact_run.mission_ref != mission_ref:
                    raise SecretAccessDenied(
                        "source Artifact does not belong to the Secret Mission"
                    )
            work.secrets.add(record, bytes(value))
        return record

    def get(self, secret_ref: SecretRef) -> SecretMetadata | None:
        with self._database.unit_of_work() as work:
            return work.secrets.get(secret_ref)

    def list_for_mission(self, mission_ref: MissionRef) -> tuple[SecretMetadata, ...]:
        with self._database.unit_of_work() as work:
            if work.missions.get(mission_ref) is None:
                raise KeyError(f"unknown Mission: {mission_ref}")
            return work.secrets.list_for_mission(mission_ref)

    def reveal_for_operator(
        self,
        secret_ref: SecretRef,
        *,
        mission_ref: MissionRef,
        purpose: str = "operator.reveal",
    ) -> RevealedSecret:
        return self._resolve(
            secret_ref,
            mission_ref=mission_ref,
            run_ref=None,
            accessor="OPERATOR",
            purpose=purpose,
        )

    def resolve_for_run(
        self,
        secret_ref: SecretRef,
        *,
        run_ref: CapabilityRunRef,
        purpose: str,
    ) -> RevealedSecret:
        with self._database.unit_of_work() as work:
            run = work.runs.get(run_ref)
            if run is None:
                raise SecretAccessDenied("Secret resolution requires a known CapabilityRun")
            mission_ref = run.mission_ref
        return self._resolve(
            secret_ref,
            mission_ref=mission_ref,
            run_ref=run_ref,
            accessor="CAPABILITY_GRANT",
            purpose=purpose,
        )

    def execution_grants(
        self,
        run_ref: CapabilityRunRef,
        authorizations: Mapping[SecretRef, str],
    ) -> tuple[SecretGrant, ...]:
        """Resolve an explicit set; this API deliberately has no enumerate-all operation."""

        return tuple(
            SecretGrant(
                secret_ref=secret_ref,
                value=self.resolve_for_run(
                    secret_ref,
                    run_ref=run_ref,
                    purpose=purpose,
                ).reveal_bytes(),
                authorized_purpose=purpose,
            )
            for secret_ref, purpose in sorted(authorizations.items(), key=lambda item: str(item[0]))
        )

    def set_status(self, secret_ref: SecretRef, status: SecretStatus) -> SecretMetadata:
        with self._database.unit_of_work() as work:
            return work.secrets.set_status(secret_ref, status)

    def access_records(self, secret_ref: SecretRef) -> tuple[SecretAccessRecord, ...]:
        with self._database.unit_of_work() as work:
            return work.secrets.list_access(secret_ref)

    def _resolve(
        self,
        secret_ref: SecretRef,
        *,
        mission_ref: MissionRef,
        run_ref: CapabilityRunRef | None,
        accessor: str,
        purpose: str,
    ) -> RevealedSecret:
        if not purpose or len(purpose) > 255:
            raise ValueError("Secret resolution purpose must contain 1-255 characters")
        with self._database.unit_of_work() as work:
            metadata = work.secrets.get(secret_ref)
            if (
                metadata is None
                or metadata.mission_ref != mission_ref
                or metadata.status is not SecretStatus.AVAILABLE
            ):
                raise SecretAccessDenied("Secret is unavailable for this Mission and Run")
            value = work.secrets.value(secret_ref)
            if value is None:
                raise SecretAccessDenied("Secret is unavailable for this Mission and Run")
            work.secrets.record_access(
                secret_ref=secret_ref,
                mission_ref=mission_ref,
                run_ref=run_ref,
                accessor=accessor,
                purpose=purpose,
                accessed_at=self._now(),
            )
            return RevealedSecret(value)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Secret service clock must return a timezone-aware datetime")
        return value
