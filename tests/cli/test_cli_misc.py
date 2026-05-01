"""Tests for plumb version, serve, and attach (T1.1, T3.2, T3.3)."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from plumb.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# plumb version
# ---------------------------------------------------------------------------


def test_version_output() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "plumb 0.1.0" in result.output


# ---------------------------------------------------------------------------
# plumb serve
# ---------------------------------------------------------------------------


def test_serve_loopback_no_warning(monkeypatch) -> None:

    warnings = []

    class _CapLogger:
        def warning(self, msg, *args, **kwargs):
            warnings.append(msg % args)

    monkeypatch.setattr("plumb.cli.logger", _CapLogger())

    with patch("uvicorn.run") as mock_run:
        runner.invoke(app, ["serve", "--host", "127.0.0.1", "--port", "9999"])
    assert not any("non-loopback" in w for w in warnings)
    mock_run.assert_called_once()


def test_serve_non_loopback_emits_warning(monkeypatch) -> None:
    warnings = []

    class _CapLogger:
        def warning(self, msg, *args, **kwargs):
            warnings.append(msg % args)

    monkeypatch.setattr("plumb.cli.logger", _CapLogger())

    with patch("uvicorn.run"):
        runner.invoke(app, ["serve", "--host", "0.0.0.0", "--port", "9999"])

    assert any("non-loopback" in w for w in warnings)


def test_serve_called_with_correct_host_port() -> None:
    with patch("uvicorn.run") as mock_run:
        runner.invoke(app, ["serve", "--host", "127.0.0.1", "--port", "8888"])
    mock_run.assert_called_once()
    _, kwargs = mock_run.call_args
    assert kwargs.get("host") == "127.0.0.1"
    assert kwargs.get("port") == 8888


def test_serve_keyboard_interrupt_exits_0() -> None:
    with patch("uvicorn.run", side_effect=KeyboardInterrupt):
        result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0


def test_serve_port_in_use_exits_1() -> None:
    import errno

    with patch("uvicorn.run", side_effect=OSError(errno.EADDRINUSE, "address already in use")):
        result = runner.invoke(app, ["serve", "--port", "8765"])
    assert result.exit_code == 1
    assert "8765" in result.output and "in use" in result.output


# ---------------------------------------------------------------------------
# plumb attach
# ---------------------------------------------------------------------------


def test_attach_delegates_to_backfill(tmp_path) -> None:
    fake_db = tmp_path / "agents.db"
    fake_db.touch()

    _backfill = "plumb.adapters.agentsview_attach.backfill"
    with patch(_backfill, return_value={"imported": 5}) as mock_bf:
        result = runner.invoke(app, ["attach", str(fake_db)])

    mock_bf.assert_called_once()
    assert result.exit_code == 0
    assert "imported" in result.output


def test_attach_nonexistent_path_exits_1(tmp_path) -> None:
    result = runner.invoke(app, ["attach", str(tmp_path / "no_such.db")])
    assert result.exit_code != 0


def test_attach_storage_error_exits_1(tmp_path) -> None:
    from unittest.mock import patch

    from plumb.core.errors import StorageError

    fake_db = tmp_path / "agents.db"
    fake_db.touch()

    with patch(
        "plumb.adapters.agentsview_attach.backfill",
        side_effect=StorageError("corrupt schema"),
    ):
        result = runner.invoke(app, ["attach", str(fake_db)])

    assert result.exit_code == 1
    assert "corrupt schema" in result.output
