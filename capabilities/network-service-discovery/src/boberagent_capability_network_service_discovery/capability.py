"""Production ``network.service_discovery`` capability implementation."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid5

from boberagent_contracts import (
    ArtifactDescriptor,
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRunStatus,
    Diagnostic,
    DiagnosticSeverity,
    JsonObject,
    Observation,
    ObservationRef,
)
from boberagent_sdk import Capability, ExecutionContext, InputError
from pydantic import BaseModel

from .inputs import ServiceDiscoveryInput
from .nmap import NmapServiceRecord, NmapXmlError, build_nmap_command, parse_nmap_xml

_OBSERVATION_NAMESPACE = UUID("f06a4871-a07f-5c90-9bf2-1a6554ec2448")
_XML_FILENAME = "nmap.xml"


class NetworkServiceDiscoveryCapability(Capability):
    """Discover open TCP services for one authorized Asset."""

    capability_id = "network.service_discovery"

    async def execute(
        self,
        operation: str,
        ctx: ExecutionContext,
        inputs: BaseModel,
    ) -> CapabilityResult:
        if operation != "discover" or not isinstance(inputs, ServiceDiscoveryInput):
            raise InputError("network.service_discovery supports only validated discover inputs")

        await ctx.cancellation.checkpoint()
        asset = await ctx.entities.asset(inputs.asset_ref)
        await ctx.scope.assert_asset_allowed(inputs.asset_ref)
        await ctx.scope.assert_address_allowed(asset.primary_address)
        workspace = await ctx.workspace.create(purpose="network-service-discovery")
        command = build_nmap_command(
            profile=inputs.profile,
            address=asset.primary_address,
            output_path=workspace.path / _XML_FILENAME,
        )

        await ctx.events.progress(
            message="TCP service discovery started",
            current=0,
            total=1,
            metadata={"asset_ref": str(inputs.asset_ref), "profile": inputs.profile.value},
        )
        process = await ctx.processes.run_tool(
            tool=command.tool,
            args=command.args,
            timeout=inputs.timeout_seconds,
        )
        artifact = await _preserve_xml(ctx, command.output_path, inputs)

        if process.cancelled:
            return _execution_failure(
                ctx=ctx,
                status=CapabilityRunStatus.CANCELLED,
                code="NMAP_CANCELLED",
                message="Nmap service discovery was cancelled.",
                artifact=artifact,
            )
        if process.timed_out:
            return _execution_failure(
                ctx=ctx,
                status=CapabilityRunStatus.TIMED_OUT,
                code="NMAP_TIMED_OUT",
                message="Nmap service discovery exceeded its configured timeout.",
                artifact=artifact,
            )
        if process.exit_code != 0:
            return _execution_failure(
                ctx=ctx,
                status=CapabilityRunStatus.FAILED,
                code="NMAP_EXIT_NONZERO",
                message="Nmap service discovery exited unsuccessfully.",
                artifact=artifact,
                details={"exit_code": process.exit_code},
            )
        if artifact is None:
            return _execution_failure(
                ctx=ctx,
                status=CapabilityRunStatus.FAILED,
                code="NMAP_XML_MISSING",
                message="Nmap completed without producing the required XML evidence.",
            )

        xml_content = await ctx.artifacts.read_bytes(artifact.artifact_id)
        try:
            parsed = parse_nmap_xml(xml_content)
        except NmapXmlError as error:
            return CapabilityResult(
                run_ref=ctx.invocation.run_id,
                execution_status=CapabilityRunStatus.COMPLETED,
                outcome=CapabilityOutcome(
                    category=CapabilityOutcomeCategory.UNKNOWN,
                    code="NMAP_XML_INVALID",
                    summary="Nmap evidence was preserved but could not be normalized.",
                ),
                artifacts=(artifact,),
                diagnostics=(
                    _diagnostic(
                        ctx=ctx,
                        code="NMAP_XML_INVALID",
                        severity=DiagnosticSeverity.ERROR,
                        message=str(error),
                        artifact=artifact,
                    ),
                ),
            )

        observations = tuple(
            _observation(ctx, inputs, record, artifact)
            for record in parsed
            if record.state == "open"
        )
        await ctx.events.progress(
            message="TCP service discovery completed",
            current=1,
            total=1,
            metadata={"open_services": len(observations)},
        )
        if observations:
            outcome = CapabilityOutcome(
                category=CapabilityOutcomeCategory.SUCCESS,
                code="SERVICES_DISCOVERED",
                summary=f"Discovered {len(observations)} open TCP service(s).",
                details={"open_service_count": len(observations)},
            )
        else:
            outcome = CapabilityOutcome(
                category=CapabilityOutcomeCategory.NEGATIVE,
                code="NO_OPEN_SERVICES",
                summary="The scan completed without discovering open TCP services.",
                details={"open_service_count": 0},
            )
        return CapabilityResult(
            run_ref=ctx.invocation.run_id,
            execution_status=CapabilityRunStatus.COMPLETED,
            outcome=outcome,
            observations=observations,
            artifacts=(artifact,),
        )


async def _preserve_xml(
    ctx: ExecutionContext,
    output_path: Path,
    inputs: ServiceDiscoveryInput,
) -> ArtifactDescriptor | None:
    if not output_path.is_file():
        return None
    return await ctx.artifacts.create_from_file(
        artifact_type="network_scan.nmap_xml",
        path=output_path,
        media_type="application/xml",
        metadata={
            "provider": "nmap",
            "profile": inputs.profile.value,
            "asset_ref": str(inputs.asset_ref),
        },
    )


def _observation(
    ctx: ExecutionContext,
    inputs: ServiceDiscoveryInput,
    record: NmapServiceRecord,
    artifact: ArtifactDescriptor,
) -> Observation:
    identity = f"{ctx.invocation.run_id}\0{inputs.asset_ref}\0{record.transport}\0{record.port}"
    return Observation(
        observation_id=ObservationRef(
            f"observation-network-service-{uuid5(_OBSERVATION_NAMESPACE, identity)}"
        ),
        type="network.service",
        subject_ref=inputs.asset_ref,
        value=record.observation_value(),
        run_ref=ctx.invocation.run_id,
        observed_at=ctx.clock.now(),
        confidence=1.0,
        evidence_refs=(artifact.artifact_id,),
    )


def _execution_failure(
    *,
    ctx: ExecutionContext,
    status: CapabilityRunStatus,
    code: str,
    message: str,
    artifact: ArtifactDescriptor | None = None,
    details: JsonObject | None = None,
) -> CapabilityResult:
    artifacts = () if artifact is None else (artifact,)
    return CapabilityResult(
        run_ref=ctx.invocation.run_id,
        execution_status=status,
        outcome=CapabilityOutcome(
            category=CapabilityOutcomeCategory.UNKNOWN,
            code=code,
            summary=message,
        ),
        artifacts=artifacts,
        diagnostics=(
            _diagnostic(
                ctx=ctx,
                code=code,
                severity=DiagnosticSeverity.ERROR,
                message=message,
                artifact=artifact,
                details=details,
            ),
        ),
    )


def _diagnostic(
    *,
    ctx: ExecutionContext,
    code: str,
    severity: DiagnosticSeverity,
    message: str,
    artifact: ArtifactDescriptor | None = None,
    details: JsonObject | None = None,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        severity=severity,
        message=message,
        occurred_at=ctx.clock.now(),
        run_ref=ctx.invocation.run_id,
        details={} if details is None else details,
        artifact_refs=() if artifact is None else (artifact.artifact_id,),
    )
