"""SDK-only production browser capability tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from boberagent_capability_browser_interaction import (
    BrowserInteractionCapability,
    CloseBrowserInput,
    InspectBrowserInput,
    NavigateBrowserInput,
    OpenBrowserInput,
)
from boberagent_contracts import (
    AssetRef,
    CapabilityOutcomeCategory,
    CapabilityRunStatus,
    ResourceRef,
)
from boberagent_execution_node.capabilities import CapabilityManifest
from boberagent_sdk import (
    AssetSnapshot,
    BrowserInspection,
    BrowserPageState,
    InputError,
    ResourceUnavailable,
    ScopeViolation,
    SessionUnavailable,
)
from boberagent_sdk.testing import FakeExecutionContext

ASSET_REF = AssetRef("asset-browser-test")
HOST = "browser.test"


class StatefulFakeBrowserDriver:
    def __init__(self) -> None:
        self._page = BrowserPageState(final_url="about:blank", title="", status_code=None)

    @property
    def supported_operations(self) -> tuple[str, ...]:
        return ("navigate", "inspect")

    async def navigate(
        self,
        url: str,
        *,
        allowed_hosts: tuple[str, ...],
        timeout: float | None = None,
    ) -> BrowserPageState:
        del timeout
        if HOST not in allowed_hosts:
            raise ScopeViolation("host denied by fake browser driver")
        if url.endswith("/redirect-outside"):
            raise ScopeViolation("redirect left scope")
        self._page = BrowserPageState(final_url=url, title="Stateful fixture", status_code=200)
        return self._page

    async def inspect(self, *, max_html_bytes: int) -> BrowserInspection:
        html = b"<html><title>Stateful fixture</title></html>"
        assert len(html) <= max_html_bytes
        return BrowserInspection(page=self._page, html=html)


def _context() -> FakeExecutionContext:
    context = FakeExecutionContext()
    context.entities.add(AssetSnapshot(ref=ASSET_REF, primary_address=HOST))
    context.scope.allow_asset(ASSET_REF)
    context.scope.allow_address(HOST)
    context.sessions.register_factory("browser", lambda _configuration: StatefulFakeBrowserDriver())
    return context


def test_manifest_is_static_valid_and_tool_independent() -> None:
    manifest_path = Path(__file__).parents[1] / "capability.json"
    manifest = CapabilityManifest.model_validate(json.loads(manifest_path.read_text()))

    assert manifest.definition.capability_id == "browser.interaction"
    assert {operation.name for operation in manifest.definition.operations} == {
        "open",
        "navigate",
        "inspect",
        "close",
    }
    assert manifest.definition.dependencies[0].identifier == "chromium"
    assert "playwright" not in str(manifest.definition.capability_id)


def test_open_navigate_inspect_close_and_artifact_flow() -> None:
    async def scenario() -> None:
        context = _context()
        capability = BrowserInteractionCapability()
        async with context:
            opened = await capability.execute(
                "open", context, OpenBrowserInput(asset_ref=ASSET_REF)
            )
            assert opened.execution_status is CapabilityRunStatus.COMPLETED
            assert opened.outcome.category is CapabilityOutcomeCategory.SUCCESS
            assert len(opened.resources) == len(opened.sessions) == 1
            session_ref = opened.sessions[0].session_id

            navigated = await capability.execute(
                "navigate",
                context,
                NavigateBrowserInput(
                    asset_ref=ASSET_REF,
                    session_ref=session_ref,
                    url=f"http://{HOST}/state",
                ),
            )
            assert navigated.outcome.details["title"] == "Stateful fixture"
            assert navigated.sessions == ()

            inspected = await capability.execute(
                "inspect",
                context,
                InspectBrowserInput(asset_ref=ASSET_REF, session_ref=session_ref),
            )
            assert len(inspected.artifacts) == 1
            assert (
                await context.artifacts.read_bytes(inspected.artifacts[0].artifact_id)
                == b"<html><title>Stateful fixture</title></html>"
            )

            closed = await capability.execute(
                "close",
                context,
                CloseBrowserInput(asset_ref=ASSET_REF, session_ref=session_ref),
            )
            assert closed.outcome.code == "BROWSER_SESSION_CLOSED"
            closed_again = await capability.execute(
                "close",
                context,
                CloseBrowserInput(asset_ref=ASSET_REF, session_ref=session_ref),
            )
            assert closed_again.outcome.code == "BROWSER_SESSION_ALREADY_CLOSED"
            with pytest.raises(SessionUnavailable, match="not active"):
                await capability.execute(
                    "navigate",
                    context,
                    NavigateBrowserInput(
                        asset_ref=ASSET_REF,
                        session_ref=session_ref,
                        url=f"http://{HOST}/after-close",
                    ),
                )

    asyncio.run(scenario())


def test_scope_and_redirect_denial_precede_or_stop_navigation() -> None:
    async def scenario() -> None:
        denied = FakeExecutionContext()
        denied.entities.add(AssetSnapshot(ref=ASSET_REF, primary_address=HOST))
        with pytest.raises(ScopeViolation):
            await BrowserInteractionCapability().execute(
                "open", denied, OpenBrowserInput(asset_ref=ASSET_REF)
            )
        with pytest.raises(ResourceUnavailable, match="Unknown Resource"):
            await denied.resources.get(ResourceRef("resource-0001"))
        denied.close()

        context = _context()
        async with context:
            capability = BrowserInteractionCapability()
            opened = await capability.execute(
                "open", context, OpenBrowserInput(asset_ref=ASSET_REF)
            )
            session_ref = opened.sessions[0].session_id
            with pytest.raises(ScopeViolation):
                await capability.execute(
                    "navigate",
                    context,
                    NavigateBrowserInput(
                        asset_ref=ASSET_REF,
                        session_ref=session_ref,
                        url="https://outside.test/",
                    ),
                )
            with pytest.raises(InputError, match="valid HTTP"):
                await capability.execute(
                    "navigate",
                    context,
                    NavigateBrowserInput(
                        asset_ref=ASSET_REF,
                        session_ref=session_ref,
                        url="file:///etc/passwd",
                    ),
                )
            with pytest.raises(ScopeViolation, match="redirect"):
                await capability.execute(
                    "navigate",
                    context,
                    NavigateBrowserInput(
                        asset_ref=ASSET_REF,
                        session_ref=session_ref,
                        url=f"http://{HOST}/redirect-outside",
                    ),
                )

    asyncio.run(scenario())
