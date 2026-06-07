# ABOUTME: Targeted tests to close coverage gaps across small/medium ForkHub modules.
# ABOUTME: Covers cli output branches, formatting helpers, agent agents/hooks, console backend.

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from forkhub.cli.app import app
from forkhub.models import (
    DeliveryResult,
    Digest,
    Signal,
    SignalCategory,
)
from tests.stubs import StubGitProvider, make_fork, make_signal, make_tracked_repo

if TYPE_CHECKING:
    from pathlib import Path

    from forkhub.database import Database


runner = CliRunner()


# ---------------------------------------------------------------------------
# notifications/console.py
# ---------------------------------------------------------------------------


class TestConsoleBackend:
    async def test_deliver_returns_success_result(self):
        """ConsoleBackend.deliver should render the digest and report success."""
        from rich.console import Console

        from forkhub.notifications.console import ConsoleBackend

        stream = StringIO()
        console = Console(file=stream, force_terminal=True, width=80)
        backend = ConsoleBackend(console=console)

        digest = Digest(
            config_id="cfg-1",
            title="Test Digest",
            body="Body content",
            signal_ids=["sig-1", "sig-2"],
        )

        result = await backend.deliver(digest)

        assert isinstance(result, DeliveryResult)
        assert result.success is True
        assert backend.backend_name() == "console"
        # Rendered output should contain the title text
        assert "Test Digest" in stream.getvalue()

    def test_default_console_is_constructed(self):
        """Constructing ConsoleBackend without a console must not error."""
        from forkhub.notifications.console import ConsoleBackend

        backend = ConsoleBackend()
        assert backend.backend_name() == "console"


# ---------------------------------------------------------------------------
# cli/formatting.py — render_digest
# ---------------------------------------------------------------------------


class TestRenderDigest:
    def test_renders_title_body_and_count(self):
        from rich.console import Console

        from forkhub.cli.formatting import render_digest

        digest = Digest(
            config_id="cfg-1",
            title="Weekly Update",
            body="Several forks contributed.",
            signal_ids=["s1", "s2", "s3"],
        )

        stream = StringIO()
        console = Console(file=stream, force_terminal=True, width=80)
        render_digest(console, digest)

        rendered = stream.getvalue()
        assert "Weekly Update" in rendered
        assert "Several forks contributed" in rendered
        assert "3 signal" in rendered


# ---------------------------------------------------------------------------
# cli/app.py — `--version` and no-subcommand help
# ---------------------------------------------------------------------------


class TestAppRoot:
    def test_invoke_without_subcommand_prints_help(self):
        """Running the root app with no subcommand should print help and exit 0."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "Monitor GitHub fork constellations" in result.output


# ---------------------------------------------------------------------------
# agent/agents.py
# ---------------------------------------------------------------------------


class TestAgentSubagents:
    @pytest.mark.parametrize(
        ("model", "digest_model", "expected_analyst", "expected_writer", "warning_fragment"),
        [
            # Non-default aliases prove config propagates (fails if literals return)
            pytest.param("opus", "sonnet", "opus", "sonnet", None, id="valid-aliases-propagate"),
            # Full model IDs are valid for the coordinator but not subagents:
            # they degrade to 'inherit' with a warning
            pytest.param(
                "claude-sonnet-4-6",
                "haiku",
                "inherit",
                "haiku",
                "claude-sonnet-4-6",
                id="invalid-alias-falls-back-to-inherit",
            ),
        ],
    )
    def test_build_subagents_models_come_from_settings(
        self, caplog, model, digest_model, expected_analyst, expected_writer, warning_fragment
    ):
        """_build_subagents should propagate configured models, not hardcode literals."""
        pytest.importorskip("claude_agent_sdk")

        from forkhub.agent.agents import _build_subagents
        from forkhub.config import AnthropicSettings, ForkHubSettings

        settings = ForkHubSettings(
            anthropic=AnthropicSettings(model=model, digest_model=digest_model)
        )
        with caplog.at_level("WARNING", logger="forkhub.agent.agents"):
            diff_analyst, digest_writer = _build_subagents(settings)

        assert getattr(diff_analyst, "model", None) == expected_analyst
        assert getattr(digest_writer, "model", None) == expected_writer
        if warning_fragment is None:
            # Valid aliases must pass through silently — pristine log
            assert caplog.text == ""
        else:
            assert warning_fragment in caplog.text
            assert "inherit" in caplog.text


# ---------------------------------------------------------------------------
# agent/hooks.py — uncovered branches: rate-limit block + pre_compact
# ---------------------------------------------------------------------------


def _pre_tool_use_input(tool_name: str) -> dict:
    return {
        "session_id": "s",
        "tool_name": tool_name,
        "tool_input": {},
        "tool_use_id": "t1",
        "hook_event_name": "PreToolUse",
    }


class TestRateLimitGuardBlocks:
    async def test_blocks_when_remaining_is_low(self):
        """When fewer than 100 requests remain, the guard must block the tool."""
        from forkhub.agent.hooks import create_rate_limit_guard_hook

        provider = StubGitProvider(rate_limit_remaining=10)
        hook = create_rate_limit_guard_hook(provider)

        result = await hook(_pre_tool_use_input("mcp__forkhub__list_forks"), None, {})
        assert result.get("decision") == "block"
        assert "Rate limit low" in result.get("reason", "")

    async def test_passes_through_for_non_github_tools(self):
        """Non-GitHub tools should not trigger a rate-limit check or block."""
        from forkhub.agent.hooks import create_rate_limit_guard_hook

        provider = StubGitProvider(rate_limit_remaining=0)
        hook = create_rate_limit_guard_hook(provider)
        result = await hook(_pre_tool_use_input("mcp__forkhub__store_signal"), None, {})
        assert result == {}


class TestPreCompactHook:
    async def test_pre_compact_returns_empty(self):
        """create_pre_compact_hook returns a callable that returns {}."""
        from forkhub.agent.hooks import create_pre_compact_hook

        hook = create_pre_compact_hook()
        result = await hook(
            {
                "session_id": "s",
                "hook_event_name": "PreCompact",
            },
            None,
            {},
        )
        assert result == {}


# ---------------------------------------------------------------------------
# services/cluster.py — small uncovered branches
# ---------------------------------------------------------------------------


class TestClusterEdgeCases:
    async def test_get_clusters_filters_by_min_size(self, db: Database):
        """get_clusters should drop clusters below min_size."""
        from forkhub.services.cluster import ClusterService

        from .stubs import StubEmbeddingProvider, make_cluster

        repo = make_tracked_repo()
        await db.insert_tracked_repo(repo)

        small = make_cluster(repo["id"], fork_count=1)
        big = make_cluster(repo["id"], fork_count=4)
        await db.insert_cluster(small)
        await db.insert_cluster(big)

        svc = ClusterService(db, StubEmbeddingProvider())
        result = await svc.get_clusters(repo["id"], min_size=3)
        assert len(result) == 1
        assert result[0].fork_count == 4

    async def test_update_clusters_returns_empty_with_only_one_signal(self, db: Database):
        """If only a single embedded signal exists, no clusters can form."""
        from forkhub.services.cluster import ClusterService

        from .stubs import StubEmbeddingProvider

        repo = make_tracked_repo()
        await db.insert_tracked_repo(repo)
        fork = make_fork(repo["id"])
        await db.insert_fork(fork)
        sig = make_signal(fork["id"], repo["id"], summary="lonely change")
        await db.insert_signal(sig)

        svc = ClusterService(db, StubEmbeddingProvider())
        clusters = await svc.update_clusters(repo["id"])
        assert clusters == []

    def test_should_cluster_rejects_when_distance_above_threshold(self, db: Database):
        """_should_cluster returns False once distance >= threshold."""
        from forkhub.services.cluster import ClusterService

        from .stubs import StubEmbeddingProvider

        svc = ClusterService(db, StubEmbeddingProvider())
        a = {"fork_id": "f1", "files_involved": '["a.py"]'}
        b = {"fork_id": "f2", "files_involved": '["a.py"]'}
        # distance equal to threshold should return False (>=)
        assert svc._should_cluster(a, b, distance=0.5, threshold=0.3) is False

    def test_should_cluster_directory_overlap_only(self, db: Database):
        """_should_cluster falls back to directory-level overlap when no shared files."""
        from forkhub.services.cluster import ClusterService

        from .stubs import StubEmbeddingProvider

        svc = ClusterService(db, StubEmbeddingProvider())
        a = {"fork_id": "f1", "files_involved": ["src/a.py"]}
        b = {"fork_id": "f2", "files_involved": ["src/b.py"]}
        assert svc._should_cluster(a, b, distance=0.0) is True

    def test_should_cluster_returns_false_for_disjoint_directories(self, db: Database):
        from forkhub.services.cluster import ClusterService

        from .stubs import StubEmbeddingProvider

        svc = ClusterService(db, StubEmbeddingProvider())
        a = {"fork_id": "f1", "files_involved": ["src/a.py"]}
        b = {"fork_id": "f2", "files_involved": ["docs/b.md"]}
        assert svc._should_cluster(a, b, distance=0.0) is False

    def test_generate_label_falls_back_when_no_files(self, db: Database):
        """When signals carry no files, the label uses just the category."""
        from forkhub.services.cluster import ClusterService

        from .stubs import StubEmbeddingProvider

        svc = ClusterService(db, StubEmbeddingProvider())
        signals = [
            {"category": "fix", "files_involved": []},
            {"category": "fix", "files_involved": []},
        ]
        label = svc._generate_cluster_label(signals)
        assert label == "fix changes"

    def test_cosine_distance_zero_vector_returns_one(self, db: Database):
        from forkhub.services.cluster import ClusterService

        from .stubs import StubEmbeddingProvider

        svc = ClusterService(db, StubEmbeddingProvider())
        assert svc._cosine_distance([0.0, 0.0], [1.0, 1.0]) == 1.0
        assert svc._cosine_distance([1.0, 1.0], [0.0, 0.0]) == 1.0


# ---------------------------------------------------------------------------
# services/tracker.py — last uncovered statement
# ---------------------------------------------------------------------------


class TestTrackerSkipsForks:
    async def test_discover_owned_repos_skips_forks_and_existing(self, db: Database):
        """Forks must be skipped and already-tracked repos must be skipped (line 43)."""
        from forkhub.models import RepoInfo
        from forkhub.services.tracker import TrackerService

        repo = RepoInfo(
            github_id=1,
            owner="alice",
            name="own",
            full_name="alice/own",
            default_branch="main",
            description="A repo",
            is_fork=False,
            stars=0,
            forks_count=0,
        )
        forked = RepoInfo(
            github_id=2,
            owner="alice",
            name="fork-of-other",
            full_name="alice/fork-of-other",
            default_branch="main",
            description="A fork",
            is_fork=True,
            stars=0,
            forks_count=0,
        )
        existing = RepoInfo(
            github_id=3,
            owner="alice",
            name="existing",
            full_name="alice/existing",
            default_branch="main",
            description="Already tracked",
            is_fork=False,
            stars=0,
            forks_count=0,
        )
        # Pre-insert the "existing" repo so the second iteration's
        # `if existing is not None: continue` branch runs.
        await db.insert_tracked_repo(make_tracked_repo(full_name="alice/existing", github_id=3))

        provider = StubGitProvider(user_repos={"alice": [repo, forked, existing]})
        tracker = TrackerService(db=db, provider=provider)
        owned = await tracker.discover_owned_repos("alice")

        # Only the new, non-fork, not-already-tracked repo is returned.
        assert [r.full_name for r in owned] == ["alice/own"]


# ---------------------------------------------------------------------------
# embeddings/local.py
# ---------------------------------------------------------------------------


class TestLocalEmbeddingProvider:
    def test_dimensions_constant(self):
        """dimensions() should report 384 for the default model."""
        from forkhub.embeddings.local import LocalEmbeddingProvider

        assert LocalEmbeddingProvider().dimensions() == 384

    async def test_embed_lazy_loads_model_via_executor(self, monkeypatch: pytest.MonkeyPatch):
        """embed() should lazy-load the model via SentenceTransformer and call encode."""
        import sys
        import types

        from forkhub.embeddings.local import LocalEmbeddingProvider

        class FakeArr:
            def __init__(self, values: list[float]):
                self._values = values

            def tolist(self) -> list[float]:
                return self._values

        class FakeModel:
            def __init__(self, model_name: str) -> None:
                self.model_name = model_name
                self.calls: list[list[str]] = []

            def encode(self, texts: list[str]):
                self.calls.append(list(texts))
                return [FakeArr([float(len(t))]) for t in texts]

        # Inject a fake `sentence_transformers` module so the import inside
        # `_load_model` resolves to FakeModel without downloading anything.
        fake_module = types.ModuleType("sentence_transformers")
        fake_module.SentenceTransformer = FakeModel
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        provider = LocalEmbeddingProvider(model_name="fake-model")
        out = await provider.embed(["hi", "there"])
        assert out == [[2.0], [5.0]]
        assert isinstance(provider._model, FakeModel)
        assert provider._model.model_name == "fake-model"


# ---------------------------------------------------------------------------
# cli/helpers.py — async_command wrapper
# ---------------------------------------------------------------------------


class TestAsyncCommandWrapper:
    def test_async_command_runs_coroutine(self):
        """async_command should invoke the wrapped coroutine via asyncio.run."""
        from forkhub.cli.helpers import async_command

        calls: list[int] = []

        @async_command
        async def trivial(value: int) -> int:
            calls.append(value)
            return value * 2

        result = trivial(21)
        assert result == 42
        assert calls == [21]


# ---------------------------------------------------------------------------
# CLI: shared monkeypatch helper for get_services
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_get_services(monkeypatch: pytest.MonkeyPatch, db: Database):
    """Patch get_services across CLI modules to return our in-memory db + stub provider."""
    provider = StubGitProvider.with_testuser_data()
    from forkhub.config import ForkHubSettings

    settings = ForkHubSettings()

    async def fake_get_services(settings_arg=None):
        return settings, db, provider

    # Patch in all CLI modules that import get_services
    import forkhub.cli.helpers as helpers_mod

    monkeypatch.setattr(helpers_mod, "get_services", fake_get_services)
    return provider, settings


# ---------------------------------------------------------------------------
# cli/clusters_cmd.py — db is None branch + console output branch
# ---------------------------------------------------------------------------


class TestClustersCmd:
    async def test_db_is_none_uses_get_services(self, patched_get_services, db: Database):
        """_clusters_impl with db=None must use get_services + close db on exit."""
        from forkhub.cli.clusters_cmd import _clusters_impl

        # Track the repo so the lookup succeeds (even though no clusters exist).
        provider, _ = patched_get_services
        repo = make_tracked_repo(full_name="testuser/alpha", github_id=42, tracking_mode="watched")
        await db.insert_tracked_repo(repo)

        output: list[str] = []
        await _clusters_impl(repo="testuser/alpha", db=None, capture_output=output)
        assert any("No clusters" in line for line in output)

    async def test_console_output_path_with_clusters(self, db: Database):
        """When capture_output is None, render_cluster runs (covers else branch)."""
        from forkhub.cli.clusters_cmd import _clusters_impl

        from .stubs import make_cluster

        repo = make_tracked_repo(full_name="testuser/alpha", github_id=11)
        await db.insert_tracked_repo(repo)
        cluster = make_cluster(repo["id"], fork_count=3)
        await db.insert_cluster(cluster)

        # Run with no capture; output goes to console.print (the rendering path).
        await _clusters_impl(repo="testuser/alpha", db=db, capture_output=None)

    async def test_clusters_repo_not_found(self, db: Database):
        """Untracked repo should print an error and return."""
        from forkhub.cli.clusters_cmd import _clusters_impl

        output: list[str] = []
        await _clusters_impl(repo="nobody/zzz", db=db, capture_output=output)
        assert any("not found" in line.lower() or "not tracked" in line.lower() for line in output)

    def test_clusters_command_wrapper(self, monkeypatch: pytest.MonkeyPatch, db: Database):
        """Invoke the @async_command-wrapped clusters_command via CliRunner."""
        from forkhub.cli import clusters_cmd

        async def fake_impl(**_kwargs):
            return None

        monkeypatch.setattr(clusters_cmd, "_clusters_impl", fake_impl)
        result = runner.invoke(app, ["clusters", "owner/repo"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# cli/config_cmd.py — `_output` console branch + wrappers
# ---------------------------------------------------------------------------


class TestConfigCmdGaps:
    async def test_config_show_writes_to_console(self):
        """Calling _config_show_impl without capture_output exercises console.print."""
        from forkhub.cli.config_cmd import _config_show_impl

        await _config_show_impl(config_path=None)

    async def test_config_show_oauth_branch(self, tmp_path: Path):
        """When auth_method='oauth', the OAuth display branch runs."""
        from forkhub.cli.config_cmd import _config_show_impl

        cfg = tmp_path / "forkhub.toml"
        cfg.write_text(
            '[github]\ntoken = "ghp_xyz"\nusername = "u"\n'
            '[anthropic]\noauth_token = "oat_abc12345xyz"\n'
        )
        out: list[str] = []
        await _config_show_impl(config_path=cfg, capture_output=out)
        joined = "\n".join(out)
        assert "OAuth" in joined

    async def test_config_show_no_auth_branch(self, tmp_path: Path):
        """When neither api_key nor oauth_token is set, the not-configured branch runs."""
        from forkhub.cli.config_cmd import _config_show_impl

        cfg = tmp_path / "forkhub.toml"
        cfg.write_text('[github]\ntoken = "ghp_xyz"\nusername = "u"\n')
        out: list[str] = []
        await _config_show_impl(config_path=cfg, capture_output=out)
        joined = "\n".join(out)
        assert "not configured" in joined

    async def test_config_show_api_key_branch(self, tmp_path: Path):
        """When auth_method='api_key', the API-key display branch runs."""
        from forkhub.cli.config_cmd import _config_show_impl

        cfg = tmp_path / "forkhub.toml"
        cfg.write_text(
            '[github]\ntoken = "ghp_xyz"\nusername = "u"\n'
            '[anthropic]\napi_key = "sk-ant-1234567890"\n'
        )
        out: list[str] = []
        await _config_show_impl(config_path=cfg, capture_output=out)
        joined = "\n".join(out)
        assert "API key" in joined

    async def test_config_path_exists_branch(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """When the config file exists, the (exists) branch runs (line 104)."""
        from forkhub import config as config_mod
        from forkhub.cli.config_cmd import _config_path_impl

        (tmp_path / "forkhub.toml").write_text('[github]\ntoken="x"\nusername="u"\n')
        monkeypatch.setattr(config_mod, "get_config_dir", lambda: tmp_path)

        out: list[str] = []
        await _config_path_impl(capture_output=out)
        assert any("(exists)" in line for line in out)

    async def test_config_path_writes_to_console(self):
        """Calling _config_path_impl without capture exercises the console print branch."""
        from forkhub.cli.config_cmd import _config_path_impl

        await _config_path_impl()

    def test_config_show_and_path_command_wrappers(self):
        """The @config_app.command-wrapped commands should run end-to-end via CliRunner."""
        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        result = runner.invoke(app, ["config", "path"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# cli/digest_cmd.py — get_services branch, invalid date, deliver branch, console
# ---------------------------------------------------------------------------


class TestDigestCmdGaps:
    async def test_invalid_since_date_returns_error(self, db: Database):
        from forkhub.cli.digest_cmd import _digest_impl

        out: list[str] = []
        await _digest_impl(since="not-a-date", db=db, capture_output=out)
        assert any("Invalid date" in line for line in out)

    async def test_db_none_branch_and_console(self, patched_get_services, db: Database):
        from forkhub.cli.digest_cmd import _digest_impl

        # No capture_output -> exercises console.print branch (line 26)
        await _digest_impl(since=None, dry_run=True, db=None, capture_output=None)

    async def test_deliver_branch_with_console_backend(self, db: Database):
        """Non-dry-run path delivers via the ConsoleBackend (exercises lines 77-85)."""
        from forkhub.cli.digest_cmd import _digest_impl

        out: list[str] = []
        await _digest_impl(since=None, dry_run=False, db=db, capture_output=out)
        joined = "\n".join(out)
        assert "Digest delivered" in joined
        assert "console" in joined

    def test_digest_command_wrapper(self, monkeypatch: pytest.MonkeyPatch):
        from forkhub.cli import digest_cmd

        async def fake_impl(**_kwargs):
            return None

        monkeypatch.setattr(digest_cmd, "_digest_impl", fake_impl)
        result = runner.invoke(app, ["digest", "--dry-run"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# cli/forks_cmd.py — sort branches, console branch, get_services, command wrappers
# ---------------------------------------------------------------------------


class TestForksCmdGaps:
    async def test_forks_sort_recent_and_ahead(self, db: Database):
        """Sort by recent and by ahead exercise the alternative sort branches."""
        from forkhub.cli.forks_cmd import _forks_impl

        repo = make_tracked_repo(full_name="testuser/alpha", github_id=42, tracking_mode="watched")
        await db.insert_tracked_repo(repo)

        for i in range(2):
            f = make_fork(
                repo["id"],
                github_id=600 + i,
                full_name=f"contributor{i}/alpha",
                last_pushed_at=f"2025-0{i + 1}-01T00:00:00+00:00",
                commits_ahead=i,
            )
            await db.insert_fork(f)

        out: list[str] = []
        await _forks_impl(repo="testuser/alpha", sort="recent", db=db, capture_output=out)
        out2: list[str] = []
        await _forks_impl(repo="testuser/alpha", sort="ahead", db=db, capture_output=out2)
        assert any("contributor" in line for line in out)
        assert any("contributor" in line for line in out2)

    async def test_forks_no_results_message(self, db: Database):
        from forkhub.cli.forks_cmd import _forks_impl

        repo = make_tracked_repo(full_name="testuser/alpha", github_id=44)
        await db.insert_tracked_repo(repo)

        out: list[str] = []
        await _forks_impl(repo="testuser/alpha", db=db, capture_output=out)
        assert any("No forks" in line for line in out)

    async def test_forks_console_branch(self, db: Database):
        """Without capture_output, render_fork_table runs (else branch)."""
        from forkhub.cli.forks_cmd import _forks_impl

        repo = make_tracked_repo(full_name="testuser/alpha", github_id=45)
        await db.insert_tracked_repo(repo)
        await db.insert_fork(make_fork(repo["id"]))

        await _forks_impl(repo="testuser/alpha", db=db, capture_output=None)

    async def test_forks_db_none_uses_get_services(self, patched_get_services, db: Database):
        from forkhub.cli.forks_cmd import _forks_impl

        repo = make_tracked_repo(full_name="testuser/alpha", github_id=46)
        await db.insert_tracked_repo(repo)
        # No capture_output and db=None -> exercises the get_services branch.
        await _forks_impl(repo="testuser/alpha", db=None, capture_output=None)

    async def test_inspect_console_branch(self, db: Database):
        """inspect_impl with no capture exercises render_signal else branch."""
        from forkhub.cli.forks_cmd import _inspect_impl

        repo = make_tracked_repo(full_name="testuser/alpha", github_id=47)
        await db.insert_tracked_repo(repo)
        fork = make_fork(repo["id"], full_name="bob/alpha")
        await db.insert_fork(fork)
        sig = make_signal(fork["id"], repo["id"], summary="cool")
        await db.insert_signal(sig)

        await _inspect_impl(fork_name="bob/alpha", db=db, capture_output=None)

    async def test_inspect_db_none_uses_get_services(self, patched_get_services, db: Database):
        from forkhub.cli.forks_cmd import _inspect_impl

        repo = make_tracked_repo(full_name="testuser/alpha", github_id=48)
        await db.insert_tracked_repo(repo)
        fork = make_fork(repo["id"], full_name="bob/alpha")
        await db.insert_fork(fork)

        # No signals -> "No signals recorded" branch
        out: list[str] = []
        await _inspect_impl(fork_name="bob/alpha", db=None, capture_output=out)
        assert any("No signals" in line for line in out)

    def test_forks_and_inspect_command_wrappers(self, monkeypatch: pytest.MonkeyPatch):
        from forkhub.cli import forks_cmd

        async def fake(**_kwargs):
            return None

        monkeypatch.setattr(forks_cmd, "_forks_impl", fake)
        monkeypatch.setattr(forks_cmd, "_inspect_impl", fake)
        assert runner.invoke(app, ["forks", "owner/repo"]).exit_code == 0
        assert runner.invoke(app, ["inspect", "fork/name"]).exit_code == 0


# ---------------------------------------------------------------------------
# cli/init_cmd.py — config_dir default branch, owns_db cleanup, command wrapper
# ---------------------------------------------------------------------------


class TestInitCmdGaps:
    async def test_owns_db_creates_and_closes_db(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """When db is None, init creates and closes its own DB."""
        import forkhub.cli.init_cmd as init_mod
        from forkhub.config import ForkHubSettings

        # Patch load_settings + DatabaseImpl + get_db_path so we don't touch the user's home dir.
        from forkhub.database import Database

        settings = ForkHubSettings()
        monkeypatch.setattr(
            "forkhub.cli.init_cmd.console", init_mod.console
        )  # no-op; ensures the import runs

        captured: list[Database] = []

        # Use an in-memory database for the connection
        class TrackedDatabase(Database):
            async def close(self) -> None:  # type: ignore[override]
                captured.append(self)
                await Database.close(self)

        # Patch resolution path so the init impl uses TrackedDatabase + tmp settings
        from forkhub import config as config_mod

        monkeypatch.setattr(config_mod, "load_settings", lambda *_args, **_kw: settings)
        monkeypatch.setattr(config_mod, "get_db_path", lambda *_args, **_kw: ":memory:")
        monkeypatch.setattr("forkhub.cli.init_cmd.console", init_mod.console)

        # Patch the DatabaseImpl symbol used inside _init_impl
        import forkhub.database as db_mod

        monkeypatch.setattr(db_mod, "Database", TrackedDatabase)

        provider = StubGitProvider.with_testuser_data()
        # provider supplied so we bypass the GitHubProvider construction path
        await init_mod._init_impl(
            username="testuser",
            token="ghp_x",
            config_dir=tmp_path,
            db=None,
            provider=provider,
        )

        # Database was constructed and closed by the init impl.
        assert len(captured) == 1

    async def test_default_config_dir(
        self, monkeypatch: pytest.MonkeyPatch, db: Database, tmp_path: Path
    ):
        """When config_dir is None, get_config_dir() supplies the default path."""
        from forkhub import config as config_mod
        from forkhub.cli import init_cmd

        monkeypatch.setattr(config_mod, "get_config_dir", lambda: tmp_path)

        provider = StubGitProvider.with_testuser_data()
        await init_cmd._init_impl(
            username="testuser",
            token="ghp_x",
            config_dir=None,
            db=db,
            provider=provider,
        )
        assert (tmp_path / "forkhub.toml").exists()

    def test_init_command_wrapper(self, monkeypatch: pytest.MonkeyPatch):
        from forkhub.cli import init_cmd

        async def fake(**_kwargs):
            return None

        monkeypatch.setattr(init_cmd, "_init_impl", fake)
        result = runner.invoke(app, ["init", "--user", "x", "--token", "y"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# cli/repos_cmd.py — get_services branch, console output, no-results message,
# CLI wrapper for all four flag branches.
# ---------------------------------------------------------------------------


class TestReposCmdGaps:
    async def test_repos_db_none_uses_get_services(self, patched_get_services, db: Database):
        from forkhub.cli.repos_cmd import _repos_impl

        out: list[str] = []
        await _repos_impl(db=None, provider=None, capture_output=out)
        # No repos in the in-memory DB -> "no tracked" message
        assert any("No tracked" in line for line in out)

    async def test_repos_console_branch(self, db: Database):
        """Without capture_output, render_repo_table runs (else branch)."""
        from forkhub.cli.repos_cmd import _repos_impl

        await db.insert_tracked_repo(
            make_tracked_repo(full_name="x/y", github_id=99, tracking_mode="watched")
        )
        provider = StubGitProvider()
        await _repos_impl(db=db, provider=provider, capture_output=None)

    def test_repos_command_wrapper_all_flag_branches(self, monkeypatch: pytest.MonkeyPatch):
        from forkhub.cli import repos_cmd

        captured: list[dict] = []

        async def fake_impl(**kwargs):
            captured.append(kwargs)

        monkeypatch.setattr(repos_cmd, "_repos_impl", fake_impl)

        for args, _expected_mode in [
            (["--owned"], "owned"),
            (["--watched"], "watched"),
            (["--upstream"], "upstream"),
            (["--inaccessible"], None),
        ]:
            result = runner.invoke(app, ["repos", *args])
            assert result.exit_code == 0, result.output

        # We invoked four times; verify the expected modes were forwarded.
        modes = [c["mode"] for c in captured]
        assert modes == ["owned", "watched", "upstream", None]
        # The --inaccessible branch sets sync_status="inaccessible"
        assert captured[-1]["sync_status"] == "inaccessible"


# ---------------------------------------------------------------------------
# cli/sync_cmd.py — get_services branch, console branch, all repos sync, errors
# ---------------------------------------------------------------------------


class TestSyncCmdGaps:
    async def test_sync_all_repos_path(self, db: Database):
        """Without --repo, the sync_all path runs and prints summary."""
        from forkhub.cli.sync_cmd import _sync_impl
        from forkhub.config import SyncSettings

        await db.insert_tracked_repo(make_tracked_repo(full_name="x/y", github_id=11))
        provider = StubGitProvider()

        out: list[str] = []
        await _sync_impl(
            repo=None,
            db=db,
            provider=provider,
            sync_settings=SyncSettings(),
            capture_output=out,
            auto_analyze=False,
        )
        joined = "\n".join(out)
        assert "Repos synced" in joined

    async def test_sync_all_console_branch(self, db: Database):
        """Without capture_output, output goes to console.print."""
        from forkhub.cli.sync_cmd import _sync_impl
        from forkhub.config import SyncSettings

        await db.insert_tracked_repo(make_tracked_repo(full_name="x/y", github_id=12))
        provider = StubGitProvider()
        await _sync_impl(
            repo=None,
            db=db,
            provider=provider,
            sync_settings=SyncSettings(),
            capture_output=None,
            auto_analyze=False,
        )

    async def test_sync_db_none_uses_get_services(self, patched_get_services, db: Database):
        """sync with db/provider None must fall through to get_services."""
        from forkhub.cli.sync_cmd import _sync_impl

        out: list[str] = []
        await _sync_impl(
            repo=None,
            db=None,
            provider=None,
            sync_settings=None,
            capture_output=out,
            auto_analyze=False,
        )

    async def test_sync_with_analyzer_on_changed_fork(self, db: Database):
        """sync_repo with an analyzer + signals path covers the analyzer-summary line."""
        from forkhub.cli.sync_cmd import _sync_impl
        from forkhub.config import SyncSettings

        from .stubs import StubAnalyzer

        repo_dict = make_tracked_repo(full_name="testuser/alpha", github_id=22)
        await db.insert_tracked_repo(repo_dict)

        signal = Signal(
            tracked_repo_id=repo_dict["id"],
            fork_id="some-id",
            category=SignalCategory.FEATURE,
            summary="x",
            significance=5,
            files_involved=[],
        )
        analyzer = StubAnalyzer(signals=[signal])

        out: list[str] = []
        await _sync_impl(
            repo="testuser/alpha",
            db=db,
            provider=StubGitProvider.with_testuser_data(),
            sync_settings=SyncSettings(),
            capture_output=out,
            auto_analyze=False,
            analyzer=analyzer,
        )
        joined = "\n".join(out)
        # When an analyzer is set, the summary line uses the count, not "skipped"
        assert "New signals: 0" in joined or "New signals:" in joined

    def test_sync_command_wrapper(self, monkeypatch: pytest.MonkeyPatch):
        from forkhub.cli import sync_cmd

        async def fake(**_kwargs):
            return None

        monkeypatch.setattr(sync_cmd, "_sync_impl", fake)
        assert runner.invoke(app, ["sync"]).exit_code == 0


# ---------------------------------------------------------------------------
# cli/track_cmd.py — invalid format, get_services branches, command wrappers,
# console output branches.
# ---------------------------------------------------------------------------


class TestTrackCmdGaps:
    async def test_track_invalid_format(self, db: Database):
        from forkhub.cli.track_cmd import _track_impl

        out: list[str] = []
        await _track_impl(
            repo="invalid-no-slash",
            db=db,
            provider=StubGitProvider(),
            capture_output=out,
        )
        assert any("Invalid repo format" in line for line in out)

    async def test_track_db_none_uses_get_services(self, patched_get_services, db: Database):
        from forkhub.cli.track_cmd import _track_impl

        out: list[str] = []
        await _track_impl(repo="testuser/alpha", db=None, provider=None, capture_output=out)

    async def test_untrack_invalid_format(self, db: Database):
        from forkhub.cli.track_cmd import _untrack_impl

        out: list[str] = []
        await _untrack_impl(repo="bad", db=db, capture_output=out)
        assert any("Invalid repo format" in line for line in out)

    async def test_untrack_db_none_uses_get_services(self, patched_get_services, db: Database):
        from forkhub.cli.track_cmd import _untrack_impl

        await db.insert_tracked_repo(make_tracked_repo(full_name="x/y", github_id=999))
        out: list[str] = []
        await _untrack_impl(repo="x/y", db=None, capture_output=out)

    async def test_exclude_db_none_uses_get_services(self, patched_get_services, db: Database):
        from forkhub.cli.track_cmd import _exclude_impl

        await db.insert_tracked_repo(make_tracked_repo(full_name="x/y", github_id=998))
        out: list[str] = []
        await _exclude_impl(repo="x/y", db=None, capture_output=out)

    async def test_include_db_none_uses_get_services(self, patched_get_services, db: Database):
        from forkhub.cli.track_cmd import _include_impl

        await db.insert_tracked_repo(make_tracked_repo(full_name="x/y", github_id=997))
        out: list[str] = []
        await _include_impl(repo="x/y", db=None, capture_output=out)

    def test_track_command_wrappers(self, monkeypatch: pytest.MonkeyPatch):
        from forkhub.cli import track_cmd

        async def fake(**_kwargs):
            return None

        monkeypatch.setattr(track_cmd, "_track_impl", fake)
        monkeypatch.setattr(track_cmd, "_untrack_impl", fake)
        monkeypatch.setattr(track_cmd, "_exclude_impl", fake)
        monkeypatch.setattr(track_cmd, "_include_impl", fake)
        assert runner.invoke(app, ["track", "owner/repo"]).exit_code == 0
        assert runner.invoke(app, ["untrack", "owner/repo"]).exit_code == 0
        assert runner.invoke(app, ["exclude", "owner/repo"]).exit_code == 0
        assert runner.invoke(app, ["include", "owner/repo"]).exit_code == 0


# ---------------------------------------------------------------------------
# Final cleanup tests for stragglers
# ---------------------------------------------------------------------------


class TestFinalCLIGaps:
    async def test_clusters_no_capture_no_results(self, db: Database):
        """capture_output=None with no clusters exercises console.print of `_output` (line 26)."""
        from forkhub.cli.clusters_cmd import _clusters_impl

        repo = make_tracked_repo(full_name="testuser/alpha", github_id=701)
        await db.insert_tracked_repo(repo)
        await _clusters_impl(repo="testuser/alpha", db=db, capture_output=None)

    async def test_repos_no_capture_no_results(self, db: Database):
        """capture_output=None with no tracked repos exercises console.print branch."""
        from forkhub.cli.repos_cmd import _repos_impl

        provider = StubGitProvider()
        await _repos_impl(db=db, provider=provider, capture_output=None)

    async def test_repos_capture_with_repos_iterates(self, db: Database):
        """capture_output=[] with a tracked repo runs the iteration branch (lines 60-69)."""
        from forkhub.cli.repos_cmd import _repos_impl

        await db.insert_tracked_repo(
            make_tracked_repo(
                full_name="x/y",
                github_id=702,
                tracking_mode="watched",
                last_synced_at=datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC).isoformat(),
            )
        )
        out: list[str] = []
        await _repos_impl(db=db, provider=StubGitProvider(), capture_output=out)
        joined = "\n".join(out)
        assert "x/y" in joined

    async def test_init_creates_default_provider(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, db: Database
    ):
        """When provider is None, init constructs a GitHubProvider (line 79)."""
        from forkhub.cli.init_cmd import _init_impl
        from forkhub.providers import github as gh_mod

        constructed: list[str] = []

        class FakeGH:
            def __init__(self, token: str) -> None:
                constructed.append(token)

            async def get_user_repos(self, username: str):
                return []

        monkeypatch.setattr(gh_mod, "GitHubProvider", FakeGH)

        await _init_impl(
            username="u",
            token="ghp_x",
            config_dir=tmp_path,
            db=db,
            provider=None,
        )
        assert constructed == ["ghp_x"]

    async def test_digest_failed_delivery_branch(
        self, monkeypatch: pytest.MonkeyPatch, db: Database
    ):
        """Failed delivery prints FAILED status (line 84)."""
        from forkhub.cli import digest_cmd
        from forkhub.notifications import console as console_module

        # Inject a backend that always reports failure.
        from .stubs import StubNotificationBackend

        failing = StubNotificationBackend(name="console", should_fail=True)

        # ConsoleBackend is imported inside _digest_impl from
        # forkhub.notifications.console, so patch the source attribute.
        monkeypatch.setattr(console_module, "ConsoleBackend", lambda *_a, **_kw: failing)

        out: list[str] = []
        await digest_cmd._digest_impl(since=None, dry_run=False, db=db, capture_output=out)
        joined = "\n".join(out)
        assert "FAILED" in joined

    async def test_sync_settings_default_when_none_for_passed_db(self, db: Database):
        """sync_settings=None with db provided exercises line 57 (SyncSettingsImpl())."""
        from forkhub.cli.sync_cmd import _sync_impl

        provider = StubGitProvider()
        out: list[str] = []
        await _sync_impl(
            repo=None,
            db=db,
            provider=provider,
            sync_settings=None,
            capture_output=out,
            auto_analyze=False,
        )

    async def test_sync_skipped_analyzer_message(
        self, monkeypatch: pytest.MonkeyPatch, db: Database
    ):
        """When auto_analyze=True but the factory returns None, the skip message fires."""
        import forkhub
        import forkhub.cli.sync_cmd as sync_mod
        from forkhub.config import SyncSettings

        # _build_default_analyzer is imported inside _sync_impl from `forkhub`,
        # so patch the source attribute.
        monkeypatch.setattr(forkhub, "_build_default_analyzer", lambda **_kw: None)

        provider = StubGitProvider()
        out: list[str] = []
        await sync_mod._sync_impl(
            repo=None,
            db=db,
            provider=provider,
            sync_settings=SyncSettings(),
            capture_output=out,
            auto_analyze=True,
        )
        joined = "\n".join(out)
        assert "Analyzer skipped" in joined

    async def test_sync_repo_warnings_and_changed_branches(self, db: Database):
        """Single-repo sync with errors + changed forks exercises lines 102-104, 107-109."""
        from forkhub.cli.sync_cmd import _sync_impl
        from forkhub.config import SyncSettings
        from forkhub.services.sync import RepoSyncResult, SyncService

        repo_dict = make_tracked_repo(
            full_name="testuser/alpha", github_id=801, tracking_mode="watched"
        )
        await db.insert_tracked_repo(repo_dict)

        async def fake_sync_repo(self, repo_id):
            return RepoSyncResult(
                repo_full_name="testuser/alpha",
                new_forks=1,
                changed_forks=["a/x", "b/y"],
                errors=["something failed"],
            )

        original = SyncService.sync_repo
        SyncService.sync_repo = fake_sync_repo  # type: ignore[method-assign]
        try:
            out: list[str] = []
            await _sync_impl(
                repo="testuser/alpha",
                db=db,
                provider=StubGitProvider(),
                sync_settings=SyncSettings(),
                capture_output=out,
                auto_analyze=False,
            )
            joined = "\n".join(out)
            assert "Changed:" in joined
            assert "Warnings:" in joined
        finally:
            SyncService.sync_repo = original  # type: ignore[method-assign]

    async def test_sync_all_with_reconcile_and_per_repo_summary(self, db: Database):
        """sync_all with reconciliation + per-repo summary lines (126-131, 152, 160-162)."""
        from forkhub.cli.sync_cmd import _sync_impl
        from forkhub.config import SyncSettings
        from forkhub.services.sync import (
            ReconcileResult,
            RepoSyncResult,
            SyncResult,
            SyncService,
        )

        await db.insert_tracked_repo(
            make_tracked_repo(full_name="testuser/alpha", github_id=901, tracking_mode="watched")
        )

        async def fake_sync_all(self, **_kw):
            return SyncResult(
                repos_synced=1,
                total_changed_forks=2,
                total_new_releases=1,
                total_signals_generated=0,
                results=[
                    RepoSyncResult(
                        repo_full_name="testuser/alpha",
                        new_forks=2,
                        changed_forks=["a/x"],
                    ),
                ],
                errors=["a global warning"],
                reconcile=ReconcileResult(
                    repos_recovered=["r1"],
                    repos_still_inaccessible=["r2"],
                    new_repos_discovered=["r3"],
                ),
            )

        original = SyncService.sync_all
        SyncService.sync_all = fake_sync_all  # type: ignore[method-assign]
        try:
            out: list[str] = []
            await _sync_impl(
                repo=None,
                db=db,
                provider=StubGitProvider(),
                sync_settings=SyncSettings(),
                capture_output=out,
                auto_analyze=False,
            )
            joined = "\n".join(out)
            assert "Reconciled" in joined
            assert "testuser/alpha" in joined
            assert "Warnings" in joined
        finally:
            SyncService.sync_all = original  # type: ignore[method-assign]

    async def test_sync_username_resolves_from_settings(
        self, monkeypatch: pytest.MonkeyPatch, db: Database
    ):
        """When `username` is None and reconcile is on, the username comes from settings."""
        from forkhub.cli.sync_cmd import _sync_impl
        from forkhub.config import ForkHubSettings, GitHubSettings, SyncSettings
        from forkhub.services.sync import SyncResult, SyncService

        # Build settings that surface a username.
        settings = ForkHubSettings(github=GitHubSettings(username="my-user"))

        observed: dict = {}

        async def fake_sync_all(self, *, username=None, **_kw):
            observed["username"] = username
            return SyncResult()

        original = SyncService.sync_all
        SyncService.sync_all = fake_sync_all  # type: ignore[method-assign]

        async def fake_get_services(_arg=None):
            return settings, db, StubGitProvider()

        import forkhub.cli.helpers as helpers_mod

        monkeypatch.setattr(helpers_mod, "get_services", fake_get_services)

        try:
            await _sync_impl(
                repo=None,
                db=None,
                provider=None,
                sync_settings=SyncSettings(),
                capture_output=[],
                auto_analyze=False,
            )
        finally:
            SyncService.sync_all = original  # type: ignore[method-assign]

        assert observed["username"] == "my-user"
