"""Authenticated E3 import and E4 exact-source materialization; no source execution."""

from __future__ import annotations

import hashlib
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from boberagent_contracts import (
    ArtifactRef,
    CapabilityRunStatus,
    DomainRef,
    PreparationPermit,
    RuntimePreparationInput,
)
from boberagent_contracts.runtime_preparation import (
    PreparationAction,
    preparation_permit_digest,
)
from boberagent_transport import (
    ImportChunk,
    ImportCompleted,
    ImportFinalize,
    ImportReady,
    ImportRejected,
    ImportRequest,
    ImportStart,
    InvocationEnvelope,
    MaterializationEvidence,
    MaterializationPreflight,
    MaterializationRejected,
    MaterializationResponse,
    MaterializeSourceRequest,
    invocation_fingerprint,
    preparation_import_id,
)
from pydantic import ValidationError

from boberagent_execution_node.persistence import RuntimeDatabase
from boberagent_execution_node.persistence.orm import (
    ImportedArtifactRow,
    PreparationAuthorityRow,
    PreparationImportRow,
    PreparationMaterializationRow,
    RunRow,
)
from boberagent_execution_node.workspace.directories import prepare_owned_directory

from .confinement import (
    E4_REQUIRED_FEATURES,
    BubblewrapConfinementBackend,
    ConfinementBackend,
    ConfinementUnavailable,
)
from .materializer import (
    MaterializationError,
    MaterializedTree,
    materialize_zip,
    parse_manifest,
    verify_published,
)

_PROVIDER_NAMESPACE = UUID("aa3e648b-55b6-572c-98b8-31ad7d8e0a25")
PREPARATION_PROVIDER_VERSION = "0.1.0"
TRUSTED_CORE_PRINCIPAL = "boberagent-core"


class PreparationAdmissionError(ValueError):
    """A bounded authority/import rejection, never a PoC execution result."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class NodePreparationService:
    """Persist authenticated E3 authority and stream only its two pinned Artifacts."""

    def __init__(
        self,
        database: RuntimeDatabase,
        root: Path,
        node_id: str,
        workspace_root: Path,
        *,
        confinement: ConfinementBackend | None = None,
    ) -> None:
        self._database = database
        self._root = root.resolve()
        self._partials = self._root / "partial"
        self._objects = self._root / "objects"
        self._partials.mkdir(parents=True, exist_ok=True)
        self._objects.mkdir(parents=True, exist_ok=True)
        self._node_id = node_id
        self._materialization_root = workspace_root.resolve() / "preparation-source"
        self._staging = self._materialization_root / "staging"
        self._published = self._materialization_root / "published"
        self._quarantine = self._materialization_root / "quarantine"
        self._confinement = confinement or BubblewrapConfinementBackend()
        self._recover_materializations()

    @property
    def node_id(self) -> str:
        return self._node_id

    def admit(self, envelope: InvocationEnvelope, *, principal: str) -> None:
        self._check_principal(principal)
        invocation = envelope.delivery.invocation
        if (
            envelope.node_id != self._node_id
            or str(invocation.capability_id) != "runtime.prepare"
            or invocation.operation != "prepare"
            or envelope.delivery.secret_grants
        ):
            raise PreparationAdmissionError("PREPARATION_INVOCATION_INVALID")
        try:
            parsed = RuntimePreparationInput.model_validate(invocation.inputs)
        except (ValidationError, ValueError, TypeError):
            raise PreparationAdmissionError("PREPARATION_INPUT_INVALID") from None
        permit = parsed.permit
        spec = permit.spec
        if (
            permit.run_ref != invocation.run_id
            or spec.preparation_ref is None
            or spec.mission_ref != invocation.mission_ref
            or spec.node_id != self._node_id
            or spec.provider_id != uuid5(_PROVIDER_NAMESPACE, f"{self._node_id}\0runtime.prepare")
            or spec.provider_version != PREPARATION_PROVIDER_VERSION
            or not {PreparationAction.IMPORT_AUTHORIZED_ARTIFACT, PreparationAction.VERIFY_ARTIFACT}
            <= set(spec.allowed_actions)
        ):
            raise PreparationAdmissionError("PREPARATION_AUTHORITY_MISMATCH")
        now = datetime.now(UTC)
        if not permit.not_before <= now < permit.expires_at:
            raise PreparationAdmissionError("PREPARATION_AUTHORITY_EXPIRED")
        digest = preparation_permit_digest(permit)
        delivery_fingerprint = invocation_fingerprint(envelope.delivery)
        with self._database.transaction() as session:
            existing = session.get(PreparationAuthorityRow, str(permit.permit_ref))
            run = session.get(RunRow, str(permit.run_ref))
            if existing is not None or run is not None:
                if (
                    existing is None
                    or run is None
                    or existing.authority_sha256 != digest
                    or existing.principal_id != principal
                    or existing.preparation_id != str(spec.preparation_ref)
                    or existing.run_id != str(permit.run_ref)
                    or run.mission_id != str(spec.mission_ref)
                    or run.capability_id != "runtime.prepare"
                    or run.operation != "prepare"
                    or run.status != CapabilityRunStatus.QUEUED.value
                    or run.invocation_fingerprint != delivery_fingerprint
                ):
                    raise PreparationAdmissionError("PREPARATION_AUTHORITY_CONFLICT")
                return
            session.add(
                RunRow(
                    run_id=str(permit.run_ref),
                    mission_id=str(spec.mission_ref),
                    capability_id="runtime.prepare",
                    operation="prepare",
                    status=CapabilityRunStatus.QUEUED.value,
                    parent_run_id=None,
                    workflow_run_id=None,
                    invocation_fingerprint=delivery_fingerprint,
                    created_at=now,
                    started_at=None,
                    finished_at=None,
                    error_code=None,
                )
            )
            session.flush()
            session.add(
                PreparationAuthorityRow(
                    permit_id=str(permit.permit_ref),
                    preparation_id=str(spec.preparation_ref),
                    run_id=str(permit.run_ref),
                    authority_sha256=digest,
                    principal_id=principal,
                    permit_json=permit.model_dump(mode="json"),
                    admitted_at=now,
                )
            )

    def exchange(
        self, request: ImportRequest, *, principal: str
    ) -> ImportReady | ImportCompleted | ImportRejected:
        self._check_principal(principal)
        try:
            return self._exchange_checked(request, principal=principal)
        except PreparationAdmissionError as error:
            self._retain_failure(request, error.code)
            return ImportRejected(
                request_message_id=request.message_id,
                node_id=self._node_id,
                import_id=request.import_id,
                artifact_ref=request.artifact_ref,
                code=error.code,
                retryable=error.code in {"IMPORT_INTERRUPTED", "IMPORT_STORAGE_UNAVAILABLE"},
            )
        except OSError:
            self._retain_failure(request, "IMPORT_STORAGE_UNAVAILABLE")
            return ImportRejected(
                request_message_id=request.message_id,
                node_id=self._node_id,
                import_id=request.import_id,
                artifact_ref=request.artifact_ref,
                code="IMPORT_STORAGE_UNAVAILABLE",
                retryable=True,
            )

    def _exchange_checked(
        self, request: ImportRequest, *, principal: str
    ) -> ImportReady | ImportCompleted:
        if request.node_id != self._node_id:
            raise PreparationAdmissionError("WRONG_NODE")
        now = datetime.now(UTC)
        with self._database.transaction() as session:
            authority = session.get(PreparationAuthorityRow, str(request.permit_ref))
            if authority is None or authority.principal_id != principal:
                raise PreparationAdmissionError("PREPARATION_NOT_ADMITTED")
            run = session.get(RunRow, authority.run_id)
            if run is None or run.status != CapabilityRunStatus.QUEUED.value:
                raise PreparationAdmissionError("PREPARATION_RUN_NOT_ACTIVE")
            try:
                permit = PreparationPermit.model_validate(authority.permit_json)
            except (ValidationError, ValueError, TypeError):
                raise PreparationAdmissionError("PREPARATION_AUTHORITY_CORRUPT") from None
            if (
                preparation_permit_digest(permit) != authority.authority_sha256
                or permit.permit_ref != request.permit_ref
                or permit.run_ref != request.run_ref
                or permit.spec.preparation_ref != request.preparation_ref
                or permit.spec.node_id != self._node_id
            ):
                raise PreparationAdmissionError("PREPARATION_AUTHORITY_MISMATCH")
            if not permit.not_before <= now < permit.expires_at:
                raise PreparationAdmissionError("PREPARATION_AUTHORITY_EXPIRED")
            source = permit.spec.source
            pins = {
                source.plan_source.raw_artifact_ref: (
                    source.plan_source.raw_sha256,
                    source.plan_source.raw_size_bytes,
                ),
                source.plan_source.manifest_artifact_ref: (
                    source.plan_source.manifest_sha256,
                    source.manifest_size_bytes,
                ),
            }
            if request.artifact_ref not in pins:
                raise PreparationAdmissionError("ARTIFACT_NOT_AUTHORIZED")
            if PreparationAction.IMPORT_AUTHORIZED_ARTIFACT not in permit.spec.allowed_actions:
                raise PreparationAdmissionError("IMPORT_NOT_AUTHORIZED")
            expected_hash, expected_size = pins[request.artifact_ref]
            if expected_size > permit.spec.budgets.max_imported_artifact_bytes:
                raise PreparationAdmissionError("IMPORT_LIMIT_EXCEEDED")
            if sum(size for _, size in pins.values()) > permit.spec.budgets.max_temporary_bytes:
                raise PreparationAdmissionError("IMPORT_TEMPORARY_LIMIT_EXCEEDED")
            if isinstance(request, ImportStart) and (
                request.sha256 != expected_hash or request.size_bytes != expected_size
            ):
                raise PreparationAdmissionError("ARTIFACT_IDENTITY_CONFLICT")
            record = session.get(PreparationImportRow, str(request.import_id))
            if record is None:
                if not isinstance(request, ImportStart):
                    raise PreparationAdmissionError("IMPORT_NOT_STARTED")
                existing = session.get(ImportedArtifactRow, str(request.artifact_ref))
                if existing is not None and (
                    existing.sha256 != expected_hash or existing.size_bytes != expected_size
                ):
                    raise PreparationAdmissionError("ARTIFACT_IDENTITY_CONFLICT")
                record = PreparationImportRow(
                    import_id=str(request.import_id),
                    permit_id=str(request.permit_ref),
                    artifact_id=str(request.artifact_ref),
                    sha256=expected_hash,
                    size_bytes=expected_size,
                    received_bytes=0,
                    state="PARTIAL",
                    started_at=now,
                    updated_at=now,
                    error_code=None,
                )
                session.add(record)
                session.flush()
                if existing is None:
                    self._partial_path(request.import_id).touch(exist_ok=True)
                else:
                    self._verify_file(
                        self._object_path(expected_hash), expected_hash, expected_size
                    )
                    record.received_bytes = expected_size
                    record.state = "VERIFIED"
            if (
                record.permit_id != str(request.permit_ref)
                or record.artifact_id != str(request.artifact_ref)
                or record.sha256 != expected_hash
                or record.size_bytes != expected_size
            ):
                raise PreparationAdmissionError("IMPORT_IDENTITY_CONFLICT")
            if record.state == "VERIFIED":
                self._verify_file(self._object_path(expected_hash), expected_hash, expected_size)
                return ImportCompleted(
                    request_message_id=request.message_id,
                    node_id=self._node_id,
                    import_id=request.import_id,
                    artifact_ref=request.artifact_ref,
                    sha256=expected_hash,
                    size_bytes=expected_size,
                    deduplicated=True,
                )
            if now - record.started_at > timedelta(
                seconds=permit.spec.budgets.max_total_runtime_seconds
            ):
                raise PreparationAdmissionError("IMPORT_TIMEOUT")
            if record.state != "PARTIAL":
                raise PreparationAdmissionError("IMPORT_NOT_RESUMABLE")
            path = self._partial_path(request.import_id)
            if not path.exists():
                # A crash may follow the atomic rename but precede the DB commit.
                object_path = self._object_path(expected_hash)
                if record.received_bytes == expected_size and object_path.exists():
                    self._verify_file(object_path, expected_hash, expected_size)
                    record.state = "VERIFIED"
                    self._publish_record(
                        session, request.artifact_ref, expected_hash, expected_size, now
                    )
                    return ImportCompleted(
                        request_message_id=request.message_id,
                        node_id=self._node_id,
                        import_id=request.import_id,
                        artifact_ref=request.artifact_ref,
                        sha256=expected_hash,
                        size_bytes=expected_size,
                        deduplicated=True,
                    )
                raise PreparationAdmissionError("IMPORT_INTERRUPTED")
            with path.open("r+b") as stream:
                stream.truncate(record.received_bytes)
                if isinstance(request, ImportChunk):
                    if len(request.data) > permit.spec.budgets.max_imported_artifact_bytes:
                        raise PreparationAdmissionError("IMPORT_LIMIT_EXCEEDED")
                    if request.offset < record.received_bytes:
                        if request.offset + len(request.data) > record.received_bytes:
                            raise PreparationAdmissionError("IMPORT_CHUNK_CONFLICT")
                        stream.seek(request.offset)
                        if stream.read(len(request.data)) != request.data:
                            raise PreparationAdmissionError("IMPORT_CHUNK_CONFLICT")
                    elif request.offset != record.received_bytes or (
                        request.offset + len(request.data) > expected_size
                    ):
                        raise PreparationAdmissionError("IMPORT_OFFSET_INVALID")
                    else:
                        stream.seek(request.offset)
                        stream.write(request.data)
                        stream.flush()
                        os.fsync(stream.fileno())
                        record.received_bytes += len(request.data)
                        record.updated_at = now
                elif isinstance(request, ImportFinalize):
                    if record.received_bytes != expected_size:
                        raise PreparationAdmissionError("IMPORT_INCOMPLETE")
                    stream.flush()
                    os.fsync(stream.fileno())
            if isinstance(request, ImportFinalize):
                self._verify_file(path, expected_hash, expected_size)
                destination = self._object_path(expected_hash)
                if destination.exists():
                    self._verify_file(destination, expected_hash, expected_size)
                    path.unlink()
                else:
                    os.replace(path, destination)
                    _sync_directory(self._objects)
                self._publish_record(
                    session, request.artifact_ref, expected_hash, expected_size, now
                )
                record.state = "VERIFIED"
                record.updated_at = now
                return ImportCompleted(
                    request_message_id=request.message_id,
                    node_id=self._node_id,
                    import_id=request.import_id,
                    artifact_ref=request.artifact_ref,
                    sha256=expected_hash,
                    size_bytes=expected_size,
                )
            return ImportReady(
                request_message_id=request.message_id,
                node_id=self._node_id,
                import_id=request.import_id,
                artifact_ref=request.artifact_ref,
                next_offset=record.received_bytes,
            )

    def imported_bytes(self, ref: ArtifactRef) -> bytes:
        """Node-local read for verification/later E4; never a transport path disclosure."""
        with self._database.transaction() as session:
            row = session.get(ImportedArtifactRow, str(ref))
            if row is None:
                raise FileNotFoundError("Artifact import is not verified")
            path = self._object_path(row.content_key)
            self._verify_file(path, row.sha256, row.size_bytes)
            return path.read_bytes()

    def materialize(
        self, request: MaterializeSourceRequest, *, principal: str
    ) -> MaterializationResponse:
        """Publish only exact, reverified imported source under admitted E4 authority."""
        self._check_principal(principal)
        try:
            return self._materialize_checked(request, principal=principal)
        except (PreparationAdmissionError, MaterializationError, ConfinementUnavailable) as error:
            return MaterializationRejected(
                request_message_id=request.message_id,
                node_id=self._node_id,
                preparation_ref=request.preparation_ref,
                code=str(error),
            )
        except OSError:
            return MaterializationRejected(
                request_message_id=request.message_id,
                node_id=self._node_id,
                preparation_ref=request.preparation_ref,
                code="STORAGE_UNAVAILABLE",
            )

    def _materialize_checked(
        self, request: MaterializeSourceRequest, *, principal: str
    ) -> MaterializationResponse:
        if request.node_id != self._node_id:
            raise PreparationAdmissionError("WRONG_NODE")
        started_at = datetime.now(UTC)
        started = time.monotonic()
        with self._database.transaction() as session:
            authority = session.get(PreparationAuthorityRow, str(request.permit_ref))
            if authority is None or authority.principal_id != principal:
                raise PreparationAdmissionError("PREPARATION_NOT_ADMITTED")
            permit = PreparationPermit.model_validate(authority.permit_json)
            if (
                preparation_permit_digest(permit) != authority.authority_sha256
                or request.permit_sha256 != authority.authority_sha256
                or permit.permit_ref != request.permit_ref
                or permit.spec.preparation_ref != request.preparation_ref
                or permit.run_ref != request.run_ref
                or permit.spec.node_id != self._node_id
                or PreparationAction.MATERIALIZE_SOURCE not in permit.spec.allowed_actions
            ):
                raise PreparationAdmissionError("PREPARATION_AUTHORITY_MISMATCH")
            if not permit.not_before <= started_at < permit.expires_at:
                raise PreparationAdmissionError("PREPARATION_AUTHORITY_EXPIRED")
            run = session.get(RunRow, str(request.run_ref))
            if run is None or run.status != CapabilityRunStatus.QUEUED.value:
                raise PreparationAdmissionError("PREPARATION_RUN_NOT_ACTIVE")
            source = permit.spec.source
            raw = source.plan_source
            pins = (
                (raw.raw_artifact_ref, raw.raw_sha256, raw.raw_size_bytes),
                (raw.manifest_artifact_ref, raw.manifest_sha256, source.manifest_size_bytes),
            )
            for ref, digest, size in pins:
                record = session.get(ImportedArtifactRow, str(ref))
                transfer = session.get(
                    PreparationImportRow,
                    str(preparation_import_id(permit.permit_ref, ref)),
                )
                if (
                    record is None
                    or record.sha256 != digest
                    or record.size_bytes != size
                    or transfer is None
                    or transfer.permit_id != str(permit.permit_ref)
                    or transfer.state != "VERIFIED"
                    or transfer.sha256 != digest
                    or transfer.size_bytes != size
                ):
                    raise PreparationAdmissionError("IMPORTED_SOURCE_NOT_VERIFIED")
                self._verify_file(self._object_path(digest), digest, size)
            materialization_id = (
                "materialization:" + hashlib.sha256(str(permit.permit_ref).encode()).hexdigest()
            )
            key = materialization_id.removeprefix("materialization:")
            existing = session.get(PreparationMaterializationRow, str(request.preparation_ref))
            if existing is not None and (
                existing.permit_id != str(permit.permit_ref)
                or existing.run_id != str(permit.run_ref)
                or existing.materialization_id != materialization_id
            ):
                raise PreparationAdmissionError("MATERIALIZATION_IDENTITY_CONFLICT")
            if existing is not None and existing.state != "PUBLISHED":
                raise PreparationAdmissionError("MATERIALIZATION_NOT_REUSABLE")
            # A fresh trusted host proof is required even on exact reuse.
            proof = self._confinement.preflight()
            if not set(E4_REQUIRED_FEATURES) <= set(proof.features):
                raise ConfinementUnavailable("CONFINEMENT_UNAVAILABLE")
            if request.action == "CHECK":
                return MaterializationPreflight(
                    request_message_id=request.message_id,
                    node_id=self._node_id,
                    preparation_ref=request.preparation_ref,
                    permit_ref=permit.permit_ref,
                    run_ref=permit.run_ref,
                    raw_artifact_ref=raw.raw_artifact_ref,
                    raw_sha256=raw.raw_sha256,
                    manifest_artifact_ref=raw.manifest_artifact_ref,
                    manifest_sha256=raw.manifest_sha256,
                    confinement_backend=proof.backend,
                    confinement_version=proof.version,
                    proven_features=proof.features,
                )
            manifest_path = self._object_path(raw.manifest_sha256)
            if source.manifest_size_bytes > 16 * 1024 * 1024:
                raise MaterializationError("WORKSPACE_LIMIT_EXCEEDED")
            manifest = parse_manifest(
                manifest_path.read_bytes(),
                raw.raw_sha256,
                raw.raw_size_bytes,
                str(raw.resolved_commit),
                permit.spec.budgets,
            )
            destination = self._published / key
            if existing is not None:
                evidence = MaterializationEvidence.model_validate(existing.evidence_json)
                try:
                    verify_published(
                        destination,
                        manifest,
                        MaterializedTree(
                            evidence.file_count,
                            evidence.materialized_bytes,
                            evidence.tree_sha256,
                        ),
                    )
                except MaterializationError:
                    self._quarantine_path(destination, key)
                    existing.state = "QUARANTINED"
                    existing.error_code = "PREPARED_CONTENT_MISMATCH"
                    existing.updated_at = started_at
                    # Commit quarantine; a historical published record is never silently reused.
                    return MaterializationRejected(
                        request_message_id=request.message_id,
                        node_id=self._node_id,
                        preparation_ref=request.preparation_ref,
                        code="PREPARED_CONTENT_MISMATCH",
                    )
                return evidence
            self._ensure_materialization_dirs()
            row = PreparationMaterializationRow(
                preparation_id=str(request.preparation_ref),
                permit_id=str(permit.permit_ref),
                run_id=str(permit.run_ref),
                materialization_id=materialization_id,
                state="INCOMPLETE",
                evidence_json=None,
                error_code=None,
                started_at=started_at,
                updated_at=started_at,
            )
            session.add(row)
        # No ORM transaction spans untrusted compressed-byte processing.
        stage = self._staging / key
        if stage.exists() or destination.exists():
            self._quarantine_path(stage if stage.exists() else destination, key)
            self._mark_quarantined(request.preparation_ref, "MATERIALIZATION_INTERRUPTED")
            raise MaterializationError("PREPARATION_INTERRUPTED")
        stage.mkdir(mode=0o700)
        try:
            result = materialize_zip(
                self._object_path(raw.raw_sha256),
                manifest,
                stage,
                permit.spec.budgets,
                started=started,
                imported_bytes=raw.raw_size_bytes + source.manifest_size_bytes,
            )
            if time.monotonic() - started > permit.spec.budgets.max_total_runtime_seconds:
                raise MaterializationError("PREPARATION_TIMEOUT")
            with self._database.transaction() as session:
                authority = session.get(PreparationAuthorityRow, str(request.permit_ref))
                current_row = session.get(
                    PreparationMaterializationRow, str(request.preparation_ref)
                )
                if (
                    authority is None
                    or authority.authority_sha256 != request.permit_sha256
                    or current_row is None
                    or current_row.state != "INCOMPLETE"
                    or datetime.now(UTC) >= permit.expires_at
                ):
                    raise PreparationAdmissionError("PREPARATION_AUTHORITY_STALE")
                current_row.state = "VERIFIED"
                current_row.updated_at = datetime.now(UTC)
            os.replace(stage, destination)
            destination.chmod(0o555)
            _sync_directory(self._published)
            evidence = MaterializationEvidence(
                request_message_id=request.message_id,
                node_id=self._node_id,
                preparation_ref=request.preparation_ref,
                permit_ref=permit.permit_ref,
                permit_sha256=request.permit_sha256,
                run_ref=permit.run_ref,
                mission_ref=permit.spec.mission_ref,
                plan_ref=permit.spec.plan_ref,
                plan_intent_sha256=permit.spec.plan_intent_sha256,
                raw_artifact_ref=raw.raw_artifact_ref,
                raw_sha256=raw.raw_sha256,
                manifest_artifact_ref=raw.manifest_artifact_ref,
                manifest_sha256=raw.manifest_sha256,
                materialization_id=DomainRef(materialization_id),
                file_count=result.file_count,
                verified_entry_count=manifest.entry_count,
                materialized_bytes=result.byte_count,
                observed_temporary_bytes=(
                    raw.raw_size_bytes + source.manifest_size_bytes + result.byte_count
                ),
                observed_write_bytes=result.byte_count,
                observed_duration_seconds=time.monotonic() - started,
                budgets=permit.spec.budgets,
                tree_sha256=result.tree_sha256,
                confinement_backend=proof.backend,
                confinement_version=proof.version,
                proven_features=proof.features,
                started_at=started_at,
                published_at=datetime.now(UTC),
            )
            with self._database.transaction() as session:
                published_row = session.get(
                    PreparationMaterializationRow, str(request.preparation_ref)
                )
                assert published_row is not None
                published_row.state = "PUBLISHED"
                published_row.evidence_json = evidence.model_dump(mode="json")
                published_row.updated_at = evidence.published_at
            return evidence
        except (MaterializationError, PreparationAdmissionError, OSError) as error:
            self._quarantine_path(stage if stage.exists() else destination, key)
            code = (
                error.code
                if isinstance(error, (MaterializationError, PreparationAdmissionError))
                else "STORAGE_UNAVAILABLE"
            )
            self._mark_quarantined(request.preparation_ref, code)
            raise

    def _mark_quarantined(self, ref: object, code: str) -> None:
        with self._database.transaction() as session:
            row = session.get(PreparationMaterializationRow, str(ref))
            if row is not None:
                row.state = "QUARANTINED"
                row.error_code = code
                row.updated_at = datetime.now(UTC)

    def _quarantine_path(self, path: Path, key: str) -> None:
        if path.exists():
            if not path.is_symlink() and path.is_dir():
                path.chmod(0o700)
            destination = self._quarantine / f"{key}-{uuid4().hex}"
            os.replace(path, destination)

    def _ensure_materialization_dirs(self) -> None:
        # E4 owns this sibling of python-environments; mkdir(parents=True)
        # would otherwise create its intermediate root with umask-dependent 0777.
        prepare_owned_directory(self._materialization_root)
        for directory in (self._staging, self._published, self._quarantine):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _recover_materializations(self) -> None:
        with self._database.transaction() as session:
            rows = (
                session.query(PreparationMaterializationRow)
                .filter(PreparationMaterializationRow.state.in_(("INCOMPLETE", "VERIFIED")))
                .all()
            )
            if rows:
                self._ensure_materialization_dirs()
            for row in rows:
                key = row.materialization_id.removeprefix("materialization:")
                for path in (self._staging / key, self._published / key):
                    self._quarantine_path(path, key)
                row.state = "QUARANTINED"
                row.error_code = "PREPARATION_INTERRUPTED"
                row.updated_at = datetime.now(UTC)

    def _publish_record(
        self, session: object, ref: ArtifactRef, sha256: str, size: int, now: datetime
    ) -> None:
        from sqlalchemy.orm import Session

        assert isinstance(session, Session)
        row = session.get(ImportedArtifactRow, str(ref))
        if row is None:
            session.add(
                ImportedArtifactRow(
                    artifact_id=str(ref),
                    sha256=sha256,
                    size_bytes=size,
                    content_key=sha256,
                    verified_at=now,
                )
            )
        elif row.sha256 != sha256 or row.size_bytes != size:
            raise PreparationAdmissionError("ARTIFACT_IDENTITY_CONFLICT")

    def _retain_failure(self, request: ImportRequest, code: str) -> None:
        with self._database.transaction() as session:
            row = session.get(PreparationImportRow, str(request.import_id))
            if row is not None and row.state != "VERIFIED":
                row.error_code = code
                row.updated_at = datetime.now(UTC)
                if code in {"IMPORT_DIGEST_MISMATCH", "IMPORT_SIZE_MISMATCH"}:
                    row.state = "FAILED"

    def _partial_path(self, import_id: object) -> Path:
        digest = hashlib.sha256(str(import_id).encode()).hexdigest()
        return self._partials / f"{digest}.part"

    def _object_path(self, sha256: str) -> Path:
        return self._objects / sha256

    @staticmethod
    def _verify_file(path: Path, expected_hash: str, expected_size: int) -> None:
        try:
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
        except OSError:
            raise PreparationAdmissionError("IMPORT_STORAGE_UNAVAILABLE") from None
        if size != expected_size:
            raise PreparationAdmissionError("IMPORT_SIZE_MISMATCH")
        if digest.hexdigest() != expected_hash:
            raise PreparationAdmissionError("IMPORT_DIGEST_MISMATCH")

    @staticmethod
    def _check_principal(principal: str) -> None:
        if principal != TRUSTED_CORE_PRINCIPAL:
            raise PreparationAdmissionError("CORE_PRINCIPAL_REQUIRED")


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
