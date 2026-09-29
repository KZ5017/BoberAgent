"""Synthetic retained identities only; D2 tests never run research/inspection/execution."""

from boberagent_contracts import AssetRef, ExecutionPlanV2
from boberagent_core import Asset, CoreDatabase, Mission
from boberagent_core.inspections.classification_models import SupportClassification
from boberagent_core.persistence.orm import (
    ArtifactRow,
    CapabilityRunRow,
    PoCAcquisitionRow,
    PoCCandidateRow,
    PoCInspectionRow,
    ResearchAttemptRow,
    ResearchSourceHitRow,
    VulnerabilityHypothesisRow,
)
from boberagent_core.planning import (
    DecisionContext,
    InitialPlanPolicyProfile,
    PlanningAttempt,
    PlanningAttemptLifecycle,
    PlanningAttemptRef,
    PlanningDisposition,
    PlanningRequest,
)
from plan_test_fixtures import NOW, plan_fixture
from sqlalchemy import insert
from test_planning_domain import request_fixture


def seed(database: CoreDatabase) -> None:
    request = request_fixture(SupportClassification.AUTOMATIC)
    with database.unit_of_work() as work:
        work.missions.add(Mission(mission_ref=request.mission_ref, status="ACTIVE", created_at=NOW))
        work.assets.add(
            Asset(
                asset_ref=AssetRef("asset-d1"),
                mission_ref=request.mission_ref,
                kind="host",
                primary_address="127.0.0.1",
                created_at=NOW,
            )
        )
    with database._migration_engine.begin() as connection:
        connection.execute(
            insert(CapabilityRunRow).values(
                run_id="run-evidence-d2",
                mission_id="mission-d1",
                capability_id="test.retained_evidence",
                operation="collect",
                status="COMPLETED",
                created_at=NOW,
                finished_at=NOW,
            )
        )
        connection.execute(
            insert(VulnerabilityHypothesisRow).values(
                hypothesis_id="hypothesis-d1",
                mission_id="mission-d1",
                asset_id="asset-d1",
                claim="synthetic",
                vulnerability_ids_json=[],
                observation_refs_json=[],
                provenance="fixture",
                status="CANDIDATE",
                created_at=NOW,
            )
        )
        connection.execute(
            insert(PoCCandidateRow).values(
                candidate_id="candidate-d1",
                mission_id="mission-d1",
                hypothesis_id="hypothesis-d1",
                source_identity="fixture:source",
                source_class="REPOSITORY",
                source_uri="https://example.invalid/fixture",
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
        )
        connection.execute(
            insert(ResearchAttemptRow).values(
                attempt_id="research-d2",
                hypothesis_id="hypothesis-d1",
                provider_id="fixture",
                request_json={},
                status="COMPLETED",
                started_at=NOW,
                finished_at=NOW,
            )
        )
        connection.execute(
            insert(ResearchSourceHitRow).values(
                hit_id=1,
                attempt_id="research-d2",
                candidate_id="candidate-d1",
                provider_id="fixture",
                source_json={},
                source_identity="fixture:source",
                decision="ACCEPTED",
                observed_at=NOW,
            )
        )
        for ref, digest in (("artifact-raw", "a" * 64), ("artifact-manifest", "b" * 64)):
            connection.execute(
                insert(ArtifactRow).values(
                    artifact_id=ref,
                    artifact_type="fixture.raw",
                    run_id="run-evidence-d2",
                    storage_ref="fixture:" + ref,
                    created_at=NOW,
                    sha256=digest,
                    size_bytes=200,
                    metadata_json={},
                    content_state="METADATA_ONLY",
                    received_bytes=0,
                )
            )
        connection.execute(
            insert(PoCAcquisitionRow).values(
                acquisition_id="acquisition-d1",
                mission_id="mission-d1",
                hypothesis_id="hypothesis-d1",
                candidate_id="candidate-d1",
                selected_hit_id=1,
                research_attempt_id="research-d2",
                research_provider_id="fixture",
                source_identity="fixture:source",
                source_uri="https://example.invalid/fixture",
                repository_uri="https://example.invalid/fixture",
                provider_repository_id=1,
                historical_ref="commit:" + "c" * 40,
                bounds_json={},
                status="COMPLETED",
                resolved_commit_sha="c" * 40,
                raw_artifact_id="artifact-raw",
                raw_archive_sha256="a" * 64,
                raw_archive_size_bytes=200,
                manifest_artifact_id="artifact-manifest",
                manifest_sha256="b" * 64,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        for ref, profile in (
            ("inspection-c2", "m20-c2-deterministic"),
            ("inspection-c3", "m20-c3-support-classifier"),
        ):
            connection.execute(
                insert(PoCInspectionRow).values(
                    inspection_id=ref,
                    mission_id="mission-d1",
                    hypothesis_id="hypothesis-d1",
                    candidate_id="candidate-d1",
                    acquisition_id="acquisition-d1",
                    raw_artifact_id="artifact-raw",
                    raw_sha256="a" * 64,
                    raw_size_bytes=200,
                    manifest_artifact_id="artifact-manifest",
                    manifest_sha256="b" * 64,
                    resolved_commit_sha="c" * 40,
                    profile_id=profile,
                    profile_version="2",
                    config_fingerprint="f" * 64,
                    limits_json={},
                    selected_paths_json=[],
                    status="COMPLETED",
                    created_at=NOW,
                    started_at=NOW,
                    finished_at=NOW,
                    document_json=request.inspection.classification.model_dump(mode="json")
                    if ref == "inspection-c3"
                    else None,
                )
            )


def attempt_fixture(
    ref: str = "planning-d2",
    *,
    classification: SupportClassification = SupportClassification.AUTOMATIC,
    request: PlanningRequest | None = None,
) -> PlanningAttempt:
    return PlanningAttempt(
        planning_attempt_ref=PlanningAttemptRef(ref),
        request=request or request_fixture(classification),
        lifecycle=PlanningAttemptLifecycle.REQUESTED,
        disposition=PlanningDisposition.UNSUPPORTED
        if classification is SupportClassification.UNSUPPORTED
        else None,
        created_at=NOW,
        updated_at=NOW,
    )


def finalize(
    database: CoreDatabase, attempt: PlanningAttempt, plan: ExecutionPlanV2 | None = None
) -> None:
    from boberagent_contracts import execution_intent_digest

    plan = plan or plan_fixture()
    with database.unit_of_work() as work:
        work.planning_attempts.add(attempt)
        work.planning_attempts.finalize(
            attempt.planning_attempt_ref,
            plan,
            intent_sha256=execution_intent_digest(plan),
            expected_state=attempt.lifecycle,
            expected_revision=0,
            completed_at=NOW,
        )


def context_fixture(attempt: PlanningAttempt, digest: str) -> DecisionContext:
    return DecisionContext(
        mission_ref=attempt.request.mission_ref,
        intent_sha256=digest,
        scope_sha256="f" * 64,
        classification_sha256=attempt.request.inspection.classification_sha256,
        validation_profile="m20-d-validation",
        validation_version="1",
        policy=InitialPlanPolicyProfile(maximum_limits=plan_fixture().limits),
    )
