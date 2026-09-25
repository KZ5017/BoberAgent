"""Single-client, on-disk Qdrant projection of curated semantic chunks."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from math import isfinite
from pathlib import Path
from uuid import UUID, uuid4

from qdrant_client import QdrantClient, models

from .semantic import (
    IndexManifest,
    SemanticChunk,
    SemanticFilters,
    SemanticHit,
    SemanticIndexIncompatible,
    SemanticUnavailable,
)

_COLLECTION = "curated_chunks"


class QdrantSemanticIndex:
    """Derived generations under one explicit root; active.json is the commit pointer."""

    def __init__(self, root: Path, *, max_indexed_chunks: int = 20_000) -> None:
        if max_indexed_chunks < 1:
            raise ValueError("max_indexed_chunks must be positive")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._max_indexed_chunks = max_indexed_chunks
        self._manifest: IndexManifest | None = None
        self._client: QdrantClient | None = None
        pointer = self.root / "active.json"
        if pointer.exists():
            try:
                data = json.loads(pointer.read_text(encoding="utf-8"))
                generation = UUID(str(data["generation"])).hex
                manifest = IndexManifest.model_validate(data["manifest"])
                location = self.root / "generations" / generation
                if not location.is_dir():
                    raise ValueError("active generation directory is missing")
                self._client = QdrantClient(path=str(location))
                self._manifest = manifest
            except (OSError, KeyError, TypeError, ValueError) as error:
                raise SemanticUnavailable("semantic index manifest is invalid") from error

    def manifest(self) -> IndexManifest | None:
        return self._manifest

    def replace_generation(
        self, manifest: IndexManifest, points: Sequence[tuple[SemanticChunk, tuple[float, ...]]]
    ) -> None:
        if len(points) != manifest.chunk_count or len(points) > self._max_indexed_chunks:
            raise ValueError("semantic generation has an invalid chunk count")
        if len({chunk.chunk_id for chunk, _ in points}) != len(points):
            raise ValueError("semantic generation contains duplicate chunk IDs")
        if any(
            len(vector) != manifest.dimension or any(not isfinite(value) for value in vector)
            for _, vector in points
        ):
            raise SemanticIndexIncompatible("semantic generation has invalid vector dimensions")
        generation = uuid4().hex
        location = self.root / "generations" / generation
        location.parent.mkdir(parents=True, exist_ok=True)
        staging: QdrantClient | None = None
        try:
            staging = QdrantClient(path=str(location))
            staging.create_collection(
                collection_name=_COLLECTION,
                vectors_config=models.VectorParams(
                    size=manifest.dimension, distance=models.Distance.COSINE
                ),
            )
            for offset in range(0, len(points), 128):
                batch = points[offset : offset + 128]
                staging.upsert(
                    collection_name=_COLLECTION,
                    points=[
                        models.PointStruct(
                            id=chunk.chunk_id,
                            vector=list(vector),
                            payload={
                                "chunk": chunk.model_dump(mode="json"),
                                "status": chunk.status.value,
                                "kind": chunk.kind,
                                "domains": list(chunk.domains),
                                "tags": list(chunk.tags),
                                "technology": chunk.technology,
                                "platform": chunk.platform,
                                "protocol": chunk.protocol,
                                "tool": chunk.tool,
                                "capability_ids": list(chunk.capability_ids),
                                "procedure_ids": [str(ref) for ref in chunk.procedure_ids],
                                "version_applicability": chunk.version_applicability,
                                "goal_type": chunk.goal_type,
                                "environment": chunk.environment,
                                "required_state": list(chunk.required_state),
                                "produced_state": list(chunk.produced_state),
                            },
                        )
                        for chunk, vector in batch
                    ],
                    wait=True,
                )
            staging.close()
            staging = None
            temporary = self.root / f"active.{generation}.json"
            temporary.write_text(
                json.dumps(
                    {"generation": generation, "manifest": manifest.model_dump(mode="json")},
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            temporary.replace(self.root / "active.json")
        except Exception:
            if staging is not None:
                staging.close()
            shutil.rmtree(location, ignore_errors=True)
            raise
        if self._client is not None:
            self._client.close()
        self._client = QdrantClient(path=str(location))
        self._manifest = manifest

    def search(
        self, vector: tuple[float, ...], *, filters: SemanticFilters, limit: int
    ) -> tuple[SemanticHit, ...]:
        if self._manifest is None or self._client is None:
            raise SemanticUnavailable("semantic index has not been built")
        if len(vector) != self._manifest.dimension or any(not isfinite(value) for value in vector):
            raise SemanticIndexIncompatible("query vector is incompatible with active index")
        if limit < 1:
            raise ValueError("semantic search limit must be positive")
        if self._manifest.chunk_count == 0:
            return ()
        conditions = [
            models.FieldCondition(key=key, match=models.MatchValue(value=value))
            for key, value in sorted(filters.payload_values().items())
        ]
        response = self._client.query_points(
            collection_name=_COLLECTION,
            query=list(vector),
            query_filter=models.Filter(must=[*conditions]),
            # Local mode is exact; retrieve all bounded candidates to make ties deterministic.
            limit=self._manifest.chunk_count,
            with_payload=True,
        )
        return tuple(
            SemanticHit(
                chunk=SemanticChunk.model_validate(point.payload["chunk"]),
                score=float(point.score),
            )
            for point in response.points
            if point.payload is not None
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
