#!/usr/bin/env python3
"""Deterministic test-only stand-in for the Nmap executable."""

from __future__ import annotations

import sys
from pathlib import Path

XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<nmaprun scanner="nmap" args="test-shim">
  <host>
    <status state="up" />
    <address addr="192.0.2.25" addrtype="ipv4" />
    <ports>
      <port protocol="tcp" portid="22">
        <state state="open" />
        <service name="ssh" product="OpenSSH" version="9.6" />
      </port>
      <port protocol="tcp" portid="80">
        <state state="open" />
        <service name="http" product="Test HTTP Server" version="1.0" />
      </port>
    </ports>
  </host>
  <runstats><finished exit="success" /></runstats>
</nmaprun>
"""


def main() -> int:
    try:
        output_index = sys.argv.index("-oX") + 1
        output_path = Path(sys.argv[output_index])
    except (ValueError, IndexError):
        print("missing -oX output path", file=sys.stderr)
        return 2
    output_path.write_bytes(XML)
    print("test Nmap shim completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
