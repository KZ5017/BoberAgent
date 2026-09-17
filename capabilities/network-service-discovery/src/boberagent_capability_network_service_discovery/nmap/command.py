"""Deterministic Nmap command construction behind semantic profiles."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path

from boberagent_sdk import InputError

from ..profiles import ScanProfile, profile_arguments

_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


@dataclass(frozen=True, slots=True)
class NmapCommand:
    """Structured managed-tool request, never a shell command."""

    tool: str
    args: tuple[str, ...]
    output_path: Path


def build_nmap_command(*, profile: ScanProfile, address: str, output_path: Path) -> NmapCommand:
    """Map semantic intent and one validated address to an Nmap argument vector."""

    selected_address, is_ipv6 = _validate_address(address)
    args = ["-n"]
    if is_ipv6:
        args.append("-6")
    args.extend(profile_arguments(profile))
    args.extend(("-oX", str(output_path), selected_address))
    return NmapCommand(tool="nmap", args=tuple(args), output_path=output_path)


def _validate_address(address: str) -> tuple[str, bool]:
    if (
        address != address.strip()
        or not address
        or any(character.isspace() for character in address)
    ):
        raise InputError("Asset primary address is not a usable network address")
    if address.startswith("-") or "\x00" in address:
        raise InputError("Asset primary address is not a usable network address")
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        labels = address.rstrip(".").split(".")
        if (
            len(address) > 253
            or not labels
            or any(_HOST_LABEL.fullmatch(label) is None for label in labels)
        ):
            raise InputError(
                "Asset primary address is not a usable IP address or hostname"
            ) from None
        return address, False
    return address, parsed.version == 6
