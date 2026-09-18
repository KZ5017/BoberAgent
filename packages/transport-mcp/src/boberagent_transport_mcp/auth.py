"""Pre-shared bearer verification using the official MCP authorization hook."""

from __future__ import annotations

import secrets

from mcp.server.auth.provider import AccessToken


class StaticBearerTokenVerifier:
    """Verify one externally provisioned token without exposing it in diagnostics."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("bearer token must not be empty")
        self._token = token

    async def verify_token(self, token: str) -> AccessToken | None:
        if not secrets.compare_digest(token, self._token):
            return None
        return AccessToken(
            token="[REDACTED]",
            client_id="boberagent-core",
            scopes=["boberagent.transport"],
        )
