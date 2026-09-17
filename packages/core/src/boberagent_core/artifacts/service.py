"""Intentional Core API for Artifact metadata and verified content access."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import BinaryIO

from boberagent_contracts import ArtifactRef

from boberagent_core.models import ArtifactContentState, StoredArtifact
from boberagent_core.persistence import CoreDatabase

from .storage import FilesystemArtifactStorage


class CoreArtifactService:
    def __init__(self, database: CoreDatabase, storage: FilesystemArtifactStorage) -> None:
        self._database = database
        self._storage = storage

    def get(self, artifact_ref: ArtifactRef) -> StoredArtifact | None:
        with self._database.unit_of_work() as work:
            return work.artifacts.get_record(artifact_ref)

    def content_available(self, artifact_ref: ArtifactRef) -> bool:
        record = self.get(artifact_ref)
        if record is None or record.content_state is not ArtifactContentState.AVAILABLE:
            return False
        with self._database.unit_of_work() as work:
            content_key = work.artifacts.content_key(artifact_ref)
        return content_key is not None and self._storage.content_exists(content_key)

    @contextmanager
    def open_content(self, artifact_ref: ArtifactRef) -> Iterator[BinaryIO]:
        with self._database.unit_of_work() as work:
            record = work.artifacts.get_record(artifact_ref)
            content_key = work.artifacts.content_key(artifact_ref)
        if (
            record is None
            or record.content_state is not ArtifactContentState.AVAILABLE
            or content_key is None
        ):
            raise FileNotFoundError(f"Artifact content is unavailable: {artifact_ref}")
        with self._storage.open_content(content_key) as stream:
            yield stream

    def read_bytes(self, artifact_ref: ArtifactRef) -> bytes:
        with self.open_content(artifact_ref) as stream:
            return stream.read()
