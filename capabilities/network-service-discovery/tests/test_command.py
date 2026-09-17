"""Semantic profile to managed Nmap argument-vector tests."""

from pathlib import Path

import pytest
from boberagent_capability_network_service_discovery import ServiceDiscoveryInput
from boberagent_capability_network_service_discovery.nmap import build_nmap_command
from boberagent_capability_network_service_discovery.profiles import ScanProfile
from boberagent_contracts import AssetRef
from boberagent_sdk import InputError
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("profile", "profile_args"),
    [
        (
            ScanProfile.QUICK,
            ("-sT", "-sV", "--version-light", "--top-ports", "100"),
        ),
        (ScanProfile.STANDARD, ("-sT", "-sV", "--top-ports", "1000")),
        (ScanProfile.FULL_TCP, ("-sT", "-sV", "-p-")),
    ],
)
def test_profiles_build_deterministic_argument_vectors(
    profile: ScanProfile, profile_args: tuple[str, ...]
) -> None:
    output = Path("/managed/workspace/nmap.xml")

    command = build_nmap_command(
        profile=profile,
        address="192.0.2.25",
        output_path=output,
    )

    assert command.tool == "nmap"
    assert command.args == ("-n", *profile_args, "-oX", str(output), "192.0.2.25")
    assert command.output_path == output
    assert all(isinstance(argument, str) for argument in command.args)


def test_ipv6_is_explicit_and_cli_like_target_is_rejected() -> None:
    output = Path("/managed/workspace/nmap.xml")
    ipv6 = build_nmap_command(
        profile=ScanProfile.QUICK,
        address="2001:db8::25",
        output_path=output,
    )

    assert ipv6.args[:2] == ("-n", "-6")
    with pytest.raises(InputError, match="usable network address"):
        build_nmap_command(
            profile=ScanProfile.STANDARD,
            address="--script=unsafe",
            output_path=output,
        )


def test_inputs_reject_provider_cli_fields_and_unbounded_timeout() -> None:
    with pytest.raises(ValidationError):
        ServiceDiscoveryInput.model_validate(
            {"asset_ref": "asset-command-test", "nmap_args": ["--script", "vuln"]}
        )
    with pytest.raises(ValidationError):
        ServiceDiscoveryInput(
            asset_ref=AssetRef("asset-command-test"),
            timeout_seconds=3601,
        )
