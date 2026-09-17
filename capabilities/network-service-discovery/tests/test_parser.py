"""Golden-fixture tests for the isolated Nmap XML adapter."""

from pathlib import Path

import pytest
from boberagent_capability_network_service_discovery.nmap import (
    NmapXmlError,
    parse_nmap_xml,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parser_extracts_tcp_states_and_conservative_service_metadata() -> None:
    records = parse_nmap_xml((FIXTURES / "multiple_services.xml").read_bytes())

    assert [(record.port, record.state) for record in records] == [
        (22, "open"),
        (80, "open"),
        (443, "open"),
        (8080, "filtered"),
        (8443, "closed"),
    ]
    assert records[0].service == "ssh"
    assert records[0].product == "OpenSSH"
    assert records[0].version == "9.6"
    assert records[1].observation_value() == {
        "transport": "tcp",
        "port": 80,
        "state": "open",
        "service": "http",
        "product": "Apache httpd",
        "version": "2.4.62",
    }
    assert records[2].service == "unknown"
    assert records[2].product is None
    assert records[3].service is None


def test_parser_handles_minimal_and_no_open_service_documents() -> None:
    minimal = parse_nmap_xml((FIXTURES / "minimal.xml").read_bytes())
    no_open = parse_nmap_xml((FIXTURES / "no_open_services.xml").read_bytes())

    assert minimal[0].port == 31337
    assert minimal[0].service is None
    assert not [record for record in no_open if record.state == "open"]


@pytest.mark.parametrize(
    "content",
    [
        (FIXTURES / "malformed.xml").read_bytes(),
        b"<!DOCTYPE nmaprun SYSTEM 'https://invalid.example/nmap.dtd'><nmaprun />",
        b"<unexpected />",
        b"<nmaprun><host><ports><port protocol='tcp' portid='0'><state state='open' />"
        b"</port></ports></host></nmaprun>",
    ],
)
def test_parser_rejects_malformed_or_unsafe_xml(content: bytes) -> None:
    with pytest.raises(NmapXmlError):
        parse_nmap_xml(content)
