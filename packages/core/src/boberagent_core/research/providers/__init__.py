"""Core-owned live research adapters; never an acquisition or execution API."""

from .github import (
    GITHUB_SEARCH_ENDPOINT,
    QUERY_MAPPING_VERSION,
    GitHubResearchConfig,
    GitHubResearchProvider,
    github_repository_query,
)

__all__ = [
    "GITHUB_SEARCH_ENDPOINT",
    "QUERY_MAPPING_VERSION",
    "GitHubResearchConfig",
    "GitHubResearchProvider",
    "github_repository_query",
]
