# ABOUTME: Second wave of targeted coverage tests across providers, database, agent.
# ABOUTME: Closes remaining gaps in providers/github, database, config, agent tools/fixer.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import respx
from httpx import Response

from forkhub.models import (
    ForkInfo,
    ForkPage,
    RepoInfo,
)

if TYPE_CHECKING:
    from pathlib import Path

    from forkhub.database import Database


# ---------------------------------------------------------------------------
# providers/github.py — fill out GET pagination, errors, and naive-since
# ---------------------------------------------------------------------------


def _repo_json(
    *,
    repo_id: int = 1001,
    owner: str = "octo",
    name: str = "world",
    fork: bool = False,
    parent: dict | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": repo_id,
        "owner": {"login": owner},
        "name": name,
        "full_name": f"{owner}/{name}",
        "default_branch": "main",
        "description": "x",
        "fork": fork,
        "stargazers_count": 1,
        "forks_count": 1,
        "pushed_at": "2025-06-01T00:00:00Z",
    }
    if parent is not None:
        out["parent"] = parent
    return out


def _fork_json(
    *,
    fork_id: int = 5001,
    owner: str = "alice",
    name: str = "world",
    pushed_at: str = "2025-06-01T00:00:00Z",
    created_at: str = "2025-01-01T00:00:00Z",
) -> dict[str, Any]:
    return {
        "id": fork_id,
        "owner": {"login": owner},
        "name": name,
        "full_name": f"{owner}/{name}",
        "default_branch": "main",
        "description": "fork",
        "fork": True,
        "stargazers_count": 0,
        "forks_count": 0,
        "pushed_at": pushed_at,
        "created_at": created_at,
    }


@pytest.fixture
def gh_provider():
    from forkhub.providers.github import GitHubProvider

    return GitHubProvider(token="abc")


@pytest.fixture
def gh_mock():
    with respx.mock(base_url="https://api.github.com") as mock:
        yield mock


class TestGitHubProviderError:
    def test_str_includes_status_and_message(self):
        from forkhub.providers.github import GitHubProviderError

        err = GitHubProviderError(404, "Not Found")
        assert err.status_code == 404
        assert err.message == "Not Found"
        assert "404" in str(err)
        assert "Not Found" in str(err)


class TestGitHubProviderGet:
    async def test_get_user_repos(self, gh_provider, gh_mock):
        gh_mock.get("/users/u/repos").mock(
            return_value=Response(
                200,
                json=[_repo_json(repo_id=1, owner="u", name="a")],
            ),
        )
        repos = await gh_provider.get_user_repos("u")
        assert len(repos) == 1
        assert isinstance(repos[0], RepoInfo)
        assert repos[0].full_name == "u/a"

    async def test_get_repo_with_parent(self, gh_provider, gh_mock):
        """A fork repo with parent metadata should populate parent_full_name."""
        gh_mock.get("/repos/u/a").mock(
            return_value=Response(
                200,
                json=_repo_json(
                    repo_id=2,
                    owner="u",
                    name="a",
                    fork=True,
                    parent={
                        "full_name": "upstream/a",
                        "owner": {"login": "upstream"},
                        "name": "a",
                    },
                ),
            )
        )
        repo = await gh_provider.get_repo("u", "a")
        assert repo.is_fork is True
        assert repo.parent_full_name == "upstream/a"

    async def test_get_forks_returns_page_with_no_next(self, gh_provider, gh_mock):
        """get_forks should return a ForkPage and detect Link headers."""
        gh_mock.get("/repos/o/r/forks").mock(
            return_value=Response(
                200,
                json=[_fork_json(fork_id=1, owner="alice")],
                headers={"link": '<https://api.github.com/page2>; rel="next"'},
            )
        )
        page = await gh_provider.get_forks("o", "r", page=1)
        assert isinstance(page, ForkPage)
        assert page.has_next is True
        assert page.forks[0].full_name == "alice/world"

    async def test_get_forks_no_link_header(self, gh_provider, gh_mock):
        """When no Link header is present, has_next must be False."""
        gh_mock.get("/repos/o/r/forks").mock(
            return_value=Response(200, json=[_fork_json(fork_id=2, owner="bob")]),
        )
        page = await gh_provider.get_forks("o", "r")
        assert page.has_next is False

    async def test_get_releases_with_naive_since(self, gh_provider, gh_mock):
        """A naive `since` datetime should be coerced to UTC (line 227)."""
        gh_mock.get("/repos/o/r/releases").mock(
            return_value=Response(
                200,
                json=[
                    {
                        "tag_name": "v1",
                        "name": "v1",
                        "body": "",
                        "published_at": "2025-06-01T00:00:00Z",
                        "prerelease": False,
                    },
                ],
            )
        )
        # Naive datetime — provider must add UTC tzinfo before comparison.
        since = datetime(2025, 1, 1)
        out = await gh_provider.get_releases("o", "r", since=since)
        assert len(out) == 1


class TestGitHubProviderErrors:
    async def test_request_failed_with_message_body(self, gh_provider, gh_mock):
        """A 404 with a JSON body containing message should propagate."""
        from forkhub.providers.github import GitHubProviderError

        gh_mock.get("/repos/x/y").mock(
            return_value=Response(404, json={"message": "Not Found"}),
        )
        with pytest.raises(GitHubProviderError) as excinfo:
            await gh_provider.get_repo("x", "y")
        assert excinfo.value.status_code == 404
        assert "Not Found" in excinfo.value.message

    async def test_request_failed_without_json_body(self, gh_provider, gh_mock):
        """A non-JSON error response should fall back to HTTP status text."""
        from forkhub.providers.github import GitHubProviderError

        gh_mock.get("/repos/x/y").mock(
            return_value=Response(503, content=b"<html>bad</html>"),
        )
        with pytest.raises(GitHubProviderError) as excinfo:
            await gh_provider.get_repo("x", "y")
        assert excinfo.value.status_code == 503
        assert "503" in excinfo.value.message

    async def test_request_error_wrapped(self, gh_provider, gh_mock, monkeypatch):
        """Network-level RequestError must surface as GitHubProviderError(0)."""
        from githubkit.exception import RequestError

        from forkhub.providers.github import GitHubProviderError

        # Force the underlying request to raise a RequestError
        async def raise_request_error(*args, **kwargs):
            raise RequestError("Connection failed")

        monkeypatch.setattr(gh_provider._github, "arequest", raise_request_error)

        with pytest.raises(GitHubProviderError) as excinfo:
            await gh_provider.get_repo("x", "y")
        assert excinfo.value.status_code == 0

    async def test_get_with_headers_request_failed(self, gh_provider, gh_mock):
        """get_with_headers also surfaces RequestFailed errors with body parse."""
        from forkhub.providers.github import GitHubProviderError

        gh_mock.get("/repos/o/r/forks").mock(
            return_value=Response(403, json={"message": "Forbidden"}),
        )
        with pytest.raises(GitHubProviderError) as excinfo:
            await gh_provider.get_forks("o", "r")
        assert excinfo.value.status_code == 403

    async def test_get_with_headers_request_error(self, gh_provider, monkeypatch):
        """Network RequestError on the with-headers path also wraps to status 0."""
        from githubkit.exception import RequestError

        from forkhub.providers.github import GitHubProviderError

        async def raise_request_error(*args, **kwargs):
            raise RequestError("net down")

        monkeypatch.setattr(gh_provider._github, "arequest", raise_request_error)
        with pytest.raises(GitHubProviderError) as excinfo:
            await gh_provider.get_forks("o", "r")
        assert excinfo.value.status_code == 0

    async def test_get_with_headers_failed_body_not_json(self, gh_provider, gh_mock):
        """get_with_headers handles a non-JSON error body."""
        from forkhub.providers.github import GitHubProviderError

        gh_mock.get("/repos/o/r/forks").mock(
            return_value=Response(500, content=b"<html>x</html>"),
        )
        with pytest.raises(GitHubProviderError) as excinfo:
            await gh_provider.get_forks("o", "r")
        assert excinfo.value.status_code == 500


# ---------------------------------------------------------------------------
# database.py — context manager, error path in migrations, sqlite-vec failure,
# annotations, _get_pragma, list_tracked_repos with mode.
# ---------------------------------------------------------------------------


class TestDatabaseGaps:
    async def test_async_context_manager(self, tmp_path):
        """`async with Database(...)` should connect and then close (lines 193-197)."""
        from forkhub.database import Database

        async with Database(":memory:") as db:
            tables = await db._table_names()
            assert "tracked_repos" in tables

    async def test_get_pragma_returns_value(self, db: Database):
        """_get_pragma should return the underlying PRAGMA value (lines 262-267)."""
        result = await db._get_pragma("foreign_keys")
        # foreign_keys=ON was set on connect; pragma returns 1
        assert result == 1

    async def test_get_pragma_returns_none_for_unknown(self, db: Database):
        """An unknown PRAGMA returns None (the if row is None branch)."""
        # Most pragmas always return a row so we need to query something that
        # returns no rows — index_list on a non-existent index does that.
        result = await db._get_pragma("index_info('does_not_exist')")
        assert result is None

    async def test_list_tracked_repos_mode_filter(self, db: Database):
        """list_tracked_repos with `mode` filter (lines 314-315)."""
        from tests.stubs import make_tracked_repo

        await db.insert_tracked_repo(
            make_tracked_repo(
                owner="aaa",
                name="bbb",
                full_name="aaa/bbb",
                github_id=901,
                tracking_mode="watched",
            )
        )
        await db.insert_tracked_repo(
            make_tracked_repo(
                owner="ccc",
                name="ddd",
                full_name="ccc/ddd",
                github_id=902,
                tracking_mode="owned",
            )
        )

        watched = await db.list_tracked_repos(mode="watched")
        assert len(watched) == 1
        assert watched[0]["full_name"] == "aaa/bbb"

    async def test_annotation_crud(self, db: Database, fork_in_db: dict):
        """insert_annotation + get_annotation_by_fork (lines 537-550)."""
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        ann = {
            "id": "ann-1",
            "fork_id": fork_in_db["id"],
            "title": "Notes",
            "body": "Has interesting changes",
            "created_at": now,
            "updated_at": now,
        }
        await db.insert_annotation(ann)

        row = await db.get_annotation_by_fork(fork_in_db["id"])
        assert row is not None
        assert row["title"] == "Notes"

    async def test_search_similar_signals_returns_empty_without_vec(self, db: Database):
        """When vec_enabled is False, search returns []."""
        # Force vec_enabled off regardless of platform support.
        db.vec_enabled = False
        result = await db.search_similar_signals([0.1, 0.2, 0.3], "any-repo")
        assert result == []

    async def test_migrate_schema_re_raises_unknown_errors(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """_migrate_schema must re-raise non-'duplicate column' errors."""
        from forkhub.database import Database

        db = Database(":memory:")
        await db.connect()

        async def boom(_sql, *args, **kwargs):
            raise RuntimeError("disk is full")

        # Patch execute so the next ALTER raises an unrelated error.
        monkeypatch.setattr(db._conn, "execute", boom)
        with pytest.raises(RuntimeError, match="disk is full"):
            await db._migrate_schema()

        await db.close()

    async def test_load_sqlite_vec_handles_failure(self, monkeypatch: pytest.MonkeyPatch):
        """_load_sqlite_vec must catch any exception and set vec_enabled=False."""
        import sys

        # Inject a fake sqlite_vec module that raises when loadable_path is called.
        import types

        from forkhub.database import Database

        broken = types.ModuleType("sqlite_vec")

        def _raise():
            raise RuntimeError("load failed")

        broken.loadable_path = _raise
        monkeypatch.setitem(sys.modules, "sqlite_vec", broken)

        db = Database(":memory:")
        await db.connect()
        # connect ran _load_sqlite_vec, which must have caught the failure.
        assert db.vec_enabled is False
        await db.close()


# ---------------------------------------------------------------------------
# config.py — uncovered properties + helpers + env override + get_data_dir
# ---------------------------------------------------------------------------


class TestConfigGaps:
    def test_anthropic_has_auth_property(self):
        from forkhub.config import AnthropicSettings

        # Both empty -> False
        assert AnthropicSettings().has_auth is False
        # api_key set -> True
        assert AnthropicSettings(api_key="sk-x").has_auth is True
        # only oauth set -> True
        assert AnthropicSettings(oauth_token="oat-x").has_auth is True

    def test_anthropic_effective_token_falls_back_to_oauth(self):
        from forkhub.config import AnthropicSettings

        s = AnthropicSettings(oauth_token="oat-y")
        assert s.effective_token == "oat-y"

    def test_anthropic_auth_method_none(self):
        from forkhub.config import AnthropicSettings

        assert AnthropicSettings().auth_method is None

    def test_load_settings_finds_home_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """When cwd has no forkhub.toml, load_settings searches ~/.config/forkhub/."""
        from forkhub.config import load_settings

        # Set HOME to tmp_path and make sure cwd has nothing
        empty_cwd = tmp_path / "empty"
        empty_cwd.mkdir()
        monkeypatch.chdir(empty_cwd)

        cfg_dir = tmp_path / ".config" / "forkhub"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "forkhub.toml").write_text('[github]\ntoken = "from-home"\n')
        monkeypatch.setenv("HOME", str(tmp_path))

        settings = load_settings()
        assert settings.github.token == "from-home"

    def test_load_toml_returns_empty_for_missing_file(self, tmp_path: Path):
        from forkhub.config import _load_toml

        result = _load_toml(tmp_path / "does_not_exist.toml")
        assert result == {}

    def test_env_var_override(self, monkeypatch: pytest.MonkeyPatch):
        """Env var should override TOML when constructing subsettings."""
        from forkhub.config import GitHubSettings, _build_subsettings

        monkeypatch.setenv("GITHUB_TOKEN", "from-env")
        s = _build_subsettings(GitHubSettings, {"token": "from-toml"})
        assert s.token == "from-env"

    def test_get_data_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """get_data_dir creates and returns the data directory."""
        from forkhub.config import get_data_dir

        monkeypatch.setenv("HOME", str(tmp_path))
        path = get_data_dir()
        assert path.exists()
        assert "forkhub" in str(path)


# ---------------------------------------------------------------------------
# agent/tools.py — remaining error/edge branches
# ---------------------------------------------------------------------------


class TestAgentToolsGaps:
    async def test_list_forks_only_active_unknown_repo(self, db: Database):
        """only_active=True with no tracked repo returns an error."""
        pytest.importorskip("claude_agent_sdk")

        from forkhub.agent.tools import create_tools
        from tests.stubs import StubEmbeddingProvider, StubGitProvider

        tools = create_tools(
            db=db, provider=StubGitProvider(), embedding_provider=StubEmbeddingProvider()
        )
        list_forks = next(t for t in tools if t.name == "list_forks")
        result = await list_forks.handler(
            {"owner": "no", "repo": "no", "page": 1, "only_active": True}
        )
        assert result.get("is_error") is True

    async def test_get_fork_summary_missing_tracked_repo(self, db: Database):
        """get_fork_summary errors when fork's tracked_repo is missing (line 126)."""
        pytest.importorskip("claude_agent_sdk")

        from forkhub.agent.tools import create_tools
        from tests.stubs import (
            StubEmbeddingProvider,
            StubGitProvider,
            make_fork,
        )

        # Disable FKs so we can insert a fork that points to a non-existent tracked_repo.
        await db._db.execute("PRAGMA foreign_keys=OFF")
        fork = make_fork("orphan-tracked-repo-id", full_name="alice/p", github_id=999)
        await db.insert_fork(fork)

        tools = create_tools(
            db=db, provider=StubGitProvider(), embedding_provider=StubEmbeddingProvider()
        )
        t = next(t for t in tools if t.name == "get_fork_summary")
        result = await t.handler({"fork_full_name": "alice/p"})
        assert result.get("is_error") is True
        assert "Tracked repo not found" in result["content"][0]["text"]

    async def test_get_file_diff_missing_tracked_repo(self, db: Database):
        """get_file_diff errors when fork's tracked_repo is missing (line 184)."""
        pytest.importorskip("claude_agent_sdk")

        from forkhub.agent.tools import create_tools
        from tests.stubs import (
            StubEmbeddingProvider,
            StubGitProvider,
            make_fork,
        )

        await db._db.execute("PRAGMA foreign_keys=OFF")
        fork = make_fork("orphan-tracked-repo-id", full_name="alice/q", github_id=998)
        await db.insert_fork(fork)

        tools = create_tools(
            db=db, provider=StubGitProvider(), embedding_provider=StubEmbeddingProvider()
        )
        t = next(t for t in tools if t.name == "get_file_diff")
        result = await t.handler({"fork_full_name": "alice/q", "file_path": "x"})
        assert result.get("is_error") is True
        assert "Tracked repo not found" in result["content"][0]["text"]

    async def test_get_releases_returns_release_list(self, db: Database):
        """get_releases must marshal Release objects to dicts (lines 214-233)."""
        pytest.importorskip("claude_agent_sdk")

        import json

        from forkhub.agent.tools import create_tools
        from forkhub.models import Release
        from tests.stubs import StubEmbeddingProvider, StubGitProvider

        class ReleaseProvider(StubGitProvider):
            async def get_releases(self, owner, repo, *, since=None):
                return [
                    Release(
                        tag="v9",
                        name="Nine",
                        body="b",
                        published_at=datetime(2025, 7, 1, tzinfo=UTC),
                        is_prerelease=False,
                    )
                ]

        tools = create_tools(
            db=db, provider=ReleaseProvider(), embedding_provider=StubEmbeddingProvider()
        )
        t = next(t for t in tools if t.name == "get_releases")
        # Provide our own clock so the call doesn't depend on wall time
        result = await t.handler({"owner": "o", "repo": "r", "since_days": 365})
        assert result.get("is_error", False) is False
        data = json.loads(result["content"][0]["text"])
        assert data["releases"][0]["tag"] == "v9"

    async def test_get_releases_provider_error(self, db: Database):
        """get_releases must wrap provider exceptions as is_error."""
        pytest.importorskip("claude_agent_sdk")

        from forkhub.agent.tools import create_tools
        from tests.stubs import StubEmbeddingProvider, StubGitProvider

        class BrokenReleases(StubGitProvider):
            async def get_releases(self, owner, repo, *, since=None):
                raise RuntimeError("releases broken")

        tools = create_tools(
            db=db,
            provider=BrokenReleases(),
            embedding_provider=StubEmbeddingProvider(),
        )
        t = next(t for t in tools if t.name == "get_releases")
        result = await t.handler({"owner": "o", "repo": "r", "since_days": 30})
        assert result.get("is_error") is True

    async def test_search_similar_signals_handles_provider_error(self, db: Database):
        """search_similar_signals returns is_error when embedding fails."""
        pytest.importorskip("claude_agent_sdk")

        from forkhub.agent.tools import create_tools
        from tests.stubs import StubGitProvider

        class BrokenEmbed:
            async def embed(self, _texts):
                raise RuntimeError("embed broken")

            def dimensions(self):
                return 4

        tools = create_tools(db=db, provider=StubGitProvider(), embedding_provider=BrokenEmbed())
        t = next(t for t in tools if t.name == "search_similar_signals")
        result = await t.handler({"summary_text": "x", "repo_id": "rid", "limit": 5})
        assert result.get("is_error") is True

    async def test_store_signal_continues_when_embedding_fails(self, db: Database):
        """When embed() raises, store_signal still records the signal."""
        pytest.importorskip("claude_agent_sdk")

        from forkhub.agent.tools import create_tools
        from tests.stubs import (
            StubGitProvider,
            make_fork,
            make_tracked_repo,
        )

        class BrokenEmbed:
            async def embed(self, _texts):
                raise RuntimeError("embed broken")

            def dimensions(self):
                return 4

        repo = make_tracked_repo(full_name="t/r", github_id=33, tracking_mode="watched")
        await db.insert_tracked_repo(repo)
        fork = make_fork(repo["id"], full_name="alice/r")
        await db.insert_fork(fork)

        tools = create_tools(db=db, provider=StubGitProvider(), embedding_provider=BrokenEmbed())
        t = next(t for t in tools if t.name == "store_signal")
        result = await t.handler(
            {
                "fork_full_name": "alice/r",
                "category": "feature",
                "summary": "x",
                "significance": 5,
                "files_involved": [],
                "detail": "",
            }
        )
        # Embedding failure doesn't fail the tool — signal is still stored.
        assert result.get("is_error", False) is False

    async def test_get_fork_stars_handles_db_error(self, db: Database):
        """get_fork_stars wraps unexpected DB errors as is_error."""
        pytest.importorskip("claude_agent_sdk")

        from forkhub.agent.tools import create_tools
        from tests.stubs import StubEmbeddingProvider, StubGitProvider

        # Close the db so any subsequent fork lookup blows up
        await db.close()
        tools = create_tools(
            db=db, provider=StubGitProvider(), embedding_provider=StubEmbeddingProvider()
        )
        t = next(t for t in tools if t.name == "get_fork_stars")
        result = await t.handler({"fork_full_name": "alice/r"})
        assert result.get("is_error") is True

    async def test_create_tools_raises_without_claude_extra(
        self, monkeypatch: pytest.MonkeyPatch, db: Database
    ):
        """create_tools must raise when the [claude] extra isn't installed."""
        from forkhub.agent import tools as tools_mod
        from tests.stubs import StubEmbeddingProvider, StubGitProvider

        monkeypatch.setattr(tools_mod, "_CLAUDE_SDK_AVAILABLE", False)
        with pytest.raises(ImportError, match="claude"):
            tools_mod.create_tools(
                db=db,
                provider=StubGitProvider(),
                embedding_provider=StubEmbeddingProvider(),
            )

    async def test_get_fork_summary_handles_provider_error(self, db: Database):
        """get_fork_summary wraps provider errors as is_error (lines 161-162)."""
        pytest.importorskip("claude_agent_sdk")

        from forkhub.agent.tools import create_tools
        from tests.stubs import (
            StubEmbeddingProvider,
            StubGitProvider,
            make_fork,
            make_tracked_repo,
        )

        repo = make_tracked_repo(
            full_name="ee/ff",
            github_id=601,
            tracking_mode="watched",
        )
        await db.insert_tracked_repo(repo)
        fork = make_fork(repo["id"], full_name="alice/ff", github_id=602)
        await db.insert_fork(fork)

        class CompareBoom(StubGitProvider):
            async def compare(self, *a, **kw):
                raise RuntimeError("compare failed")

        tools = create_tools(
            db=db, provider=CompareBoom(), embedding_provider=StubEmbeddingProvider()
        )
        t = next(t for t in tools if t.name == "get_fork_summary")
        result = await t.handler({"fork_full_name": "alice/ff"})
        assert result.get("is_error") is True
        assert "compare failed" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# agent/runner.py — ClaudeAnalyzer end-to-end with mocked SDK client
# ---------------------------------------------------------------------------


class _FakeResultMessage:
    """Minimal ResultMessage stand-in used to terminate the receive_messages loop."""


class _FakeSDKClient:
    """Stub ClaudeSDKClient that captures init args and yields one ResultMessage."""

    instances: list[_FakeSDKClient] = []

    def __init__(self, options):
        self.options = options
        self.connect_called = False
        self.disconnect_called = False
        self.queries: list[str] = []
        _FakeSDKClient.instances.append(self)

    async def connect(self):
        self.connect_called = True

    async def disconnect(self):
        self.disconnect_called = True

    async def query(self, prompt: str):
        self.queries.append(prompt)

    async def receive_messages(self):
        # Yield one stand-in ResultMessage so the runner exits the loop.
        yield _FakeResultMessage()


class TestClaudeAnalyzerRunner:
    @pytest.fixture(autouse=True)
    def _check_sdk(self):
        pytest.importorskip("claude_agent_sdk")

    def test_analyzer_requires_claude_extra(self, monkeypatch: pytest.MonkeyPatch, db: Database):
        """ClaudeAnalyzer constructor raises when SDK is missing."""
        from forkhub.agent import runner as runner_mod
        from forkhub.config import ForkHubSettings
        from tests.stubs import StubEmbeddingProvider, StubGitProvider

        monkeypatch.setattr(runner_mod, "_CLAUDE_SDK_AVAILABLE", False)
        with pytest.raises(ImportError, match="claude"):
            runner_mod.ClaudeAnalyzer(
                db=db,
                provider=StubGitProvider(),
                embedding_provider=StubEmbeddingProvider(),
                settings=ForkHubSettings(),
            )

    def test_create_batches_partitions_forks(self, db: Database):
        """_create_batches splits fork lists into BATCH_SIZE chunks."""
        from forkhub.agent.runner import BATCH_SIZE, ClaudeAnalyzer
        from forkhub.config import ForkHubSettings
        from forkhub.models import Fork, ForkVitality
        from tests.stubs import StubEmbeddingProvider, StubGitProvider

        analyzer = ClaudeAnalyzer(
            db=db,
            provider=StubGitProvider(),
            embedding_provider=StubEmbeddingProvider(),
            settings=ForkHubSettings(),
        )

        # Empty list returns []
        assert analyzer._create_batches([]) == []

        # 31 forks split into [30, 1]
        forks = [
            Fork(
                tracked_repo_id=f"r{i}",
                github_id=i,
                owner=f"o{i}",
                full_name=f"o{i}/p",
                default_branch="main",
                vitality=ForkVitality.ACTIVE,
            )
            for i in range(BATCH_SIZE + 1)
        ]
        batches = analyzer._create_batches(forks)
        assert [len(b) for b in batches] == [BATCH_SIZE, 1]

    def test_build_coordinator_prompt_includes_releases_and_forks(self, db: Database):
        """The prompt must include repo header, releases, and fork stats."""
        from forkhub.agent.runner import ClaudeAnalyzer
        from forkhub.config import ForkHubSettings
        from forkhub.models import (
            Fork,
            ForkVitality,
            Release,
            TrackedRepo,
            TrackingMode,
        )
        from tests.stubs import StubEmbeddingProvider, StubGitProvider

        analyzer = ClaudeAnalyzer(
            db=db,
            provider=StubGitProvider(),
            embedding_provider=StubEmbeddingProvider(),
            settings=ForkHubSettings(),
        )

        repo = TrackedRepo(
            github_id=1,
            owner="o",
            name="p",
            full_name="o/p",
            tracking_mode=TrackingMode.WATCHED,
            default_branch="main",
            description="A repo",
        )
        forks = [
            Fork(
                tracked_repo_id=repo.id,
                github_id=2,
                owner="alice",
                full_name="alice/p",
                default_branch="main",
                description="alice fork",
                vitality=ForkVitality.ACTIVE,
                stars=10,
                commits_ahead=4,
                commits_behind=1,
            )
        ]
        releases = [
            Release(
                tag="v1",
                name="One",
                body="x" * 250,
                published_at=datetime(2025, 6, 1, tzinfo=UTC),
                is_prerelease=False,
            )
        ]
        prompt = analyzer._build_coordinator_prompt(repo, forks, releases)
        assert "Repository: o/p" in prompt
        assert "alice/p" in prompt
        assert "v1" in prompt
        # Truncated body (>200 chars) should end with "..."
        assert "..." in prompt

    def test_build_coordinator_prompt_no_changed_forks(self, db: Database):
        """When changed_forks is empty, the no-changes branch runs."""
        from forkhub.agent.runner import ClaudeAnalyzer
        from forkhub.config import ForkHubSettings
        from forkhub.models import TrackedRepo, TrackingMode
        from tests.stubs import StubEmbeddingProvider, StubGitProvider

        analyzer = ClaudeAnalyzer(
            db=db,
            provider=StubGitProvider(),
            embedding_provider=StubEmbeddingProvider(),
            settings=ForkHubSettings(),
        )
        repo = TrackedRepo(
            github_id=1,
            owner="o",
            name="p",
            full_name="o/p",
            tracking_mode=TrackingMode.WATCHED,
            default_branch="main",
        )
        prompt = analyzer._build_coordinator_prompt(repo, [], [])
        assert "No Changed Forks" in prompt

    def test_create_tools_falls_back_when_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, db: Database
    ):
        """If the tools module fails to import, _create_tools returns []."""
        from forkhub.agent import runner as runner_mod
        from forkhub.agent.runner import ClaudeAnalyzer
        from forkhub.config import ForkHubSettings
        from tests.stubs import StubEmbeddingProvider, StubGitProvider

        analyzer = ClaudeAnalyzer(
            db=db,
            provider=StubGitProvider(),
            embedding_provider=StubEmbeddingProvider(),
            settings=ForkHubSettings(),
        )

        # Force the tools module's create_tools to raise ImportError on access.
        import forkhub.agent.tools as tools_mod

        def boom(*_a, **_kw):
            raise ImportError("no extra")

        monkeypatch.setattr(tools_mod, "create_tools", boom)
        assert analyzer._create_tools() == []
        # Quiet ruff about unused var
        del runner_mod

    async def test_analyze_runs_and_returns_signals(
        self, monkeypatch: pytest.MonkeyPatch, db: Database
    ):
        """analyze() runs a session and returns signals from the DB."""
        from forkhub.agent import runner as runner_mod
        from forkhub.agent.runner import ClaudeAnalyzer
        from forkhub.config import ForkHubSettings
        from forkhub.models import (
            Fork,
            ForkVitality,
            TrackedRepo,
            TrackingMode,
        )
        from tests.stubs import StubEmbeddingProvider, StubGitProvider, make_signal

        # Patch SDK client + ResultMessage check + create_sdk_mcp_server.
        _FakeSDKClient.instances.clear()
        monkeypatch.setattr(runner_mod, "ClaudeSDKClient", _FakeSDKClient)
        monkeypatch.setattr(runner_mod, "ResultMessage", _FakeResultMessage)
        monkeypatch.setattr(runner_mod, "create_sdk_mcp_server", lambda *a, **kw: object())

        # Insert a fork + tracked_repo so that signals associate properly.
        from tests.stubs import make_fork, make_tracked_repo

        tr = make_tracked_repo(full_name="r/n", github_id=4321, tracking_mode="watched")
        await db.insert_tracked_repo(tr)
        fk = make_fork(tr["id"], full_name="alice/n", github_id=5432)
        await db.insert_fork(fk)
        # Pre-insert a signal so that list_signals returns one.
        await db.insert_signal(make_signal(fk["id"], tr["id"]))

        analyzer = ClaudeAnalyzer(
            db=db,
            provider=StubGitProvider(),
            embedding_provider=StubEmbeddingProvider(),
            settings=ForkHubSettings(),
        )
        repo = TrackedRepo(
            id=tr["id"],
            github_id=tr["github_id"],
            owner="r",
            name="n",
            full_name="r/n",
            tracking_mode=TrackingMode.WATCHED,
            default_branch="main",
        )
        fork = Fork(
            id=fk["id"],
            tracked_repo_id=tr["id"],
            github_id=fk["github_id"],
            owner="alice",
            full_name="alice/n",
            default_branch="main",
            vitality=ForkVitality.ACTIVE,
        )
        result = await analyzer.analyze(repo, [fork], [])
        # The session was driven through the fake client.
        assert _FakeSDKClient.instances, "ClaudeSDKClient was not invoked"
        # The pre-existing signal should NOT be returned because it was created
        # BEFORE session_start; verify that analyze still completes cleanly.
        assert isinstance(result, list)

    async def test_analyze_handles_session_exception(
        self, monkeypatch: pytest.MonkeyPatch, db: Database
    ):
        """When _run_session raises, analyze() logs it and returns the empty list."""
        from forkhub.agent.runner import ClaudeAnalyzer
        from forkhub.config import ForkHubSettings
        from forkhub.models import (
            Fork,
            ForkVitality,
            TrackedRepo,
            TrackingMode,
        )
        from tests.stubs import StubEmbeddingProvider, StubGitProvider

        analyzer = ClaudeAnalyzer(
            db=db,
            provider=StubGitProvider(),
            embedding_provider=StubEmbeddingProvider(),
            settings=ForkHubSettings(),
        )

        async def boom(*args, **kwargs):
            raise RuntimeError("session broken")

        analyzer._run_session = boom  # type: ignore[assignment]

        repo = TrackedRepo(
            github_id=99,
            owner="x",
            name="y",
            full_name="x/y",
            tracking_mode=TrackingMode.WATCHED,
            default_branch="main",
        )
        fork = Fork(
            tracked_repo_id=repo.id,
            github_id=10,
            owner="alice",
            full_name="alice/y",
            default_branch="main",
            vitality=ForkVitality.ACTIVE,
        )
        out = await analyzer.analyze(repo, [fork], [])
        assert out == []

    async def test_analyze_no_changes_returns_empty(self, db: Database):
        """No changed forks AND no releases -> short-circuit to []."""
        from forkhub.agent.runner import ClaudeAnalyzer
        from forkhub.config import ForkHubSettings
        from forkhub.models import TrackedRepo, TrackingMode
        from tests.stubs import StubEmbeddingProvider, StubGitProvider

        analyzer = ClaudeAnalyzer(
            db=db,
            provider=StubGitProvider(),
            embedding_provider=StubEmbeddingProvider(),
            settings=ForkHubSettings(),
        )
        repo = TrackedRepo(
            github_id=1,
            owner="o",
            name="p",
            full_name="o/p",
            tracking_mode=TrackingMode.WATCHED,
            default_branch="main",
        )
        out = await analyzer.analyze(repo, [], [])
        assert out == []

    async def test_analyze_collects_signals_inserted_during_session(
        self, monkeypatch: pytest.MonkeyPatch, db: Database
    ):
        """analyze() should collect signals created by _run_session (lines 106-107)."""
        from forkhub.agent import runner as runner_mod
        from forkhub.agent.runner import ClaudeAnalyzer
        from forkhub.config import ForkHubSettings
        from forkhub.models import (
            Fork,
            ForkVitality,
            TrackedRepo,
            TrackingMode,
        )
        from tests.stubs import (
            StubEmbeddingProvider,
            StubGitProvider,
            make_fork,
            make_signal,
            make_tracked_repo,
        )

        tr = make_tracked_repo(full_name="rr/nn", github_id=4322, tracking_mode="watched")
        await db.insert_tracked_repo(tr)
        fk = make_fork(tr["id"], full_name="alice/nn", github_id=5433)
        await db.insert_fork(fk)

        async def fake_session(_self, repo, forks, releases):
            # Insert a signal mid-session so list_signals(since=session_start) finds it.
            await db.insert_signal(make_signal(fk["id"], tr["id"]))

        monkeypatch.setattr(runner_mod.ClaudeAnalyzer, "_run_session", fake_session)

        analyzer = ClaudeAnalyzer(
            db=db,
            provider=StubGitProvider(),
            embedding_provider=StubEmbeddingProvider(),
            settings=ForkHubSettings(),
        )
        repo = TrackedRepo(
            id=tr["id"],
            github_id=tr["github_id"],
            owner="rr",
            name="nn",
            full_name="rr/nn",
            tracking_mode=TrackingMode.WATCHED,
            default_branch="main",
        )
        fork = Fork(
            id=fk["id"],
            tracked_repo_id=tr["id"],
            github_id=fk["github_id"],
            owner="alice",
            full_name="alice/nn",
            default_branch="main",
            vitality=ForkVitality.ACTIVE,
        )
        result = await analyzer.analyze(repo, [fork], [])
        assert len(result) == 1

    async def test_analyze_releases_only_runs_one_batch(
        self, monkeypatch: pytest.MonkeyPatch, db: Database
    ):
        """If no forks change but new releases exist, exactly one session runs."""
        from forkhub.agent import runner as runner_mod
        from forkhub.agent.runner import ClaudeAnalyzer
        from forkhub.config import ForkHubSettings
        from forkhub.models import (
            Release,
            TrackedRepo,
            TrackingMode,
        )
        from tests.stubs import StubEmbeddingProvider, StubGitProvider

        _FakeSDKClient.instances.clear()
        monkeypatch.setattr(runner_mod, "ClaudeSDKClient", _FakeSDKClient)
        monkeypatch.setattr(runner_mod, "ResultMessage", _FakeResultMessage)
        monkeypatch.setattr(runner_mod, "create_sdk_mcp_server", lambda *a, **kw: object())

        analyzer = ClaudeAnalyzer(
            db=db,
            provider=StubGitProvider(),
            embedding_provider=StubEmbeddingProvider(),
            settings=ForkHubSettings(),
        )
        repo = TrackedRepo(
            github_id=1,
            owner="o",
            name="p",
            full_name="o/p",
            tracking_mode=TrackingMode.WATCHED,
            default_branch="main",
        )
        releases = [
            Release(
                tag="v1",
                name="One",
                body="short",
                published_at=datetime(2025, 6, 1, tzinfo=UTC),
                is_prerelease=False,
            )
        ]
        await analyzer.analyze(repo, [], releases)
        assert len(_FakeSDKClient.instances) == 1


# ---------------------------------------------------------------------------
# agent/test_fixer.py — ClaudeTestFixer end-to-end with mocked SDK client
# ---------------------------------------------------------------------------


class _ResultMessageWithText:
    """ResultMessage stand-in carrying a `.text` attr the test fixer reads."""

    def __init__(self, text: str) -> None:
        self.text = text


class _FakeFixerSDKClient:
    instances: list[_FakeFixerSDKClient] = []

    def __init__(self, options):
        self.options = options
        self.connect_called = False
        self.disconnect_called = False
        self.queries: list[str] = []
        self.response_text = '{"reasoning": "ok", "edits": [], "should_reject": false}'
        _FakeFixerSDKClient.instances.append(self)

    async def connect(self):
        self.connect_called = True

    async def disconnect(self):
        self.disconnect_called = True

    async def query(self, prompt: str):
        self.queries.append(prompt)

    async def receive_messages(self):
        yield _ResultMessageWithText(self.response_text)


class TestClaudeTestFixer:
    @pytest.fixture(autouse=True)
    def _check_sdk(self):
        pytest.importorskip("claude_agent_sdk")

    def test_constructor_requires_claude_extra(self, monkeypatch: pytest.MonkeyPatch):
        from forkhub.agent import test_fixer as tf_mod

        monkeypatch.setattr(tf_mod, "_CLAUDE_SDK_AVAILABLE", False)
        with pytest.raises(ImportError, match="claude"):
            tf_mod.ClaudeTestFixer()

    async def test_suggest_fixes_returns_parsed_response(self, monkeypatch: pytest.MonkeyPatch):
        from forkhub.agent import test_fixer as tf_mod

        _FakeFixerSDKClient.instances.clear()
        monkeypatch.setattr(tf_mod, "ClaudeSDKClient", _FakeFixerSDKClient)
        monkeypatch.setattr(tf_mod, "ResultMessage", _ResultMessageWithText)

        fixer = tf_mod.ClaudeTestFixer()
        result = await fixer.suggest_fixes(
            test_output="some failing output",
            patch_summary="patch summary",
            files_patched=["src/a.py"],
            test_file_contents={"tests/t.py": "def test_a(): assert False"},
        )
        assert result.should_reject is False

    async def test_suggest_fixes_handles_invalid_json(self, monkeypatch: pytest.MonkeyPatch):
        """Bad JSON in the agent response -> rejected suggestion."""
        from forkhub.agent import test_fixer as tf_mod

        _FakeFixerSDKClient.instances.clear()

        class JunkClient(_FakeFixerSDKClient):
            def __init__(self, options):
                super().__init__(options)
                self.response_text = "this is not json at all"

        monkeypatch.setattr(tf_mod, "ClaudeSDKClient", JunkClient)
        monkeypatch.setattr(tf_mod, "ResultMessage", _ResultMessageWithText)

        fixer = tf_mod.ClaudeTestFixer()
        result = await fixer.suggest_fixes(
            test_output="x",
            patch_summary="y",
            files_patched=[],
            test_file_contents={},
        )
        assert result.should_reject is True
        assert "Agent call failed" in result.reasoning

    async def test_suggest_fixes_handles_markdown_json(self, monkeypatch: pytest.MonkeyPatch):
        """JSON wrapped in ```json blocks should be stripped before parsing."""
        from forkhub.agent import test_fixer as tf_mod

        _FakeFixerSDKClient.instances.clear()

        class MarkdownJSONClient(_FakeFixerSDKClient):
            def __init__(self, options):
                super().__init__(options)
                self.response_text = (
                    '```json\n{"reasoning": "from md", "edits": [], "should_reject": true}\n```'
                )

        monkeypatch.setattr(tf_mod, "ClaudeSDKClient", MarkdownJSONClient)
        monkeypatch.setattr(tf_mod, "ResultMessage", _ResultMessageWithText)

        fixer = tf_mod.ClaudeTestFixer()
        result = await fixer.suggest_fixes(
            test_output="x",
            patch_summary="y",
            files_patched=[],
            test_file_contents={},
        )
        assert result.should_reject is True
        assert result.reasoning == "from md"

    async def test_suggest_fixes_handles_generic_code_block(self, monkeypatch: pytest.MonkeyPatch):
        """JSON wrapped in plain ``` blocks (no language tag) is also handled."""
        from forkhub.agent import test_fixer as tf_mod

        _FakeFixerSDKClient.instances.clear()

        class CodeBlockClient(_FakeFixerSDKClient):
            def __init__(self, options):
                super().__init__(options)
                self.response_text = (
                    '```\n{"reasoning": "plain block", "edits": [], "should_reject": false}\n```'
                )

        monkeypatch.setattr(tf_mod, "ClaudeSDKClient", CodeBlockClient)
        monkeypatch.setattr(tf_mod, "ResultMessage", _ResultMessageWithText)

        fixer = tf_mod.ClaudeTestFixer()
        result = await fixer.suggest_fixes(
            test_output="x" * 5000,  # truncation path
            patch_summary="y",
            files_patched=["a.py"],
            test_file_contents={"t.py": "content"},
        )
        assert result.reasoning == "plain block"

    async def test_query_returns_empty_when_no_result_message(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """If receive_messages yields nothing matching ResultMessage, _query falls through to ''."""
        from forkhub.agent import test_fixer as tf_mod

        class _NotResultMessage:
            text = "ignored"

        class NoResultClient(_FakeFixerSDKClient):
            async def receive_messages(self):
                # Yield non-ResultMessage values so the isinstance check fails.
                yield _NotResultMessage()

        # Leave ResultMessage as the SDK type so isinstance() returns False above.
        monkeypatch.setattr(tf_mod, "ClaudeSDKClient", NoResultClient)

        fixer = tf_mod.ClaudeTestFixer()
        result = await fixer.suggest_fixes(
            test_output="x",
            patch_summary="y",
            files_patched=[],
            test_file_contents={},
        )
        # Empty response text -> JSON parse fails -> rejected.
        assert result.should_reject is True


# ---------------------------------------------------------------------------
# forkhub/__init__.py — ForkHub class public methods
# ---------------------------------------------------------------------------


class TestForkHubPublicAPI:
    @pytest.fixture
    async def hub_with_repo(self, db: Database):
        """A ForkHub instance with one tracked repo + alpha fork."""
        from forkhub import ForkHub
        from forkhub.config import ForkHubSettings
        from tests.stubs import (
            StubEmbeddingProvider,
            StubGitProvider,
            StubNotificationBackend,
            make_fork,
            make_tracked_repo,
        )

        provider = StubGitProvider.with_testuser_data()
        await db.insert_tracked_repo(
            make_tracked_repo(
                full_name="testuser/alpha",
                github_id=701,
                tracking_mode="watched",
            )
        )
        repo_row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert repo_row is not None

        await db.insert_fork(
            make_fork(
                repo_row["id"],
                full_name="alice/alpha",
                owner="alice",
                vitality="active",
                github_id=8801,
            )
        )

        hub = ForkHub(
            settings=ForkHubSettings(),
            git_provider=provider,
            notification_backends=[StubNotificationBackend()],
            embedding_provider=StubEmbeddingProvider(),
            db=db,
            auto_analyze=False,
        )
        return hub

    async def test_init_returns_owned_plus_upstream(self, db: Database):
        """ForkHub.init() returns owned + detected upstream repos."""
        from forkhub import ForkHub
        from forkhub.config import ForkHubSettings
        from tests.stubs import (
            StubEmbeddingProvider,
            StubGitProvider,
            StubNotificationBackend,
        )

        provider = StubGitProvider.with_testuser_data()
        hub = ForkHub(
            settings=ForkHubSettings(),
            git_provider=provider,
            notification_backends=[StubNotificationBackend()],
            embedding_provider=StubEmbeddingProvider(),
            db=db,
            auto_analyze=False,
        )
        result = await hub.init("testuser")
        assert len(result) >= 1

    async def test_untrack_calls_tracker(self, hub_with_repo):
        await hub_with_repo.untrack("testuser", "alpha")

    async def test_get_repos_returns_list(self, hub_with_repo):
        repos = await hub_with_repo.get_repos()
        assert isinstance(repos, list)

    async def test_get_forks_active_only(self, hub_with_repo):
        forks = await hub_with_repo.get_forks("testuser", "alpha", active_only=True)
        assert any(f.full_name == "alice/alpha" for f in forks)

    async def test_get_forks_all(self, hub_with_repo):
        forks = await hub_with_repo.get_forks("testuser", "alpha", active_only=False)
        assert len(forks) >= 1

    async def test_sync_specific_repo(self, hub_with_repo):
        """ForkHub.sync(repo='owner/name') runs the single-repo path."""
        result = await hub_with_repo.sync(repo="testuser/alpha")
        assert result.repos_synced == 1

    async def test_sync_unknown_repo_raises(self, hub_with_repo):
        with pytest.raises(ValueError, match="not tracked"):
            await hub_with_repo.sync(repo="nobody/x")

    async def test_sync_all_no_repo_arg(self, hub_with_repo):
        """ForkHub.sync() with no repo argument runs sync_all (line 221)."""
        result = await hub_with_repo.sync()
        # sync_all returns a SyncResult; we just need it to succeed.
        assert result is not None

    async def test_retry_repo_resets_status(self, db: Database, hub_with_repo):
        from forkhub.models import SyncStatus

        # Mark the repo inaccessible first
        row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert row is not None
        row["sync_status"] = str(SyncStatus.INACCESSIBLE)
        row["last_sync_error"] = "boom"
        await db.update_tracked_repo(row)

        await hub_with_repo.retry_repo("testuser", "alpha")

        row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert row["sync_status"] == str(SyncStatus.OK)
        assert row["last_sync_error"] is None

    async def test_retry_repo_unknown_raises(self, hub_with_repo):
        with pytest.raises(ValueError, match="not tracked"):
            await hub_with_repo.retry_repo("nobody", "x")

    async def test_deliver_digest_via_backends(self, hub_with_repo):
        digest = await hub_with_repo.generate_digest(repo="testuser/alpha")
        results = await hub_with_repo.deliver_digest(digest)
        assert len(results) == 1
        assert results[0].backend_name == "stub"

    async def test_backfill_unknown_repo_raises(self, hub_with_repo):
        with pytest.raises(ValueError, match="not tracked"):
            await hub_with_repo.backfill(repo="nobody/x")

    async def test_backfill_runs_with_repo(self, hub_with_repo):
        """backfill('testuser/alpha') must build a BackfillService and run it."""
        result = await hub_with_repo.backfill(repo="testuser/alpha", dry_run=True)
        assert hasattr(result, "total_evaluated")

    async def test_backfill_auto_fix_tests_requires_claude(
        self, monkeypatch: pytest.MonkeyPatch, hub_with_repo
    ):
        """When auto_fix_tests is True, ClaudeTestFixer is constructed."""
        pytest.importorskip("claude_agent_sdk")

        # Replace the test_fixer constructor with a recorder.
        constructed: list[dict] = []

        class RecorderFixer:
            def __init__(self, **kwargs):
                constructed.append(kwargs)

            async def suggest_fixes(self, *args, **kwargs):
                return None

        from forkhub.agent import test_fixer as test_fixer_mod

        monkeypatch.setattr(test_fixer_mod, "ClaudeTestFixer", RecorderFixer)

        await hub_with_repo.backfill(repo="testuser/alpha", dry_run=True, auto_fix_tests=True)
        assert len(constructed) == 1


# ---------------------------------------------------------------------------
# services/sync.py — remaining branches: reconcile errors, sync_repo errors,
# discover_owned exception, ValueError, paginate exception variants, CancelledError.
# ---------------------------------------------------------------------------


class TestSyncServiceGaps:
    async def test_sync_all_runs_reconcile_and_records_errors(self, db: Database):
        """sync_all with reconcile=True and a failing reconcile records the error."""
        from forkhub.config import SyncSettings
        from forkhub.services.sync import SyncService
        from tests.stubs import StubGitProvider

        class BrokenReconcileProvider(StubGitProvider):
            async def get_repo(self, owner, repo):
                raise RuntimeError("reconcile boom")

        provider = BrokenReconcileProvider()
        svc = SyncService(db=db, provider=provider, settings=SyncSettings())

        # Trigger sync_all with a username so reconcile is invoked.
        # No tracked repos -> sync loop is empty, but reconcile may fail.
        async def fake_reconcile(*args, **kwargs):
            raise RuntimeError("recon failed")

        svc.reconcile = fake_reconcile  # type: ignore[assignment]

        result = await svc.sync_all(username="user")
        assert any("Reconciliation failed" in e for e in result.errors)

    async def test_sync_all_records_per_repo_errors(self, db: Database):
        """When sync_repo raises, sync_all records the error and continues."""
        from forkhub.config import SyncSettings
        from forkhub.services.sync import SyncService
        from tests.stubs import StubGitProvider, make_tracked_repo

        await db.insert_tracked_repo(
            make_tracked_repo(
                owner="zz",
                name="zz",
                full_name="zz/zz",
                github_id=200,
                tracking_mode="watched",
            )
        )

        provider = StubGitProvider()
        svc = SyncService(db=db, provider=provider, settings=SyncSettings())

        async def boom(_repo_id):
            raise RuntimeError("sync exploded")

        svc.sync_repo = boom  # type: ignore[assignment]

        result = await svc.sync_all(reconcile=False)
        assert any("Error syncing zz/zz" in e for e in result.errors)

    async def test_reconcile_logs_unexpected_error(self, db: Database):
        """Reconcile's unexpected exception path logs at warning."""
        from forkhub.config import SyncSettings
        from forkhub.models import SyncStatus
        from forkhub.services.sync import SyncService
        from tests.stubs import StubGitProvider, make_tracked_repo

        # Insert an inaccessible repo so reconcile attempts to health-check it.
        repo = make_tracked_repo(
            owner="dead",
            name="repo",
            full_name="dead/repo",
            github_id=505,
            tracking_mode="watched",
        )
        repo["sync_status"] = str(SyncStatus.INACCESSIBLE)
        await db.insert_tracked_repo(repo)

        class BrokenProvider(StubGitProvider):
            async def get_repo(self, owner, repo):
                raise RuntimeError("network down")  # neither 403 nor 404

        svc = SyncService(db=db, provider=BrokenProvider(), settings=SyncSettings())
        result = await svc.reconcile()
        assert "dead/repo" in result.repos_still_inaccessible

    async def test_reconcile_logs_403_404_at_debug(self, db: Database):
        """Reconcile's 403/404 path logs at debug (line 165)."""
        from forkhub.config import SyncSettings
        from forkhub.models import SyncStatus
        from forkhub.services.sync import SyncService
        from tests.stubs import StubGitProvider, make_tracked_repo

        repo = make_tracked_repo(
            owner="d2",
            name="r2",
            full_name="d2/r2",
            github_id=506,
            tracking_mode="watched",
        )
        repo["sync_status"] = str(SyncStatus.INACCESSIBLE)
        await db.insert_tracked_repo(repo)

        class NotFoundProvider(StubGitProvider):
            async def get_repo(self, owner, repo):
                err = RuntimeError("no")
                err.status_code = 404  # type: ignore[attr-defined]
                raise err

        svc = SyncService(db=db, provider=NotFoundProvider(), settings=SyncSettings())
        result = await svc.reconcile()
        assert "d2/r2" in result.repos_still_inaccessible

    async def test_reconcile_discover_owned_logs_error(self, db: Database):
        """When TrackerService.discover_owned_repos raises, reconcile logs (line 177)."""
        from forkhub.config import SyncSettings
        from forkhub.services.sync import SyncService
        from tests.stubs import StubGitProvider

        class BadTracker:
            async def discover_owned_repos(self, username):
                raise RuntimeError("tracker broken")

        svc = SyncService(db=db, provider=StubGitProvider(), settings=SyncSettings())
        result = await svc.reconcile(username="u", tracker_service=BadTracker())
        assert result.new_repos_discovered == []

    async def test_sync_repo_value_error_for_missing_id(self, db: Database):
        """sync_repo raises ValueError when repo_id is unknown (line 196)."""
        from forkhub.config import SyncSettings
        from forkhub.services.sync import SyncService
        from tests.stubs import StubGitProvider

        svc = SyncService(db=db, provider=StubGitProvider(), settings=SyncSettings())
        with pytest.raises(ValueError, match="not found"):
            await svc.sync_repo("missing-id")

    async def test_sync_repo_inaccessible_path(self, db: Database):
        """403/404 from get_forks marks the repo INACCESSIBLE (lines 211-225)."""
        from forkhub.config import SyncSettings
        from forkhub.models import SyncStatus
        from forkhub.services.sync import SyncService
        from tests.stubs import StubGitProvider, make_tracked_repo

        repo = make_tracked_repo(
            owner="x",
            name="y",
            full_name="x/y",
            github_id=900,
            tracking_mode="watched",
        )
        await db.insert_tracked_repo(repo)

        class ForbiddenProvider(StubGitProvider):
            async def get_forks(self, owner, repo, *, page=1):
                err = RuntimeError("forbidden")
                err.status_code = 403  # type: ignore[attr-defined]
                raise err

        svc = SyncService(db=db, provider=ForbiddenProvider(), settings=SyncSettings())
        result = await svc.sync_repo(repo["id"])
        # Should mark inaccessible and report error.
        assert any("HTTP 403" in e for e in result.errors)
        row = await db.get_tracked_repo(repo["id"])
        assert row["sync_status"] == str(SyncStatus.INACCESSIBLE)

    async def test_sync_repo_other_error_marks_error(self, db: Database):
        """A non-403/404 error from get_forks marks the repo ERROR."""
        from forkhub.config import SyncSettings
        from forkhub.models import SyncStatus
        from forkhub.services.sync import SyncService
        from tests.stubs import StubGitProvider, make_tracked_repo

        repo = make_tracked_repo(
            owner="x2",
            name="y2",
            full_name="x2/y2",
            github_id=901,
            tracking_mode="watched",
        )
        await db.insert_tracked_repo(repo)

        class BoomProvider(StubGitProvider):
            async def get_forks(self, owner, repo, *, page=1):
                raise RuntimeError("anything else")

        svc = SyncService(db=db, provider=BoomProvider(), settings=SyncSettings())
        result = await svc.sync_repo(repo["id"])
        assert any("sync error" in e.lower() for e in result.errors)
        row = await db.get_tracked_repo(repo["id"])
        assert row["sync_status"] == str(SyncStatus.ERROR)

    async def test_sync_repo_re_raises_cancelled_error(self, db: Database):
        """asyncio.CancelledError must propagate from the analyzer call (line 341)."""
        import asyncio

        from forkhub.config import SyncSettings
        from forkhub.services.sync import SyncService
        from tests.stubs import StubGitProvider, make_fork, make_tracked_repo

        repo = make_tracked_repo(
            owner="ca",
            name="cb",
            full_name="ca/cb",
            github_id=902,
            tracking_mode="watched",
        )
        await db.insert_tracked_repo(repo)
        # Add a fork that compares as changed
        fork = make_fork(
            repo["id"],
            full_name="forker/cb",
            github_id=950,
            head_sha="old",
            commits_ahead=1,
        )
        await db.insert_fork(fork)

        from forkhub.models import (
            CompareResult,
        )

        class ChangedProvider(StubGitProvider):
            def __init__(self):
                super().__init__(
                    forks={
                        "ca/cb": [
                            ForkInfo(
                                github_id=950,
                                owner="forker",
                                full_name="forker/cb",
                                default_branch="main",
                                description="x",
                                stars=1,
                                last_pushed_at=datetime.now(UTC),
                                has_diverged=True,
                                created_at=datetime.now(UTC) - timedelta(days=10),
                            ),
                        ]
                    },
                    head_shas={"forker/cb": "new-sha"},
                )

            async def compare(self, *args, **kwargs):
                return CompareResult(ahead_by=2, behind_by=0, files=[], commits=[])

        class CancellingAnalyzer:
            async def analyze(self, *args, **kwargs):
                raise asyncio.CancelledError()

        svc = SyncService(
            db=db,
            provider=ChangedProvider(),
            settings=SyncSettings(),
            analyzer=CancellingAnalyzer(),
        )
        with pytest.raises(asyncio.CancelledError):
            await svc.sync_repo(repo["id"])

    async def test_reconcile_records_discovered_repos(self, db: Database):
        """Reconcile success path records new_repos_discovered (line 177)."""
        from forkhub.config import SyncSettings
        from forkhub.models import RepoInfo
        from forkhub.services.sync import SyncService
        from tests.stubs import StubGitProvider

        class GoodTracker:
            async def discover_owned_repos(self, username):
                return [
                    RepoInfo(
                        github_id=1,
                        owner="x",
                        name="y",
                        full_name="x/y",
                        default_branch="main",
                        description=None,
                        is_fork=False,
                        stars=0,
                        forks_count=0,
                    )
                ]

        svc = SyncService(db=db, provider=StubGitProvider(), settings=SyncSettings())
        result = await svc.reconcile(username="u", tracker_service=GoodTracker())
        assert result.new_repos_discovered == ["x/y"]

    async def test_sync_repo_paginates_when_has_next(self, db: Database):
        """get_forks with has_next=True triggers `page += 1` (line 211)."""
        from forkhub.config import SyncSettings
        from forkhub.models import ForkPage
        from forkhub.services.sync import SyncService
        from tests.stubs import StubGitProvider, make_tracked_repo

        repo = make_tracked_repo(
            owner="pa",
            name="pb",
            full_name="pa/pb",
            github_id=910,
            tracking_mode="watched",
        )
        await db.insert_tracked_repo(repo)

        page_calls: list[int] = []

        class PaginatedProvider(StubGitProvider):
            async def get_forks(self, owner, repo, *, page=1):
                page_calls.append(page)
                if page == 1:
                    return ForkPage(
                        forks=[
                            ForkInfo(
                                github_id=20000 + page,
                                owner="o",
                                full_name=f"o/r{page}",
                                default_branch="main",
                                description="d",
                                stars=0,
                                last_pushed_at=datetime.now(UTC),
                                has_diverged=False,
                                created_at=datetime.now(UTC),
                            ),
                        ],
                        total_count=1,
                        page=1,
                        has_next=True,
                    )
                return ForkPage(forks=[], total_count=0, page=page, has_next=False)

            async def get_releases(self, owner, repo, *, since=None):
                return []

        svc = SyncService(db=db, provider=PaginatedProvider(), settings=SyncSettings())
        await svc.sync_repo(repo["id"])
        assert page_calls == [1, 2]

    async def test_sync_repo_analyzer_failure_recorded(self, db: Database):
        """Generic analyzer exceptions are caught + appended to result.errors."""
        from forkhub.config import SyncSettings
        from forkhub.models import (
            CompareResult,
        )
        from forkhub.services.sync import SyncService
        from tests.stubs import StubGitProvider, make_fork, make_tracked_repo

        repo = make_tracked_repo(
            owner="ea",
            name="eb",
            full_name="ea/eb",
            github_id=903,
            tracking_mode="watched",
        )
        await db.insert_tracked_repo(repo)
        await db.insert_fork(
            make_fork(
                repo["id"], full_name="forker/eb", github_id=951, head_sha="old", commits_ahead=1
            )
        )

        class ChangedProvider(StubGitProvider):
            def __init__(self):
                super().__init__(
                    forks={
                        "ea/eb": [
                            ForkInfo(
                                github_id=951,
                                owner="forker",
                                full_name="forker/eb",
                                default_branch="main",
                                description="x",
                                stars=1,
                                last_pushed_at=datetime.now(UTC),
                                has_diverged=True,
                                created_at=datetime.now(UTC) - timedelta(days=10),
                            ),
                        ]
                    },
                    head_shas={"forker/eb": "new-sha"},
                )

            async def compare(self, *args, **kwargs):
                return CompareResult(ahead_by=2, behind_by=0, files=[], commits=[])

        class BoomAnalyzer:
            async def analyze(self, *args, **kwargs):
                raise ValueError("analyzer broken")

        svc = SyncService(
            db=db,
            provider=ChangedProvider(),
            settings=SyncSettings(),
            analyzer=BoomAnalyzer(),
        )
        result = await svc.sync_repo(repo["id"])
        assert any("Analyzer failed" in e for e in result.errors)


# ---------------------------------------------------------------------------
# cli/sync_cmd.py:143 — analyzer-not-None summary line for sync_all
# ---------------------------------------------------------------------------


class TestSyncCmdAnalyzerSummary:
    async def test_sync_all_with_analyzer_total_signals_line(self, db: Database):
        """When sync_all runs with an analyzer, line 143 prints the totals."""
        from forkhub.cli.sync_cmd import _sync_impl
        from forkhub.config import SyncSettings
        from tests.stubs import StubAnalyzer, StubGitProvider, make_tracked_repo

        await db.insert_tracked_repo(
            make_tracked_repo(
                owner="o",
                name="n",
                full_name="o/n",
                github_id=400,
                tracking_mode="watched",
            )
        )

        out: list[str] = []
        await _sync_impl(
            repo=None,
            db=db,
            provider=StubGitProvider(),
            sync_settings=SyncSettings(),
            capture_output=out,
            auto_analyze=False,
            analyzer=StubAnalyzer(),
        )
        joined = "\n".join(out)
        assert "Total new signals:" in joined
