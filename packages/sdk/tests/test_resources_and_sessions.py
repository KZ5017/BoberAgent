"""Resource and Session registration, lookup, and lease behavior."""

import asyncio

import pytest
from boberagent_contracts import (
    AccessMode,
    ResourceRef,
    SessionDescriptor,
    SessionRef,
)
from boberagent_sdk import (
    BrowserInspection,
    BrowserPageState,
    CommandResult,
    ResourceUnavailable,
    SessionUnavailable,
    parse_browser_url,
)
from boberagent_sdk.testing import FakeExecutionContext


class FakeCommandDriver:
    @property
    def supported_operations(self) -> tuple[str, ...]:
        return ("command_execute",)

    async def execute(self, command: str, *, timeout: float | None = None) -> CommandResult:
        del timeout
        return CommandResult(exit_code=0, stdout=command.encode())


class FakeBrowserDriver:
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
        del allowed_hosts, timeout
        return BrowserPageState(final_url=url, title="Fixture", status_code=200)

    async def inspect(self, *, max_html_bytes: int) -> BrowserInspection:
        del max_html_bytes
        return BrowserInspection(
            page=BrowserPageState(final_url="https://example.test/", title="Fixture"),
            html=b"<html></html>",
        )


async def exercise_resource_leases(context: FakeExecutionContext) -> None:
    descriptor = await context.resources.create(
        resource_type="test.environment",
        configuration={"runtime": "fixture"},
    )
    assert await context.resources.get(descriptor.resource_id) == descriptor

    shared = context.resources.acquire(descriptor.resource_id, mode=AccessMode.SHARED)
    async with shared as acquired:
        assert acquired.resource_id == descriptor.resource_id
        conflicting = context.resources.acquire(descriptor.resource_id, mode=AccessMode.EXCLUSIVE)
        with pytest.raises(ResourceUnavailable, match="Conflicting"):
            await conflicting.__aenter__()

    async with context.resources.acquire(
        descriptor.resource_id, mode=AccessMode.EXCLUSIVE
    ) as acquired:
        assert acquired.resource_id == descriptor.resource_id
    await context.resources.close(descriptor.resource_id)
    assert (await context.resources.get(descriptor.resource_id)).state == "closed"


def test_resource_lookup_and_access_modes() -> None:
    context = FakeExecutionContext()
    try:
        asyncio.run(exercise_resource_leases(context))
    finally:
        context.close()


async def exercise_session_leases(context: FakeExecutionContext) -> None:
    descriptor = SessionDescriptor(
        session_id=SessionRef("session-test"),
        session_type="command",
        state="active",
        provider="fake",
        owner_ref=context.invocation.run_id,
        created_by_run=context.invocation.run_id,
        created_at=context.clock.now(),
        supported_operations=("command_execute",),
        access_modes=(AccessMode.SHARED, AccessMode.EXCLUSIVE),
    )
    driver = FakeCommandDriver()
    context.sessions.register(descriptor, driver)
    handle = await context.sessions.get(descriptor.session_id)
    assert handle.descriptor == descriptor

    shared = context.sessions.acquire(descriptor.session_id, mode=AccessMode.SHARED)
    async with shared as acquired:
        assert acquired.driver.supported_operations == ("command_execute",)
        conflicting = context.sessions.acquire(descriptor.session_id, mode=AccessMode.EXCLUSIVE)
        with pytest.raises(SessionUnavailable, match="Conflicting"):
            await conflicting.__aenter__()

    async with context.sessions.acquire(descriptor.session_id) as acquired:
        assert acquired.descriptor.session_id == descriptor.session_id


def test_session_lookup_and_access_modes() -> None:
    context = FakeExecutionContext()
    try:
        asyncio.run(exercise_session_leases(context))
    finally:
        context.close()


async def exercise_session_create_and_close(context: FakeExecutionContext) -> None:
    context.sessions.register_factory("browser", lambda _configuration: FakeBrowserDriver())
    handle = await context.sessions.create(
        session_type="browser",
        resource_refs=(ResourceRef("resource-browser-test"),),
        configuration={},
        owner_ref=context.mission.mission_ref,
    )
    assert handle.descriptor.state == "ACTIVE"
    await context.sessions.close(handle.descriptor.session_id)
    assert (await context.sessions.get(handle.descriptor.session_id)).descriptor.state == "CLOSED"
    with pytest.raises(SessionUnavailable, match="not active"):
        await context.sessions.acquire(handle.descriptor.session_id).__aenter__()


def test_session_create_close_and_browser_url_normalization() -> None:
    context = FakeExecutionContext()
    try:
        asyncio.run(exercise_session_create_and_close(context))
    finally:
        context.close()

    assert parse_browser_url("https://Example.TEST.:8443/path").host == "example.test"
    assert parse_browser_url("http://192.0.2.10:8080/").port == 8080
    assert parse_browser_url("http://[2001:db8::1]/").host == "2001:db8::1"
    with pytest.raises(ValueError, match="only http and https"):
        parse_browser_url("file:///etc/passwd")
    with pytest.raises(ValueError, match="user information"):
        parse_browser_url("https://user:password@example.test/")
