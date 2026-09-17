"""Tool-independent service-discovery profile vocabulary."""

from enum import StrEnum


class ScanProfile(StrEnum):
    """Bounded assessment intents mapped internally to the current provider."""

    QUICK = "quick"
    STANDARD = "standard"
    FULL_TCP = "full_tcp"


_PROFILE_ARGUMENTS: dict[ScanProfile, tuple[str, ...]] = {
    ScanProfile.QUICK: ("-sT", "-sV", "--version-light", "--top-ports", "100"),
    ScanProfile.STANDARD: ("-sT", "-sV", "--top-ports", "1000"),
    ScanProfile.FULL_TCP: ("-sT", "-sV", "-p-"),
}


def profile_arguments(profile: ScanProfile) -> tuple[str, ...]:
    """Return a deterministic, controlled Nmap argument fragment."""

    return _PROFILE_ARGUMENTS[profile]
