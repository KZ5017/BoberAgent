"""The generic Resource fake cannot pretend it constructed an E5 runtime."""

import asyncio

import pytest
from boberagent_sdk import ResourceUnavailable
from boberagent_sdk.testing import FakeExecutionContext


def test_generic_fake_cannot_create_python_runtime() -> None:
    async def scenario() -> None:
        async with FakeExecutionContext() as ctx:
            with pytest.raises(ResourceUnavailable, match="typed preparation"):
                await ctx.resources.create(resource_type="python_runtime", configuration={})

    asyncio.run(scenario())
