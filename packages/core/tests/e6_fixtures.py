"""Existing upstream synthetic fixtures, explicit fake enforcement; no real-host claim."""

import asyncio
from pathlib import Path

from boberagent_contracts import DomainRef
from boberagent_core import (
    ArtifactStorageConfiguration,
    CapabilityRegistry,
    CapabilityRouter,
    CoreArtifactReceiver,
    CoreArtifactService,
    CoreDatabase,
    CoreTransportReceiver,
    DatabaseConfig,
    FilesystemArtifactStorage,
    upgrade_database,
)
from boberagent_core.capabilities import CapabilityRegistrationClient
from boberagent_core.planning.approval import CorePlanApprovalService
from boberagent_core.preparation import (
    CorePreparationCompletionService,
    CorePreparationDispatchService,
    CoreRuntimePreparationAdmissionService,
)
from boberagent_core.preparation.runtime import CorePythonRuntimeService
from boberagent_core.results import ResultIngestionService
from boberagent_execution_node import (
    ArtifactSyncCoordinator,
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
)
from boberagent_execution_node.preparation.python_distribution import (
    PythonDistributionConfiguration,
)
from boberagent_execution_node.preparation.python_environment import PythonEnvironmentProvider
from boberagent_execution_node.preparation.runtime_service import NodePythonRuntimeService
from boberagent_transport import InMemoryTransport
from boberagent_transport.preparation_runtime import (
    PythonRuntimeAccepted,
    RuntimePreparationOperation,
)
from m20e5g_fixtures import establish_d
from python_runtime_test_fixtures import runtime_binding_fixture
from test_core_poc_acquisition import NOW
from test_python_revalidation_flow import GenerationBackend
from test_runtime_preparation_e4 import ControlledConfinement

NODE = "node-e6-test"


class E6Case:
    def __init__(self, root: Path, distribution: PythonDistributionConfiguration) -> None:
        self.root, self.distribution = root, distribution
        self.database = CoreDatabase(DatabaseConfig.sqlite(root / "core.sqlite3"))
        upgrade_database(self.database)
        self.policy, self.request = establish_d(self.database, root, NODE)
        self.node = ExecutionNode(
            NodeConfiguration.for_runtime_directory(root / "node", configured_node_id=NODE),
            preparation_confinement=ControlledConfinement(),
        )
        self.registry = CapabilityRegistry(self.database)
        self.admission = CoreRuntimePreparationAdmissionService(
            self.database,
            self.policy,
            CorePlanApprovalService(self.database, self.policy, clock=lambda: NOW),
            self.registry,
        )
        self.transport = InMemoryTransport(trusted_core_principal="boberagent-core")
        self.storage = FilesystemArtifactStorage(
            ArtifactStorageConfiguration(root=root / "artifacts")
        )
        self.artifacts = CoreArtifactService(self.database, self.storage)
        self.completion = CorePreparationCompletionService(self.database, self.artifacts)
        self.dispatch = CorePreparationDispatchService(
            self.database,
            self.admission,
            self.registry,
            CapabilityRouter(self.registry, self.transport),
            self.transport,
            self.artifacts,
        )
        self.backend = GenerationBackend(
            (distribution.distribution_root / "bin/python3.12").read_bytes()
        )
        self.runtime = CorePythonRuntimeService(self.dispatch)

    async def open(self, *, build: bool = True) -> None:
        await self.node.initialize()
        assert (
            self.node.python_resources and self.node.python_environments and self.node.preparation
        )
        boot = self.node.python_resources._boot
        self.backend.identity = self.backend.identity.model_copy(update={"boot_generation": boot})
        self.backend.proof_updates["boot_generation"] = boot
        provider = PythonEnvironmentProvider(
            distribution=self.distribution,
            backend=self.backend,
            backend_identity=runtime_binding_fixture().backend,
            repository=self.node.python_environments,
        )
        self.node.python_runtime_service = NodePythonRuntimeService(provider, self.node.preparation)
        self.transport.register_node(ExecutionNodeTransportEndpoint(self.node))
        self.transport.register_artifact_receiver(CoreArtifactReceiver(self.database, self.storage))
        await self.transport.connect()
        await CapabilityRegistrationClient(self.transport, self.registry).refresh_node(NODE)
        admission = self.admission.admit(self.request)
        assert admission.permit
        self.permit = admission.permit
        self.ref = admission.attempt.preparation_ref
        await self.dispatch.dispatch_and_import(self.ref)
        if not build:
            return
        self.source = await self.dispatch.materialize_source(self.ref)
        initial = await self.runtime.exchange(
            self.ref,
            materialization=self.source,
            operation=RuntimePreparationOperation.PREPARE_RUNTIME,
            attempt_id=DomainRef("e6-construct"),
        )
        await asyncio.gather(*tuple(self.node.python_runtime_service._tasks.values()))
        prepared = await self.runtime.exchange(
            self.ref,
            materialization=self.source,
            operation=RuntimePreparationOperation.PREPARE_RUNTIME,
            attempt_id=DomainRef("e6-construct"),
        )
        assert prepared.current and initial.resource_ref and prepared.construction_sha256
        await self.runtime.exchange(
            self.ref,
            materialization=self.source,
            operation=RuntimePreparationOperation.REVALIDATE_RUNTIME,
            attempt_id=DomainRef("e6-validation"),
            resource_ref=prepared.resource_ref,
            binding_sha256=prepared.current.binding_sha256,
        )
        await asyncio.gather(*tuple(self.node.python_runtime_service._tasks.values()))
        self.ready: PythonRuntimeAccepted = await self.runtime.exchange(
            self.ref,
            materialization=self.source,
            operation=RuntimePreparationOperation.RUNTIME_STATUS,
            resource_ref=prepared.resource_ref,
            binding_sha256=prepared.current.binding_sha256,
        )
        assert self.ready.current and self.ready.current.validity.value == "VALID"
        assert self.node.store and not self.node.store.pending_results()

    async def finalize(self) -> None:
        assert self.ready.resource_ref and self.ready.current
        await self.completion.finalize(
            self.dispatch,
            self.ref,
            materialization=self.source,
            resource_ref=self.ready.resource_ref,
            binding_sha256=self.ready.current.binding_sha256,
        )

    def reopen_core(self) -> None:
        configuration = self.database.config
        self.database.dispose()
        self.database = CoreDatabase(configuration)
        self.artifacts = CoreArtifactService(self.database, self.storage)
        self.completion = CorePreparationCompletionService(self.database, self.artifacts)
        self.transport.register_artifact_receiver(CoreArtifactReceiver(self.database, self.storage))

    async def deliver(self, *, acknowledge: bool = True) -> None:
        receiver = CoreTransportReceiver(
            self.database, result_ingestion=ResultIngestionService(self.database)
        )
        count = await self.transport.flush_outboxes(NODE)
        for _ in range(count):
            payload = await asyncio.wait_for(self.transport.receive(), 5)
            _, ack = receiver.accept(payload)
            if acknowledge:
                await self.transport.acknowledge(ack)

    def coordinator(self) -> ArtifactSyncCoordinator:
        assert self.node.store
        from boberagent_core.clock import utc_now

        return ArtifactSyncCoordinator(
            store=self.node.store,
            spool_root=self.node.configuration.artifact_spool_root,
            node_id=NODE,
            transport=self.transport,
            clock=utc_now,
            chunk_size=1024,
        )

    async def close(self) -> None:
        await self.transport.disconnect()
        await self.node.shutdown()
        self.database.dispose()
