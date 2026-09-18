"""SDK-only production capability tests with FakeExecutionContext."""

import asyncio
from pathlib import Path

import pytest
from boberagent_capability_network_service_discovery import (
    NetworkServiceDiscoveryCapability,
    ScanProfile,
    ServiceDiscoveryInput,
)
from boberagent_capability_network_service_discovery.nmap import build_nmap_command
from boberagent_contracts import (
    AssetRef,
    CapabilityOutcomeCategory,
    CapabilityRunStatus,
)
from boberagent_sdk import AssetSnapshot, ProcessResult, ScopeViolation
from boberagent_sdk.testing import FakeExecutionContext

FIXTURES = Path(__file__).parent / "fixtures"
ASSET_REF = AssetRef("asset-service-discovery")
ADDRESS = "192.0.2.25"


def _configured_context(
    xml_fixture: str | None,
    *,
    process_result: ProcessResult | None = None,
) -> tuple[FakeExecutionContext, Path]:
    context = FakeExecutionContext()
    context.entities.add(AssetSnapshot(ref=ASSET_REF, primary_address=ADDRESS))
    context.scope.allow_asset(ASSET_REF)
    context.scope.allow_address(ADDRESS)
    xml_path = context.workspace.root_path / "workspace-0001" / "nmap.xml"
    command = build_nmap_command(
        profile=ScanProfile.STANDARD,
        address=ADDRESS,
        output_path=xml_path,
    )
    context.processes.expect_tool(
        tool="nmap",
        args=command.args,
        timeout=600.0,
        result=process_result or ProcessResult(exit_code=0),
        file_outputs=(
            None if xml_fixture is None else {xml_path: (FIXTURES / xml_fixture).read_bytes()}
        ),
    )
    return context, xml_path


def test_capability_discovers_open_services_and_preserves_xml() -> None:
    async def scenario() -> None:
        context, _xml_path = _configured_context("multiple_services.xml")
        async with context:
            result = await NetworkServiceDiscoveryCapability().execute(
                "discover",
                context,
                ServiceDiscoveryInput(asset_ref=ASSET_REF),
            )
            context.processes.assert_expectations_met()

            assert result.execution_status is CapabilityRunStatus.COMPLETED
            assert result.outcome.category is CapabilityOutcomeCategory.SUCCESS
            values = [observation.value for observation in result.observations]
            assert all(isinstance(value, dict) for value in values)
            assert [value["port"] for value in values if isinstance(value, dict)] == [22, 80, 443]
            assert all(observation.type == "network.service" for observation in result.observations)
            assert all(observation.subject_ref == ASSET_REF for observation in result.observations)
            artifact = result.artifacts[0]
            assert artifact.artifact_type == "network_scan.nmap_xml"
            assert artifact.media_type == "application/xml"
            assert (
                await context.artifacts.read_bytes(artifact.artifact_id)
                == (FIXTURES / "multiple_services.xml").read_bytes()
            )
            assert all(
                observation.evidence_refs == (artifact.artifact_id,)
                for observation in result.observations
            )

    asyncio.run(scenario())


def test_capability_normalizes_real_nmap_doctype_output() -> None:
    async def scenario() -> None:
        context, _xml_path = _configured_context("modern_nmap_7.xml")
        async with context:
            result = await NetworkServiceDiscoveryCapability().execute(
                "discover",
                context,
                ServiceDiscoveryInput(asset_ref=ASSET_REF),
            )
            context.processes.assert_expectations_met()

            assert result.execution_status is CapabilityRunStatus.COMPLETED
            assert result.outcome.category is CapabilityOutcomeCategory.SUCCESS
            assert len(result.observations) == 1
            assert result.observations[0].type == "network.service"
            assert result.observations[0].value == {
                "transport": "tcp",
                "port": 80,
                "state": "open",
                "service": "http",
                "product": "SimpleHTTPServer",
                "version": "0.6",
            }
            assert not any(
                diagnostic.code == "NMAP_XML_INVALID" for diagnostic in result.diagnostics
            )
            assert (
                await context.artifacts.read_bytes(result.artifacts[0].artifact_id)
                == (FIXTURES / "modern_nmap_7.xml").read_bytes()
            )

    asyncio.run(scenario())


def test_valid_scan_with_no_open_service_is_negative() -> None:
    async def scenario() -> None:
        context, _xml_path = _configured_context("no_open_services.xml")
        async with context:
            result = await NetworkServiceDiscoveryCapability().execute(
                "discover",
                context,
                ServiceDiscoveryInput(asset_ref=ASSET_REF),
            )
            assert result.execution_status is CapabilityRunStatus.COMPLETED
            assert result.outcome.category is CapabilityOutcomeCategory.NEGATIVE
            assert result.observations == ()
            assert len(result.artifacts) == 1

    asyncio.run(scenario())


def test_malformed_xml_preserves_evidence_and_returns_unknown() -> None:
    async def scenario() -> None:
        context, _xml_path = _configured_context("malformed.xml")
        async with context:
            result = await NetworkServiceDiscoveryCapability().execute(
                "discover",
                context,
                ServiceDiscoveryInput(asset_ref=ASSET_REF),
            )
            assert result.execution_status is CapabilityRunStatus.COMPLETED
            assert result.outcome.category is CapabilityOutcomeCategory.UNKNOWN
            assert result.observations == ()
            assert result.diagnostics[0].code == "NMAP_XML_INVALID"
            assert result.diagnostics[0].artifact_refs == (result.artifacts[0].artifact_id,)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("process_result", "expected_status", "expected_code"),
    [
        (ProcessResult(timed_out=True), CapabilityRunStatus.TIMED_OUT, "NMAP_TIMED_OUT"),
        (ProcessResult(cancelled=True), CapabilityRunStatus.CANCELLED, "NMAP_CANCELLED"),
        (ProcessResult(exit_code=2), CapabilityRunStatus.FAILED, "NMAP_EXIT_NONZERO"),
    ],
)
def test_process_terminal_semantics_remain_distinct_and_preserve_evidence(
    process_result: ProcessResult,
    expected_status: CapabilityRunStatus,
    expected_code: str,
) -> None:
    async def scenario() -> None:
        context, _xml_path = _configured_context(
            "minimal.xml",
            process_result=process_result,
        )
        async with context:
            result = await NetworkServiceDiscoveryCapability().execute(
                "discover",
                context,
                ServiceDiscoveryInput(asset_ref=ASSET_REF),
            )
            assert result.execution_status is expected_status
            assert result.outcome.category is CapabilityOutcomeCategory.UNKNOWN
            assert result.diagnostics[0].code == expected_code
            assert len(result.artifacts) == 1

    asyncio.run(scenario())


def test_missing_xml_is_an_execution_failure() -> None:
    async def scenario() -> None:
        context, _xml_path = _configured_context(None)
        async with context:
            result = await NetworkServiceDiscoveryCapability().execute(
                "discover",
                context,
                ServiceDiscoveryInput(asset_ref=ASSET_REF),
            )
            assert result.execution_status is CapabilityRunStatus.FAILED
            assert result.diagnostics[0].code == "NMAP_XML_MISSING"
            assert result.artifacts == ()

    asyncio.run(scenario())


def test_scope_denial_happens_before_nmap_invocation() -> None:
    async def scenario() -> None:
        context = FakeExecutionContext()
        context.entities.add(AssetSnapshot(ref=ASSET_REF, primary_address=ADDRESS))
        async with context:
            try:
                await NetworkServiceDiscoveryCapability().execute(
                    "discover",
                    context,
                    ServiceDiscoveryInput(asset_ref=ASSET_REF),
                )
            except ScopeViolation:
                pass
            else:
                raise AssertionError("scope denial did not stop capability execution")
            assert context.processes.invocations == []

    asyncio.run(scenario())


def test_address_scope_denial_happens_before_nmap_invocation() -> None:
    async def scenario() -> None:
        context = FakeExecutionContext()
        context.entities.add(AssetSnapshot(ref=ASSET_REF, primary_address=ADDRESS))
        context.scope.allow_asset(ASSET_REF)
        async with context:
            with pytest.raises(ScopeViolation):
                await NetworkServiceDiscoveryCapability().execute(
                    "discover",
                    context,
                    ServiceDiscoveryInput(asset_ref=ASSET_REF),
                )
            assert context.processes.invocations == []

    asyncio.run(scenario())
