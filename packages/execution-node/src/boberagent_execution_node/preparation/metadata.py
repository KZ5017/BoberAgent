"""Static Node-owned preparation metadata; implementation loading remains lazy."""

from boberagent_contracts import (
    CONTRACT_VERSION,
    CapabilityDefinition,
    ExecutionCharacteristics,
    ExecutionDuration,
    ExecutionInteraction,
    InteractionSurfaceDeclaration,
    OperationDefinition,
    ResultObjectType,
    RetrySemantics,
    SchemaDeclaration,
    SideEffectCategory,
    SideEffectDeclaration,
    SideEffectLevel,
)
from boberagent_contracts.runtime_preparation import RuntimePreparationInput

from .service import PREPARATION_PROVIDER_VERSION


def admission_definition() -> CapabilityDefinition:
    """Advertise exact E3 admission, not completed runtime preparation readiness."""
    return CapabilityDefinition(
        capability_id="runtime.prepare",
        contract_version=CONTRACT_VERSION,
        implementation_version=PREPARATION_PROVIDER_VERSION,
        title="Runtime preparation",
        description="Permit-bound source/runtime preparation and verified final evidence; never source execution.",
        operations=(
            OperationDefinition(
                name="prepare",
                title="Admit preparation",
                description="Queue a permit-bound preparation Run without executing source.",
                input_schema=SchemaDeclaration(inline=RuntimePreparationInput.model_json_schema()),
                result_types=(ResultObjectType.RESOURCE, ResultObjectType.ARTIFACT),
                retry_semantics=RetrySemantics.UNSAFE,
            ),
        ),
        execution=ExecutionCharacteristics(
            duration=ExecutionDuration.ONE_SHOT,
            interaction=ExecutionInteraction.STATELESS,
        ),
        interaction_surfaces=InteractionSurfaceDeclaration(
            local_compute=True,
            target_network=False,
            internet_access=False,
            active_session=False,
            managed_resource=True,
        ),
        side_effects=(
            SideEffectDeclaration(
                category=SideEffectCategory.LOCAL_FILESYSTEM,
                level=SideEffectLevel.WRITE,
            ),
        ),
        dependencies=(),
    )
