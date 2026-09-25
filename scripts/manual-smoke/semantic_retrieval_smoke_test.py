"""Manual real-provider validation of curated Knowledge semantic retrieval.

This script is intentionally outside pytest and never discovers models or other vault notes.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

from boberagent_cli.operator_env import operator_environment
from boberagent_core.knowledge import (
    EmbeddingHTTPConfiguration,
    KnowledgeId,
    KnowledgeRequest,
    KnowledgeRoute,
    KnowledgeRouter,
    KnowledgeStatus,
    OpenAICompatibleEmbeddingProvider,
    SemanticRetrievalService,
    chunk_source,
)
from boberagent_core.knowledge.qdrant_local import QdrantSemanticIndex
from pydantic import SecretStr

_EXCERPT_CHARS = 240


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manually validate M18 semantic retrieval against a running embedding endpoint"
    )
    parser.add_argument("--knowledge-root", type=Path, required=True)
    parser.add_argument("--index-directory", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--api-key-env", default="LM_API_TOKEN")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--domain")
    parser.add_argument("--protocol")
    parser.add_argument("--tool")
    return parser


def _run(arguments: argparse.Namespace) -> None:
    root: Path = arguments.knowledge_root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"--knowledge-root is not an existing directory: {root}")
    if not arguments.index_directory.is_absolute():
        raise ValueError("--index-directory must be an absolute path")
    index_directory: Path = arguments.index_directory.expanduser().resolve()
    if index_directory.is_relative_to(root):
        raise ValueError("--index-directory must be outside the canonical Knowledge root")
    if not arguments.query.strip():
        raise ValueError("--query must not be blank")

    # The M17 loader visits only root/reference and root/procedures. No vault-parent walk.
    catalog = KnowledgeRouter.from_directory(root)
    canonical = catalog.repository.list_documents()
    if not canonical or not any(chunk_source(document) for document in canonical):
        raise RuntimeError("no canonical reference Knowledge with indexable body was found")

    environment = operator_environment(os.environ, project_root=Path(__file__).resolve().parents[2])
    token = environment.get(arguments.api_key_env)
    if token is None or not token.strip():
        raise RuntimeError(
            f"bearer token environment variable is unset or blank: {arguments.api_key_env}"
        )

    configuration = EmbeddingHTTPConfiguration(
        base_url=arguments.base_url,
        model_id=arguments.model,
        api_key=SecretStr(token),
        timeout_seconds=arguments.timeout,
    )
    request = KnowledgeRequest(
        semantic_query=arguments.query,
        semantic_limit=arguments.limit,
        kind="reference",
        domain=arguments.domain,
        protocol=arguments.protocol,
        tool=arguments.tool,
    )
    with OpenAICompatibleEmbeddingProvider(configuration) as provider:
        index = QdrantSemanticIndex(index_directory)
        try:
            router = KnowledgeRouter(
                catalog.repository,
                catalog.procedures,
                source_root=root,
                semantic_service=SemanticRetrievalService(
                    root=root, provider=provider, index=index
                ),
            )
            rebuilt = router.refresh_semantic()
            resolution = router.resolve(request)
            if resolution.route is not KnowledgeRoute.SEMANTIC or not resolution.semantic_hits:
                raise RuntimeError("semantic retrieval returned no canonical reference hits")

            for hit in resolution.semantic_hits:
                chunk = hit.chunk
                if not math.isfinite(hit.score):
                    raise RuntimeError("semantic retrieval returned a non-finite score")
                if chunk.source_type != "reference" or not isinstance(
                    chunk.source_ref, KnowledgeId
                ):
                    raise RuntimeError("semantic retrieval returned a non-reference hit")
                document = router.get_canonical(chunk.source_ref)
                if document is None or document.status is not KnowledgeStatus.CANONICAL:
                    raise RuntimeError(f"hit has no canonical Knowledge source: {chunk.source_ref}")
                if (
                    chunk.version != document.version
                    or chunk.source_sha256 != document.provenance.content_sha256
                    or chunk.provenance != document.provenance
                    or chunk.char_end <= chunk.char_start
                    or chunk.source_text != document.body[chunk.char_start : chunk.char_end]
                    or chunk.source_text == chunk.embedding_text
                ):
                    raise RuntimeError(
                        f"hit provenance or source excerpt is invalid: {chunk.chunk_id}"
                    )
                if (
                    chunk.section_ordinal < 0
                    or chunk.chunk_ordinal < 0
                    or chunk.document_ordinal < 0
                    or not chunk.provenance.source_path
                ):
                    raise RuntimeError(f"hit is missing source-order metadata: {chunk.chunk_id}")

            top_ref = resolution.semantic_hits[0].chunk.source_ref
            if not isinstance(top_ref, KnowledgeId):
                raise RuntimeError("top semantic hit is not reference Knowledge")
            exact = router.resolve(KnowledgeRequest(knowledge_id=top_ref))
            if exact.route is not KnowledgeRoute.KNOWLEDGE_ID or not exact.documents:
                raise RuntimeError(f"deterministic exact Knowledge lookup failed: {top_ref}")

            print(f"Semantic generation: {'rebuilt' if rebuilt else 'reused'}")
            print(f"Canonical reference documents: {len(canonical)}")
            print(f"Ranked hits: {len(resolution.semantic_hits)}")
            for rank, hit in enumerate(resolution.semantic_hits, 1):
                chunk = hit.chunk
                excerpt = chunk.source_text[:_EXCERPT_CHARS]
                section = " > ".join(chunk.heading_path) or "(introduction)"
                print(f"{rank}. score={hit.score:.6f}  {chunk.source_ref}@{chunk.version}")
                print(f"   title: {chunk.title}")
                print(f"   section: {section}")
                print(
                    "   order: "
                    f"section={chunk.section_ordinal} "
                    f"chunk={chunk.chunk_ordinal} document={chunk.document_ordinal}"
                )
                print(f"   source: {chunk.provenance.source_path}")
                print(f"   source excerpt: {json.dumps(excerpt, ensure_ascii=False)}")
                if len(chunk.source_text) > _EXCERPT_CHARS:
                    print("   source excerpt truncated at 240 characters")
            print(f"Exact lookup of top Knowledge ID: OK ({top_ref})")
        finally:
            index.close()


def main() -> None:
    parser = _parser()
    try:
        _run(parser.parse_args())
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"semantic smoke failed: {error}\n")


if __name__ == "__main__":
    main()
