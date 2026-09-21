"""Harmless controlled client for the manual incoming Session smoke test."""

from __future__ import annotations

import argparse
import socket


def main() -> None:
    parser = argparse.ArgumentParser(description="Send/receive known listener smoke-test bytes")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    arguments = parser.parse_args()
    with socket.create_connection(
        (arguments.host, arguments.port), timeout=arguments.timeout_seconds
    ) as connection:
        connection.sendall(b"hello-boberagent")
        received = connection.recv(4096)
    if received != b"pong-boberagent":
        raise RuntimeError(f"unexpected bounded smoke-test response ({len(received)} bytes)")
    print("SUCCESS: received expected harmless response and the peer closed cleanly.")


if __name__ == "__main__":
    main()
