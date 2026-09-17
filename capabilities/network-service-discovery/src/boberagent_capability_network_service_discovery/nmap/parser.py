"""Pure, deterministic parsing of untrusted Nmap XML evidence."""

from __future__ import annotations

import re
import xml.etree.ElementTree as element_tree
from dataclasses import dataclass

from boberagent_contracts import JsonObject

_UNSAFE_DECLARATION = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


class NmapXmlError(ValueError):
    """Nmap XML was malformed or violated the expected bounded record shape."""


@dataclass(frozen=True, slots=True)
class NmapServiceRecord:
    transport: str
    port: int
    state: str
    service: str | None = None
    product: str | None = None
    version: str | None = None

    def observation_value(self) -> JsonObject:
        return {
            "transport": self.transport,
            "port": self.port,
            "state": self.state,
            "service": self.service,
            "product": self.product,
            "version": self.version,
        }


def parse_nmap_xml(content: bytes) -> tuple[NmapServiceRecord, ...]:
    """Parse explicit TCP port records without resolving external XML resources."""

    if _UNSAFE_DECLARATION.search(content) is not None:
        raise NmapXmlError("Nmap XML contains a forbidden document or entity declaration")
    try:
        root = element_tree.fromstring(content)
    except element_tree.ParseError as error:
        raise NmapXmlError("Nmap XML is malformed") from error
    if root.tag != "nmaprun":
        raise NmapXmlError("Nmap XML root element must be nmaprun")

    records: list[NmapServiceRecord] = []
    for port_element in root.findall("./host/ports/port"):
        if port_element.get("protocol") != "tcp":
            continue
        port = _parse_port(port_element.get("portid"))
        state_element = port_element.find("state")
        if state_element is None:
            raise NmapXmlError(f"TCP port {port} has no state element")
        state = _required_text(state_element.get("state"), field="state", port=port)
        service_element = port_element.find("service")
        records.append(
            NmapServiceRecord(
                transport="tcp",
                port=port,
                state=state.lower(),
                service=(
                    None if service_element is None else _optional_text(service_element.get("name"))
                ),
                product=(
                    None
                    if service_element is None
                    else _optional_text(service_element.get("product"))
                ),
                version=(
                    None
                    if service_element is None
                    else _optional_text(service_element.get("version"))
                ),
            )
        )
    return tuple(sorted(records, key=lambda record: (record.port, record.state)))


def _parse_port(raw: str | None) -> int:
    try:
        port = int(raw) if raw is not None else 0
    except ValueError as error:
        raise NmapXmlError("TCP port identifier is not an integer") from error
    if not 1 <= port <= 65535:
        raise NmapXmlError("TCP port identifier is outside 1-65535")
    return port


def _required_text(raw: str | None, *, field: str, port: int) -> str:
    value = _optional_text(raw)
    if value is None:
        raise NmapXmlError(f"TCP port {port} has no {field} value")
    return value


def _optional_text(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    return value or None
