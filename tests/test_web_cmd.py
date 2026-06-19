# ABOUTME: Tests for the `forkhub web` CLI command.
# ABOUTME: Covers _web_impl directly and the Typer wrapper via CliRunner (uvicorn stubbed).

from __future__ import annotations

from fastapi import FastAPI
from typer.testing import CliRunner

from forkhub.cli.app import app
from forkhub.cli.web_cmd import _web_impl


def test_web_impl_builds_app_and_invokes_runner():
    captured: dict = {}

    def fake_run(app_obj, host, port):
        captured.update(app=app_obj, host=host, port=port)

    _web_impl(host="0.0.0.0", port=9999, run=fake_run)

    assert isinstance(captured["app"], FastAPI)
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9999


def test_web_command_runs_via_cli(monkeypatch):
    calls: dict = {}
    monkeypatch.setattr(
        "uvicorn.run", lambda app_obj, host, port: calls.update(host=host, port=port)
    )

    result = CliRunner().invoke(app, ["web", "--host", "0.0.0.0", "--port", "1234"])

    assert result.exit_code == 0, result.output
    assert calls == {"host": "0.0.0.0", "port": 1234}
