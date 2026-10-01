"""E1 SDK preparation port is typed and fake-only, without runtime side effects."""

import asyncio

import pytest
from boberagent_contracts import RuntimePreparationInput
from boberagent_sdk import InputError, RuntimePreparationService
from boberagent_sdk.testing import FakeRuntimePreparationService
from preparation_test_fixtures import permit_fixture, receipt_fixture


async def _exercise_fake() -> None:
    fake: RuntimePreparationService = FakeRuntimePreparationService()
    assert isinstance(fake, FakeRuntimePreparationService)
    request = RuntimePreparationInput(
        schema_version="runtime-preparation-input-v1", permit=permit_fixture()
    )
    expected = receipt_fixture()
    fake.expect(request, expected)
    result = await fake.prepare_runtime(request)
    assert result == expected
    assert fake.calls == [request]
    fake.assert_expectations_met()
    with pytest.raises(InputError, match="unexpected typed"):
        await fake.prepare_runtime(request)


def test_fake_typed_preparation_contract() -> None:
    asyncio.run(_exercise_fake())


def test_fake_has_no_generic_command_or_execution_surface() -> None:
    fake = FakeRuntimePreparationService()
    assert not hasattr(fake, "run_tool")
    assert not hasattr(fake, "execute_plan")
    assert not hasattr(fake, "workspace")
    assert not hasattr(fake, "artifacts")


def test_fake_rejects_receipt_for_other_run() -> None:
    request = RuntimePreparationInput(
        schema_version="runtime-preparation-input-v1", permit=permit_fixture()
    )
    receipt = receipt_fixture().model_copy(update={"run_ref": "run-other"})
    with pytest.raises(ValueError, match="must match"):
        FakeRuntimePreparationService().expect(request, receipt)
