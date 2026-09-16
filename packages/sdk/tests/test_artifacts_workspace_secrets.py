"""Artifact, Workspace, Secret, clock, and cancellation fake behavior."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from boberagent_contracts import SecretRef
from boberagent_sdk import ExecutionCancelled, SensitiveValue
from boberagent_sdk.testing import FakeClock, FakeExecutionContext


def test_fake_artifact_creation_and_retrieval() -> None:
    context = FakeExecutionContext()
    try:
        artifact = asyncio.run(
            context.artifacts.create_text(
                artifact_type="test.output",
                text="evidence",
                metadata={"format": "plain"},
            )
        )
        assert asyncio.run(context.artifacts.get(artifact.artifact_id)) == artifact
        assert asyncio.run(context.artifacts.read_bytes(artifact.artifact_id)) == b"evidence"
        assert str(artifact.storage_ref) != str(artifact.artifact_id)
        assert artifact.sha256 is not None
    finally:
        context.close()


def test_workspace_path_is_temporary_and_cleaned_up() -> None:
    context = FakeExecutionContext()
    workspace = asyncio.run(context.workspace.create(purpose="unit-test"))
    marker = workspace.path / "marker.txt"
    marker.write_text("temporary", encoding="utf-8")
    assert marker.exists()
    context.close()
    assert not workspace.path.exists()


def test_sensitive_value_is_redacted_and_secret_round_trips() -> None:
    context = FakeExecutionContext()
    secret_ref = SecretRef("secret-existing")
    plaintext = "correct horse battery staple"
    context.secrets.register(secret_ref, plaintext)
    try:
        resolved = asyncio.run(
            context.secrets.resolve(secret_ref, purpose="unit-test authentication")
        )
        assert resolved.reveal_text() == plaintext
        assert plaintext not in repr(resolved)
        assert plaintext not in str(resolved)
        assert plaintext not in f"{resolved}"

        stored_ref = asyncio.run(
            context.secrets.store(
                value=SensitiveValue.from_text("new secret"),
                secret_type="password",
            )
        )
        stored = asyncio.run(context.secrets.resolve(stored_ref, purpose="verify test store"))
        assert stored.reveal_text() == "new secret"
    finally:
        context.close()


def test_fake_clock_and_cancellation_are_deterministic() -> None:
    initial = datetime(2026, 2, 3, tzinfo=UTC)
    clock = FakeClock(initial)
    context = FakeExecutionContext(clock=clock)
    try:
        assert context.clock.now() == initial
        context.clock.set(initial + timedelta(minutes=5))
        assert context.clock.now() == initial + timedelta(minutes=5)
        asyncio.run(context.cancellation.checkpoint())
        context.cancellation.request()
        assert context.cancellation.requested
        with pytest.raises(ExecutionCancelled):
            asyncio.run(context.cancellation.checkpoint())
    finally:
        context.close()
