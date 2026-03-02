# ABOUTME: Tests for Protocol-based plugin interfaces.
# ABOUTME: Verifies runtime_checkable behavior, isinstance checks, and method signature correctness.
from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

import pytest

from forkhub.interfaces import EmbeddingProvider, GitProvider, NotificationBackend

if TYPE_CHECKING:
    from datetime import datetime


# ---------------------------------------------------------------------------
# Minimal stub implementations that satisfy each Protocol
# ---------------------------------------------------------------------------


class StubGitProvider:
    """Minimal class implementing all GitProvider methods."""

    async def get_user_repos(self, username: str) -> list:
        return []

    async def get_forks(self, owner: str, repo: str, *, page: int = 1) -> object:
        return object()

    async def compare(self, owner: str, repo: str, base: str, head: str) -> object:
        return object()

    async def get_releases(self, owner: str, repo: str, *, since: datetime | None = None) -> list:
        return []

    async def get_repo(self, owner: str, repo: str) -> object:
        return object()

    async def get_commit_messages(self, owner: str, repo: str, *, since: str | None = None) -> list:
        return []

    async def get_file_diff(self, owner: str, repo: str, base: str, head: str, path: str) -> str:
        return ""

    async def get_rate_limit(self) -> object:
        return object()


class StubNotificationBackend:
    """Minimal class implementing all NotificationBackend methods."""

    async def deliver(self, digest: object) -> object:
        return object()

    def backend_name(self) -> str:
        return "stub"


class StubEmbeddingProvider:
    """Minimal class implementing all EmbeddingProvider methods."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 384 for _ in texts]

    def dimensions(self) -> int:
        return 384


# ---------------------------------------------------------------------------
# Incomplete stubs that are missing required methods
# ---------------------------------------------------------------------------


class IncompleteGitProvider:
    """Missing most GitProvider methods -- only has get_repo."""

    async def get_repo(self, owner: str, repo: str) -> object:
        return object()


class IncompleteNotificationBackend:
    """Missing deliver method."""

    def backend_name(self) -> str:
        return "broken"


class IncompleteEmbeddingProvider:
    """Missing dimensions method."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return []


# ===========================================================================
# Test: Protocols are runtime_checkable
# ===========================================================================


class TestRuntimeCheckable:
    """Each protocol must be decorated with @runtime_checkable."""

    def test_git_provider_is_runtime_checkable(self) -> None:
        assert hasattr(GitProvider, "__protocol_attrs__") or hasattr(
            GitProvider, "_is_runtime_protocol"
        )
        # The real test: isinstance doesn't raise TypeError
        assert isinstance(StubGitProvider(), GitProvider)

    def test_notification_backend_is_runtime_checkable(self) -> None:
        assert isinstance(StubNotificationBackend(), NotificationBackend)

    def test_embedding_provider_is_runtime_checkable(self) -> None:
        assert isinstance(StubEmbeddingProvider(), EmbeddingProvider)


# ===========================================================================
# Test: Complete implementations pass isinstance checks
# ===========================================================================


class TestCompleteImplementations:
    """A class implementing all required methods should pass isinstance."""

    def test_stub_git_provider_is_instance(self) -> None:
        provider = StubGitProvider()
        assert isinstance(provider, GitProvider)

    def test_stub_notification_backend_is_instance(self) -> None:
        backend = StubNotificationBackend()
        assert isinstance(backend, NotificationBackend)

    def test_stub_embedding_provider_is_instance(self) -> None:
        provider = StubEmbeddingProvider()
        assert isinstance(provider, EmbeddingProvider)


# ===========================================================================
# Test: Incomplete implementations fail isinstance checks
# ===========================================================================


class TestIncompleteImplementations:
    """A class missing required methods should fail isinstance."""

    def test_incomplete_git_provider_fails(self) -> None:
        provider = IncompleteGitProvider()
        assert not isinstance(provider, GitProvider)

    def test_incomplete_notification_backend_fails(self) -> None:
        backend = IncompleteNotificationBackend()
        assert not isinstance(backend, NotificationBackend)

    def test_incomplete_embedding_provider_fails(self) -> None:
        provider = IncompleteEmbeddingProvider()
        assert not isinstance(provider, EmbeddingProvider)

    def test_plain_object_fails_all_protocols(self) -> None:
        obj = object()
        assert not isinstance(obj, GitProvider)
        assert not isinstance(obj, NotificationBackend)
        assert not isinstance(obj, EmbeddingProvider)


# ===========================================================================
# Test: Method signatures are correct
# ===========================================================================


class TestGitProviderSignatures:
    """Verify GitProvider methods have the expected parameter names and kinds."""

    @pytest.fixture()
    def protocol_methods(self) -> dict[str, inspect.Signature]:
        methods = {}
        for name in [
            "get_user_repos",
            "get_forks",
            "compare",
            "get_releases",
            "get_repo",
            "get_commit_messages",
            "get_file_diff",
            "get_rate_limit",
        ]:
            method = getattr(GitProvider, name, None)
            assert method is not None, f"GitProvider is missing method {name}"
            methods[name] = inspect.signature(method)
        return methods

    def test_get_user_repos_params(self, protocol_methods: dict) -> None:
        sig = protocol_methods["get_user_repos"]
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "username" in params

    def test_get_forks_params(self, protocol_methods: dict) -> None:
        sig = protocol_methods["get_forks"]
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "owner" in params
        assert "repo" in params
        assert "page" in params
        # page should be keyword-only with default=1
        page_param = sig.parameters["page"]
        assert page_param.kind == inspect.Parameter.KEYWORD_ONLY
        assert page_param.default == 1

    def test_compare_params(self, protocol_methods: dict) -> None:
        sig = protocol_methods["compare"]
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "owner" in params
        assert "repo" in params
        assert "base" in params
        assert "head" in params

    def test_get_releases_params(self, protocol_methods: dict) -> None:
        sig = protocol_methods["get_releases"]
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "owner" in params
        assert "repo" in params
        assert "since" in params
        # since should be keyword-only with default=None
        since_param = sig.parameters["since"]
        assert since_param.kind == inspect.Parameter.KEYWORD_ONLY
        assert since_param.default is None

    def test_get_repo_params(self, protocol_methods: dict) -> None:
        sig = protocol_methods["get_repo"]
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "owner" in params
        assert "repo" in params

    def test_get_commit_messages_params(self, protocol_methods: dict) -> None:
        sig = protocol_methods["get_commit_messages"]
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "owner" in params
        assert "repo" in params
        assert "since" in params
        # since should be keyword-only with default=None
        since_param = sig.parameters["since"]
        assert since_param.kind == inspect.Parameter.KEYWORD_ONLY
        assert since_param.default is None

    def test_get_file_diff_params(self, protocol_methods: dict) -> None:
        sig = protocol_methods["get_file_diff"]
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "owner" in params
        assert "repo" in params
        assert "base" in params
        assert "head" in params
        assert "path" in params

    def test_get_rate_limit_params(self, protocol_methods: dict) -> None:
        sig = protocol_methods["get_rate_limit"]
        params = list(sig.parameters.keys())
        assert "self" in params
        # get_rate_limit takes no arguments beyond self
        assert len(params) == 1


class TestNotificationBackendSignatures:
    """Verify NotificationBackend methods have the expected parameter names."""

    def test_deliver_params(self) -> None:
        sig = inspect.signature(NotificationBackend.deliver)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "digest" in params

    def test_backend_name_params(self) -> None:
        sig = inspect.signature(NotificationBackend.backend_name)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert len(params) == 1


class TestEmbeddingProviderSignatures:
    """Verify EmbeddingProvider methods have the expected parameter names."""

    def test_embed_params(self) -> None:
        sig = inspect.signature(EmbeddingProvider.embed)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "texts" in params

    def test_dimensions_params(self) -> None:
        sig = inspect.signature(EmbeddingProvider.dimensions)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert len(params) == 1


# ===========================================================================
# Test: Protocol method count matches expectations
# ===========================================================================


class TestProtocolMethodCount:
    """Verify each protocol exposes the expected number of abstract methods."""

    def _protocol_method_names(self, protocol: type) -> set[str]:
        """Return names of methods defined on the protocol (excluding dunder)."""
        return {
            name
            for name in dir(protocol)
            if not name.startswith("_") and callable(getattr(protocol, name, None))
        }

    def test_git_provider_has_8_methods(self) -> None:
        methods = self._protocol_method_names(GitProvider)
        expected = {
            "get_user_repos",
            "get_forks",
            "compare",
            "get_releases",
            "get_repo",
            "get_commit_messages",
            "get_file_diff",
            "get_rate_limit",
        }
        assert methods == expected

    def test_notification_backend_has_2_methods(self) -> None:
        methods = self._protocol_method_names(NotificationBackend)
        expected = {"deliver", "backend_name"}
        assert methods == expected

    def test_embedding_provider_has_2_methods(self) -> None:
        methods = self._protocol_method_names(EmbeddingProvider)
        expected = {"embed", "dimensions"}
        assert methods == expected
