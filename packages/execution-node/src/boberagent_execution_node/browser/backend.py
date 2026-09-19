"""Playwright-backed browser runtime hidden behind semantic SDK drivers."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from boberagent_sdk import (
    BrowserInspection,
    BrowserPageState,
    BrowserSession,
    ExecutionTimeout,
    InputError,
    ScopeViolation,
    normalize_browser_host,
    parse_browser_url,
)
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Request,
    Route,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)


class ManagedBrowserSession(BrowserSession, Protocol):
    async def close(self) -> None: ...


class ManagedBrowserRuntime(Protocol):
    async def create_session(self) -> ManagedBrowserSession: ...

    async def close(self) -> None: ...


class BrowserBackend(Protocol):
    async def launch(
        self,
        *,
        executable_path: Path,
        headless: bool,
    ) -> ManagedBrowserRuntime: ...


class PlaywrightBrowserBackend:
    """Launch explicitly provisioned Chromium; never download a browser implicitly."""

    async def launch(
        self,
        *,
        executable_path: Path,
        headless: bool,
    ) -> ManagedBrowserRuntime:
        playwright = await async_playwright().start()
        try:
            browser = await playwright.chromium.launch(
                executable_path=str(executable_path),
                headless=headless,
            )
        except BaseException:
            await playwright.stop()
            raise
        return PlaywrightBrowserRuntime(playwright, browser)


class PlaywrightBrowserRuntime:
    def __init__(self, playwright: Playwright, browser: Browser) -> None:
        self._playwright = playwright
        self._browser = browser
        self._sessions: set[PlaywrightBrowserSession] = set()
        self._closed = False

    async def create_session(self) -> ManagedBrowserSession:
        if self._closed:
            raise RuntimeError("browser Resource is closed")
        context = await self._browser.new_context()
        page = await context.new_page()
        session = PlaywrightBrowserSession(context, page, self._sessions.discard)
        self._sessions.add(session)
        return session

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for session in tuple(self._sessions):
            await session.close()
        try:
            await self._browser.close()
        finally:
            await self._playwright.stop()


class PlaywrightBrowserSession:
    def __init__(
        self,
        context: BrowserContext,
        page: Page,
        unregister: object,
    ) -> None:
        self._context = context
        self._page = page
        self._unregister = unregister
        self._allowed_hosts: frozenset[str] = frozenset()
        self._blocked_navigation_host: str | None = None
        self._last_status: int | None = None
        self._closed = False
        self._route_installed = False

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
        self._require_open()
        target = parse_browser_url(url)
        normalized_hosts = frozenset(normalize_browser_host(host) for host in allowed_hosts)
        if target.host not in normalized_hosts:
            raise ScopeViolation("browser target host is outside the authorized navigation policy")
        self._allowed_hosts = normalized_hosts
        self._blocked_navigation_host = None
        if not self._route_installed:
            await self._context.route("**/*", self._authorize_route)
            self._route_installed = True
        try:
            response = await self._page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=None if timeout is None else timeout * 1000,
            )
        except PlaywrightTimeoutError as error:
            raise ExecutionTimeout("browser navigation timed out") from error
        except PlaywrightError as error:
            if self._blocked_navigation_host is not None:
                raise ScopeViolation("browser redirect left the authorized host scope") from error
            raise
        final_target = parse_browser_url(self._page.url)
        if final_target.host not in self._allowed_hosts:
            raise ScopeViolation("browser navigation ended outside the authorized host scope")
        self._last_status = None if response is None else response.status
        return await self._page_state()

    async def inspect(self, *, max_html_bytes: int) -> BrowserInspection:
        self._require_open()
        if max_html_bytes <= 0:
            raise InputError("HTML snapshot bound must be positive")
        html = (await self._page.content()).encode("utf-8")
        if len(html) > max_html_bytes:
            raise InputError("HTML snapshot exceeds the configured evidence bound")
        return BrowserInspection(page=await self._page_state(), html=html)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._context.close()
        finally:
            discard = self._unregister
            if callable(discard):
                discard(self)

    async def _authorize_route(self, route: Route, request: Request) -> None:
        try:
            target = parse_browser_url(request.url)
        except ValueError:
            if request.is_navigation_request():
                self._blocked_navigation_host = "unsupported"
            await route.abort("blockedbyclient")
            return
        if target.host not in self._allowed_hosts:
            if request.is_navigation_request():
                self._blocked_navigation_host = target.host
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    async def _page_state(self) -> BrowserPageState:
        return BrowserPageState(
            final_url=self._page.url,
            title=await self._page.title(),
            status_code=self._last_status,
        )

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("browser Session is closed")
