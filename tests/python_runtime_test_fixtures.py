"""Synthetic E5-A claims only: no interpreter, filesystem or host probes."""

from datetime import timedelta
from typing import Literal

from boberagent_contracts import (
    ArtifactRef,
    ConfinementFeature,
    DomainRef,
    InterpreterEvidence,
    PythonBackendIdentity,
    PythonEnvironmentInventory,
    PythonInterpreterIdentity,
    PythonProviderOperation,
    PythonRuntimeAuthorityProjection,
    PythonRuntimeBinding,
    PythonRuntimeEnforcement,
    PythonRuntimeEvidence,
    PythonRuntimeNonActions,
    PythonRuntimeOutputEvidence,
    PythonRuntimeProfileIdentity,
    PythonRuntimeRequestBinding,
    PythonWritableMount,
    ResourceRef,
    preparation_permit_digest,
)
from plan_test_fixtures import NOW
from preparation_test_fixtures import manifest_fixture, permit_fixture


def runtime_authority_fixture() -> PythonRuntimeAuthorityProjection:
    permit = permit_fixture()
    binding = PythonRuntimeRequestBinding(
        schema_version="python-runtime-request-binding-v1",
        spec=permit.spec,
        permit_ref=permit.permit_ref,
        permit_sha256=preparation_permit_digest(permit),
        run_ref=permit.run_ref,
        materialization_id=DomainRef("materialization:synthetic"),
        source_tree_sha256="4" * 64,
        entrypoint_sha256=permit.spec.entrypoint.entry_sha256,
        profile=PythonRuntimeProfileIdentity(
            profile_id=permit.spec.profile.profile_id,
            profile_version="1",
            profile_sha256=permit.spec.profile_sha256,
            runtime_provider="python-stdlib@1",
            construction_version="python-stdlib@1",
            layout_version="m20-e5-python-layout@1",
        ),
    )
    return PythonRuntimeAuthorityProjection(permit=permit, binding=binding)


def runtime_binding_fixture() -> PythonRuntimeBinding:
    return PythonRuntimeBinding(
        schema_version="python-runtime-binding-v1",
        resource_ref=ResourceRef("resource-runtime-test"),
        request=runtime_authority_fixture().binding,
        interpreter=PythonInterpreterIdentity(
            summary=InterpreterEvidence(
                registry_tool="python-runtime-3.12",
                executable_sha256="5" * 64,
                python_version="3.12.7",
                platform="linux",
                abi="cpython-312",
                runtime_fingerprint="6" * 64,
            ),
            implementation="CPython",
            build_identity="synthetic-test-build",
            architecture="x86_64",
            soabi="cpython-312-x86_64-linux-gnu",
            cache_tag="cpython-312",
            base_layout="m20-e5-system-python@1",
            stdlib_layout="m20-e5-system-stdlib@1",
            closure_sha256="7" * 64,
        ),
        backend=PythonBackendIdentity(
            backend_id="linux-bwrap-cgroup",
            backend_version="1",
            profile_id="m20-e5-linux-bwrap-cgroup",
            profile_version="1",
            profile_sha256="8" * 64,
            binary_sha256="9" * 64,
            binary_version="0.11.0",
            helper_sha256="a" * 64,
        ),
    )


def runtime_evidence_fixture() -> PythonRuntimeEvidence:
    usage = manifest_fixture().usage
    mounts: tuple[Literal["/work/venv", "/work/tmp", "/work/home"], ...] = (
        "/work/venv",
        "/work/tmp",
        "/work/home",
    )
    return PythonRuntimeEvidence(
        schema_version="PythonRuntimeEvidence-v1",
        binding=runtime_binding_fixture(),
        workspace_correlation=DomainRef("workspace-test-runtime"),
        operation=PythonProviderOperation.VERIFY_ENVIRONMENT,
        environment=PythonEnvironmentInventory(
            namespace_prefix="/work/venv",
            pyvenv_config_sha256="b" * 64,
            inventory_sha256="c" * 64,
            file_count=2,
            total_bytes=500,
            copied_executable_sha256="5" * 64,
            permitted_links=("lib64->lib",),
            system_site_packages=False,
            pip_bootstrapped=False,
            pip_used=False,
        ),
        non_actions=PythonRuntimeNonActions(
            source_imported=False,
            source_compiled=False,
            entrypoint_executed=False,
            package_installed=False,
            activation_script_sourced=False,
            preparation_network="NONE",
        ),
        enforcement=PythonRuntimeEnforcement(
            kernel_version="synthetic-kernel",
            boot_generation=DomainRef("boot-test-generation"),
            verified_features=tuple(ConfinementFeature),
            process_mechanism="CGROUP_V2_PIDS_MAX",
            memory_mechanism="CGROUP_V2_MEMORY_MAX_ZERO_SWAP_GROUP_OOM",
            descendant_mechanism="CGROUP_KILL_SUPERVISED_PID_NAMESPACE",
            storage_mechanism="CAPPED_TMPFS_BOUNDED_TRUSTED_PUBLISHER",
            runtime_mechanism="SUPERVISED_MONOTONIC_DEADLINES",
            output_mechanism="COMBINED_CAPPED_PIPE_DRAIN",
            network_mechanism="EMPTY_NETWORK_NAMESPACE_NO_SOCKET_FDS",
            filesystem_policy="MINIMAL_READONLY_VIEW_NO_WRITABLE_HOST_BIND",
            source_visibility="ABSENT_DURING_PYTHON_OPERATIONS",
            effective_process_limit=2,
            effective_memory_bytes=1024**3,
            effective_swap_bytes=0,
            effective_process_seconds=30,
            effective_total_seconds=60,
            effective_output_bytes=1000,
            effective_write_bytes=10_000,
            writable_mounts=tuple(
                PythonWritableMount(
                    namespace_path=path,
                    mechanism="SIZED_INODE_BOUNDED_TMPFS",
                    max_bytes=1000,
                    max_inodes=10,
                )
                for path in mounts
            ),
            passed_probes=tuple(ConfinementFeature),
            pids_limit_events=0,
            oom_events=0,
            memory_peak_bytes=1024**2,
            processes_peak=1,
            descendants_empty=True,
        ),
        aggregate_usage=usage,
        e5_usage=usage,
        budget_ledger_correlation=DomainRef("budget-test-ledger"),
        outputs=PythonRuntimeOutputEvidence(
            stdout_bytes=50,
            stdout_sha256="d" * 64,
            stderr_bytes=50,
            stderr_sha256="e" * 64,
        ),
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=20),
        monotonic_duration_milliseconds=20_000,
        verification="VERIFIED",
        failure=None,
        evidence_artifact_refs=(ArtifactRef("artifact-runtime-evidence"),),
    )
