"""Real Core/neutral transport/admission chain with a synthetic confined provider."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from boberagent_contracts import CapabilityRunStatus, DomainRef
from boberagent_core import (
    ArtifactStorageConfiguration,
    CapabilityRouter,
    CoreArtifactService,
    CoreDatabase,
    FilesystemArtifactStorage,
)
from boberagent_core.preparation import (
    CorePreparationDispatchService,
    CoreRuntimePreparationAdmissionService,
    PreparationDispatchError,
)
from boberagent_core.preparation.runtime import CorePythonRuntimeService
from boberagent_execution_node import (
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
)
from boberagent_execution_node.preparation.python_distribution import (
    PythonDistributionConfiguration,
)
from boberagent_execution_node.preparation.python_environment import PythonEnvironmentProvider
from boberagent_execution_node.preparation.runtime_confinement_models import ProbeEvidence
from boberagent_execution_node.preparation.runtime_service import NodePythonRuntimeService
from boberagent_transport import InMemoryTransport, PreparationTransport
from boberagent_transport.preparation_runtime import RuntimePreparationOperation
from boberagent_transport_mcp import (
    McpClientConfiguration,
    McpServerConfiguration,
    McpTransport,
    McpTransportServer,
)
from pydantic import SecretStr
from python_runtime_test_fixtures import runtime_binding_fixture
from test_python_environment import FakeEnvironmentBackend
from test_python_provenance import configured as configured
from test_runtime_preparation_e2 import NODE, _setup
from test_runtime_preparation_e4 import ControlledConfinement


class GenerationBackend(FakeEnvironmentBackend):
    async def run_environment_verify(
        self,
        distribution: PythonDistributionConfiguration,
        operation_id: DomainRef,
        environment_path: Path,
        helper_sha256: str,
        *,
        cancellation: object = None,
    ) -> ProbeEvidence:
        probe = await super().run_environment_verify(
            distribution,
            operation_id,
            environment_path,
            helper_sha256,
            cancellation=cancellation,
        )
        return probe.model_copy(update={"boot_generation": self.identity.boot_generation})


@pytest.mark.parametrize("carrier", ["memory", "mcp"])
def test_core_pump_construct_validate_disconnect_restart_exact_same_resource(
    tmp_path: Path,
    configured: PythonDistributionConfiguration,
    carrier: str,
) -> None:
    database, _plan, policy, approvals, registry, _old, request = _setup(tmp_path)
    request = request.model_copy(
        update={
            "budgets": request.budgets.model_copy(
                update=dict(
                    max_file_count=15000,
                    max_processes=11,
                    max_total_runtime_seconds=900,
                    max_memory_bytes=1024**3,
                    max_temporary_bytes=1024**3,
                    max_preparation_write_bytes=2 * 1024**3,
                    max_captured_output_bytes=200000,
                )
            )
        }
    )

    async def scenario() -> None:
        configuration = NodeConfiguration.for_runtime_directory(
            tmp_path / "node", configured_node_id=NODE
        )
        node = ExecutionNode(configuration, preparation_confinement=ControlledConfinement())
        await node.initialize()
        assert node.python_resources and node.python_environments and node.preparation
        # Backend injection stays in tests; production composition has no bypass.
        backend = GenerationBackend((configured.distribution_root / "bin/python3.12").read_bytes())
        # All synthetic controls/probes intentionally share this test generation.
        node.python_resources._boot = DomainRef("boot-a")
        provider = PythonEnvironmentProvider(
            distribution=configured,
            backend=backend,
            backend_identity=runtime_binding_fixture().backend,
            repository=node.python_environments,
        )
        node.python_runtime_service = NodePythonRuntimeService(provider, node.preparation)
        server = None
        transport: PreparationTransport
        if carrier == "memory":
            memory = InMemoryTransport(trusted_core_principal="boberagent-core")
            memory.register_node(ExecutionNodeTransportEndpoint(node))
            transport = memory
        else:
            server = McpTransportServer(
                endpoint=ExecutionNodeTransportEndpoint(node),
                configuration=McpServerConfiguration(
                    port=0, bearer_token=SecretStr("harmless-e5f-test")
                ),
            )
            await server.start()
            transport = McpTransport(
                McpClientConfiguration(
                    endpoint_url=server.endpoint_url,
                    node_id=NODE,
                    bearer_token=SecretStr("harmless-e5f-test"),
                )
            )
        await transport.connect()

        def clock() -> datetime:
            return datetime.now(UTC)

        admission = CoreRuntimePreparationAdmissionService(
            database, policy, approvals, registry, clock=clock
        )
        admitted = admission.admit(request)
        assert admitted.permit is not None
        ref = admitted.attempt.preparation_ref
        artifacts = CoreArtifactService(
            database,
            FilesystemArtifactStorage(ArtifactStorageConfiguration(root=tmp_path / "artifacts")),
        )
        dispatch = CorePreparationDispatchService(
            database,
            admission,
            registry,
            CapabilityRouter(registry, transport, clock=clock),
            transport,
            artifacts,
            clock=clock,
        )
        runtime = CorePythonRuntimeService(dispatch)
        try:
            await dispatch.dispatch_and_import(ref)
            source = await dispatch.materialize_source(ref)
            initial = await runtime.exchange(
                ref,
                materialization=source,
                operation=RuntimePreparationOperation.PREPARE_RUNTIME,
                attempt_id=DomainRef("prepare-first"),
            )
            # Explicit pump observes durable work; submission never returns a terminal Result.
            await asyncio.gather(*tuple(node.python_runtime_service._tasks.values()))
            assert initial.resource_ref is not None
            assert all(
                o.failure is None for o in node.python_resources.operations(initial.resource_ref)
            ), node.python_resources.operations(initial.resource_ref)
            prepared = await runtime.exchange(
                ref,
                materialization=source,
                operation=RuntimePreparationOperation.PREPARE_RUNTIME,
                attempt_id=DomainRef("prepare-first"),
            )
            assert prepared.current and prepared.current.validity.value == "UNCHECKED"
            assert prepared.resource_ref and prepared.evidence
            resource, binding = prepared.resource_ref, prepared.current.binding_sha256
            construction_sha = prepared.construction_sha256
            await runtime.exchange(
                ref,
                materialization=source,
                operation=RuntimePreparationOperation.REVALIDATE_RUNTIME,
                attempt_id=DomainRef("validation-first"),
                resource_ref=resource,
                binding_sha256=binding,
            )
            await transport.disconnect()  # Node owns worker, not the connection.
            await asyncio.gather(*tuple(node.python_runtime_service._tasks.values()))
            await transport.connect()
            status = await runtime.exchange(
                ref,
                materialization=source,
                operation=RuntimePreparationOperation.RUNTIME_STATUS,
                resource_ref=resource,
                binding_sha256=binding,
            )
            assert status.current and status.current.validity.value == "VALID"
            assert status.evidence and status.evidence.evidence_artifact_refs
            assert status.construction_sha256 == construction_sha
            # A forged sealed digest cannot start work or invalidate a valid Resource.
            before_wrong_binding = tuple(backend.calls)
            with pytest.raises(PreparationDispatchError):
                await runtime.exchange(
                    ref,
                    materialization=source,
                    operation=RuntimePreparationOperation.REVALIDATE_RUNTIME,
                    attempt_id=DomainRef("wrong-binding"),
                    resource_ref=resource,
                    binding_sha256="0" * 64,
                )
            assert node.python_resources.load(resource).validity.value == "VALID"
            assert tuple(backend.calls) == before_wrong_binding
            assert (
                await transport.query_run_status(NODE, admitted.permit.run_ref)
                is CapabilityRunStatus.QUEUED
            )
            retained_attempt = admission.get_attempt(ref)
            assert retained_attempt and retained_attempt.lifecycle.value == "DISPATCHED"
            assert node.store and node.store.pending_results() == ()
            old_calls = tuple(backend.calls)
            balances = node.python_resources.budget(resource)
            # A real close/reopen, not just a different repository over an open engine.
            await transport.disconnect()
            if server is not None:
                await server.stop()
            await node.shutdown()
            database.dispose()
            reopened = CoreDatabase(database.config)
            try:
                with reopened.unit_of_work() as work:
                    assert work.runs.get(admitted.permit.run_ref) is not None
                node = ExecutionNode(configuration, preparation_confinement=ControlledConfinement())
                await node.initialize()
                assert node.python_resources and node.python_environments and node.preparation
                boot = node.python_resources._boot
                backend.identity = backend.identity.model_copy(update={"boot_generation": boot})
                provider = PythonEnvironmentProvider(
                    distribution=configured,
                    backend=backend,
                    backend_identity=runtime_binding_fixture().backend,
                    repository=node.python_environments,
                )
                node.python_runtime_service = NodePythonRuntimeService(provider, node.preparation)
                if carrier == "memory":
                    memory = InMemoryTransport(trusted_core_principal="boberagent-core")
                    memory.register_node(ExecutionNodeTransportEndpoint(node))
                    transport = memory
                else:
                    server = McpTransportServer(
                        endpoint=ExecutionNodeTransportEndpoint(node),
                        configuration=McpServerConfiguration(
                            port=0, bearer_token=SecretStr("harmless-e5f-test")
                        ),
                    )
                    await server.start()
                    transport = McpTransport(
                        McpClientConfiguration(
                            endpoint_url=server.endpoint_url,
                            node_id=NODE,
                            bearer_token=SecretStr("harmless-e5f-test"),
                        )
                    )
                await transport.connect()
                # Existing services read durable Core state, with a newly opened transport.
                dispatch = CorePreparationDispatchService(
                    reopened,
                    admission,
                    registry,
                    CapabilityRouter(registry, transport, clock=clock),
                    transport,
                    artifacts,
                    clock=clock,
                )
                runtime = CorePythonRuntimeService(dispatch)
                status = await runtime.exchange(
                    ref,
                    materialization=source,
                    operation=RuntimePreparationOperation.RUNTIME_STATUS,
                    resource_ref=resource,
                    binding_sha256=binding,
                )
                assert status.current and status.current.validity.value == "UNCHECKED"
                assert status.construction_sha256 == construction_sha
                assert tuple(backend.calls) == old_calls
                assert node.python_resources.budget(resource) == balances
                await runtime.exchange(
                    ref,
                    materialization=source,
                    operation=RuntimePreparationOperation.REVALIDATE_RUNTIME,
                    attempt_id=DomainRef("validation-second"),
                    resource_ref=resource,
                    binding_sha256=binding,
                )
                await asyncio.gather(*tuple(node.python_runtime_service._tasks.values()))
                status = await runtime.exchange(
                    ref,
                    materialization=source,
                    operation=RuntimePreparationOperation.RUNTIME_STATUS,
                    resource_ref=resource,
                    binding_sha256=binding,
                )
                assert status.current and status.current.validity.value == "VALID"
                assert status.current.boot_generation == boot
                assert status.resource_ref == resource
                assert status.construction_sha256 == construction_sha
                assert tuple(backend.calls) == (*old_calls, "controls", "verify")
                assert node.store and node.store.pending_results() == ()
                retained_attempt = admission.get_attempt(ref)
                assert retained_attempt and retained_attempt.lifecycle.value == "DISPATCHED"
            finally:
                reopened.dispose()
        finally:
            await transport.disconnect()
            if server is not None:
                await server.stop()
            await node.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()
