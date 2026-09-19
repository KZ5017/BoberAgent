"""Production ``browser.interaction`` capability orchestration."""

from __future__ import annotations

from boberagent_contracts import (
    AssetRef,
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRunStatus,
    JsonObject,
    ResourceDescriptor,
    SessionDescriptor,
    SessionRef,
)
from boberagent_sdk import (
    BrowserSession,
    Capability,
    ExecutionContext,
    InputError,
    SessionHandle,
    SessionUnavailable,
    parse_browser_url,
)
from pydantic import BaseModel

from .inputs import (
    BrowserInput,
    CloseBrowserInput,
    InspectBrowserInput,
    NavigateBrowserInput,
    OpenBrowserInput,
)


class BrowserInteractionCapability(Capability):
    capability_id = "browser.interaction"

    async def execute(
        self,
        operation: str,
        ctx: ExecutionContext,
        inputs: BaseModel,
    ) -> CapabilityResult:
        if not isinstance(inputs, BrowserInput):
            raise InputError("browser.interaction requires a validated browser input model")
        await ctx.cancellation.checkpoint()
        await ctx.entities.asset(inputs.asset_ref)
        await ctx.scope.assert_asset_allowed(inputs.asset_ref)
        if operation == "open" and isinstance(inputs, OpenBrowserInput):
            return await self._open(ctx, inputs)
        if operation == "navigate" and isinstance(inputs, NavigateBrowserInput):
            return await self._navigate(ctx, inputs)
        if operation == "inspect" and isinstance(inputs, InspectBrowserInput):
            return await self._inspect(ctx, inputs)
        if operation == "close" and isinstance(inputs, CloseBrowserInput):
            return await self._close(ctx, inputs)
        raise InputError(f"unsupported browser.interaction operation: {operation}")

    async def _open(self, ctx: ExecutionContext, inputs: OpenBrowserInput) -> CapabilityResult:
        resource = await ctx.resources.create(
            resource_type="browser_process",
            configuration={"headless": True},
            owner_ref=ctx.mission.mission_ref,
        )
        try:
            handle = await ctx.sessions.create(
                session_type="browser",
                resource_refs=(resource.resource_id,),
                configuration={},
                owner_ref=ctx.mission.mission_ref,
                target_ref=inputs.asset_ref,
            )
        except BaseException:
            await ctx.resources.close(resource.resource_id)
            raise
        return CapabilityResult(
            run_ref=ctx.invocation.run_id,
            execution_status=CapabilityRunStatus.COMPLETED,
            outcome=CapabilityOutcome(
                category=CapabilityOutcomeCategory.SUCCESS,
                code="BROWSER_SESSION_OPENED",
                summary="A managed browser Resource and stateful Session were opened.",
                details=_references(resource, handle.descriptor),
            ),
            resources=(resource,),
            sessions=(handle.descriptor,),
        )

    async def _navigate(
        self, ctx: ExecutionContext, inputs: NavigateBrowserInput
    ) -> CapabilityResult:
        try:
            target = parse_browser_url(inputs.url)
        except ValueError as error:
            raise InputError("browser navigation requires a valid HTTP(S) URL") from error
        await ctx.scope.assert_address_allowed(target.host)
        await self._validate_session(ctx, inputs.session_ref, inputs.asset_ref)
        async with ctx.sessions.acquire(inputs.session_ref) as leased:
            driver = _browser_driver(leased)
            page = await driver.navigate(
                inputs.url,
                allowed_hosts=(target.host,),
                timeout=inputs.timeout_seconds,
            )
        return CapabilityResult(
            run_ref=ctx.invocation.run_id,
            execution_status=CapabilityRunStatus.COMPLETED,
            outcome=CapabilityOutcome(
                category=CapabilityOutcomeCategory.SUCCESS,
                code="BROWSER_NAVIGATED",
                summary="The existing browser Session completed scoped navigation.",
                details={
                    "session_ref": str(inputs.session_ref),
                    "final_url": page.final_url,
                    "title": page.title,
                    "status_code": page.status_code,
                },
            ),
        )

    async def _inspect(
        self, ctx: ExecutionContext, inputs: InspectBrowserInput
    ) -> CapabilityResult:
        await self._validate_session(ctx, inputs.session_ref, inputs.asset_ref)
        async with ctx.sessions.acquire(inputs.session_ref) as leased:
            inspection = await _browser_driver(leased).inspect(max_html_bytes=inputs.max_html_bytes)
        artifact = await ctx.artifacts.create_from_bytes(
            artifact_type="browser.page_html",
            data=inspection.html,
            media_type="text/html; charset=utf-8",
            metadata={
                "session_ref": str(inputs.session_ref),
                "final_url": inspection.page.final_url,
            },
        )
        return CapabilityResult(
            run_ref=ctx.invocation.run_id,
            execution_status=CapabilityRunStatus.COMPLETED,
            outcome=CapabilityOutcome(
                category=CapabilityOutcomeCategory.SUCCESS,
                code="BROWSER_PAGE_INSPECTED",
                summary="Current browser page metadata and bounded HTML evidence were captured.",
                details={
                    "session_ref": str(inputs.session_ref),
                    "final_url": inspection.page.final_url,
                    "title": inspection.page.title,
                    "status_code": inspection.page.status_code,
                    "artifact_ref": str(artifact.artifact_id),
                },
            ),
            artifacts=(artifact,),
        )

    async def _close(self, ctx: ExecutionContext, inputs: CloseBrowserInput) -> CapabilityResult:
        handle = await self._validate_session(ctx, inputs.session_ref, inputs.asset_ref)
        resource_refs = handle.descriptor.resource_refs
        was_closed = handle.descriptor.state.upper() in {"CLOSED", "LOST"}
        await ctx.sessions.close(inputs.session_ref)
        for resource_ref in resource_refs:
            await ctx.resources.close(resource_ref)
        return CapabilityResult(
            run_ref=ctx.invocation.run_id,
            execution_status=CapabilityRunStatus.COMPLETED,
            outcome=CapabilityOutcome(
                category=CapabilityOutcomeCategory.SUCCESS,
                code=("BROWSER_SESSION_ALREADY_CLOSED" if was_closed else "BROWSER_SESSION_CLOSED"),
                summary="The browser Session and its dedicated Resource are closed.",
                details={
                    "session_ref": str(inputs.session_ref),
                    "resource_refs": [str(ref) for ref in resource_refs],
                },
            ),
        )

    async def _validate_session(
        self,
        ctx: ExecutionContext,
        session_ref: SessionRef,
        asset_ref: AssetRef,
    ) -> SessionHandle:
        handle = await ctx.sessions.get(session_ref)
        descriptor = handle.descriptor
        if descriptor.session_type != "browser":
            raise SessionUnavailable("requested Session is not a browser Session")
        if str(descriptor.owner_ref) != str(ctx.mission.mission_ref):
            raise SessionUnavailable("browser Session does not belong to this Mission")
        if descriptor.target_ref is None or str(descriptor.target_ref) != str(asset_ref):
            raise SessionUnavailable("browser Session does not belong to the requested Asset")
        if len(descriptor.resource_refs) != 1:
            raise SessionUnavailable("browser Session has invalid Resource ownership metadata")
        return handle


def _browser_driver(handle: SessionHandle) -> BrowserSession:
    if not isinstance(handle.driver, BrowserSession):
        raise SessionUnavailable("Session does not provide browser navigation semantics")
    return handle.driver


def _references(
    resource: ResourceDescriptor,
    session: SessionDescriptor,
) -> JsonObject:
    return {
        "resource_ref": str(resource.resource_id),
        "session_ref": str(session.session_id),
    }
