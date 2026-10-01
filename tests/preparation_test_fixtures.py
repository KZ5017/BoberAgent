"""M20-E1 typed intent and evidence, without admission or preparation side effects."""

from datetime import timedelta
from uuid import UUID

from boberagent_contracts import (
    ArtifactRef,
    CapabilityRunRef,
    PlanDecisionRef,
    PreparationPermitRef,
    ResourceRef,
    RuntimePreparationManifestRef,
    RuntimePreparationRef,
)
from boberagent_contracts.runtime_preparation import (
    ConfinementEvidence,
    ConfinementFeature,
    FixedEnvironmentEvidence,
    InterpreterEvidence,
    MaterializationEvidence,
    PreparationAction,
    PreparationAuthorityBoundary,
    PreparationBudgets,
    PreparationOutcome,
    PreparationPermit,
    PreparationSource,
    PreparationUsage,
    PythonEnvironmentEvidence,
    RuntimePreparationManifest,
    RuntimePreparationReceipt,
    RuntimePreparationSpec,
    initial_python_preparation_profile,
    preparation_manifest_digest,
    preparation_permit_digest,
    preparation_profile_digest,
    preparation_spec_fingerprint,
)
from plan_test_fixtures import NOW, plan_fixture


def spec_fixture() -> RuntimePreparationSpec:
    plan = plan_fixture()
    profile = initial_python_preparation_profile()
    return RuntimePreparationSpec(
        schema_version="runtime-preparation-spec-v1",
        preparation_ref=RuntimePreparationRef("preparation-test"),
        mission_ref=plan.mission_ref,
        plan_ref=plan.execution_plan_id,
        plan_intent_sha256="1" * 64,
        node_id="node-test",
        provider_id=UUID("00000000-0000-0000-0000-000000000001"),
        provider_version="1.0.0",
        source=PreparationSource(plan_source=plan.source, manifest_size_bytes=100),
        entrypoint=plan.entrypoint,
        runtime=plan.runtime,
        profile=profile,
        profile_sha256=preparation_profile_digest(profile),
        budgets=PreparationBudgets(
            max_imported_artifact_bytes=1000,
            max_materialized_bytes=1000,
            max_file_count=10,
            max_path_depth=5,
            max_temporary_bytes=10_000,
            max_preparation_write_bytes=10_000,
            max_processes=2,
            max_process_runtime_seconds=30,
            max_total_runtime_seconds=60,
            max_captured_output_bytes=1000,
            max_memory_bytes=1024**3,
        ),
        allowed_actions=tuple(PreparationAction),
    )


def permit_fixture(spec: RuntimePreparationSpec | None = None) -> PreparationPermit:
    selected = spec or spec_fixture()
    return PreparationPermit(
        schema_version="preparation-permit-v1",
        permit_ref=PreparationPermitRef("permit-test"),
        spec=selected,
        spec_sha256=preparation_spec_fingerprint(selected),
        run_ref=CapabilityRunRef("run-prepare"),
        validation_decision_ref=PlanDecisionRef("decision-validation"),
        validation_sha256="2" * 64,
        policy_decision_ref=PlanDecisionRef("decision-policy"),
        policy_context_sha256="3" * 64,
        policy_decision="ALLOW",
        approval_decision_ref=None,
        issued_at=NOW,
        not_before=NOW,
        expires_at=NOW + timedelta(hours=1),
        admission_nonce="nonce-test",
        maximum_preparation_runs=1,
        boundary=PreparationAuthorityBoundary(),
    )


def manifest_fixture(permit: PreparationPermit | None = None) -> RuntimePreparationManifest:
    selected = permit or permit_fixture()
    return RuntimePreparationManifest(
        schema_version="runtime-preparation-manifest-v1",
        manifest_ref=RuntimePreparationManifestRef("manifest-test"),
        spec=selected.spec,
        run_ref=selected.run_ref,
        permit_ref=selected.permit_ref,
        permit_sha256=preparation_permit_digest(selected),
        resource_ref=ResourceRef("resource-prepared"),
        workspace_correlation="workspace-prepared",
        materialization=MaterializationEvidence(
            verified=True,
            file_count=1,
            total_bytes=200,
            tree_sha256="4" * 64,
            entrypoint_sha256=selected.spec.entrypoint.entry_sha256,
        ),
        interpreter=InterpreterEvidence(
            registry_tool="python3",
            executable_sha256="5" * 64,
            python_version="3.12.7",
            platform="linux",
            abi="cpython-312",
            runtime_fingerprint="6" * 64,
        ),
        environment=PythonEnvironmentEvidence(
            system_site_packages=False,
            pip_bootstrapped=False,
            pip_used=False,
            source_imported=False,
            source_compiled=False,
            entrypoint_executed=False,
        ),
        external_installed_dependencies=(),
        usage=PreparationUsage(
            imported_bytes=300,
            materialized_bytes=200,
            file_count=1,
            temporary_bytes=500,
            preparation_write_bytes=500,
            peak_processes=1,
            process_runtime_seconds=10,
            total_runtime_seconds=20,
            captured_output_bytes=100,
            peak_memory_bytes=1024**2,
        ),
        confinement=ConfinementEvidence(
            backend_id="test-backend",
            backend_version="1",
            profile_id="test-profile",
            profile_version="1",
            verified_features=tuple(ConfinementFeature),
        ),
        fixed_environment=FixedEnvironmentEvidence(
            node_controlled_path=True,
            ambient_pythonpath=False,
            ambient_user_site=False,
            ambient_package_manager_config=False,
            activation_script_sourced=False,
        ),
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=20),
        outcome=PreparationOutcome.PREPARED,
        reason_code=None,
        evidence_artifact_refs=(ArtifactRef("artifact-preparation-log"),),
    )


def receipt_fixture(
    manifest: RuntimePreparationManifest | None = None,
) -> RuntimePreparationReceipt:
    selected = manifest or manifest_fixture()
    return RuntimePreparationReceipt(
        schema_version="runtime-preparation-receipt-v1",
        preparation_ref=selected.spec.preparation_ref,
        run_ref=selected.run_ref,
        resource_ref=selected.resource_ref,
        manifest_ref=selected.manifest_ref,
        manifest_artifact_ref=ArtifactRef("artifact-runtime-manifest"),
        manifest_sha256=preparation_manifest_digest(selected),
        manifest_size_bytes=len(selected.model_dump_json().encode()),
        permit_ref=selected.permit_ref,
        permit_sha256=selected.permit_sha256,
        node_id=selected.spec.node_id,
        provider_id=selected.spec.provider_id,
        provider_version=selected.spec.provider_version,
        outcome=PreparationOutcome.PREPARED,
        reason_code=None,
    )
