"""Typer-driven CLI for plumb (FR-CLI-1).

Seven subcommands: run stats, score write, example promote, judge run,
serve, attach, version.
"""

from __future__ import annotations

import errno
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, NoReturn

try:
    import typer
except ImportError as _e:
    raise ImportError(
        "plumb CLI requires 'typer' and 'rich'. Install them with: pip install 'plumb[cli]'"
    ) from _e

from plumb._cli_judge import register as _register_judge
from plumb._output import format_output
from plumb._time_utils import parse_since

logger = logging.getLogger(__name__)


class _RealClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


# ---------------------------------------------------------------------------
# App + sub-apps
# ---------------------------------------------------------------------------

app = typer.Typer(name="plumb", no_args_is_help=True)
run_app = typer.Typer(no_args_is_help=True, help="Commands for inspecting runs.")
score_app = typer.Typer(no_args_is_help=True, help="Commands for recording scores.")
example_app = typer.Typer(no_args_is_help=True, help="Commands for managing examples.")
judge_app = typer.Typer(no_args_is_help=True, help="Commands for running judge evaluations.")

app.add_typer(run_app, name="run")
app.add_typer(score_app, name="score")
app.add_typer(example_app, name="example")
app.add_typer(judge_app, name="judge")

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_RUN_STATS_COLUMNS = [
    "run_id",
    "task_id",
    "kind",
    "status",
    "start_ts",
    "duration_ms",
    "span_count",
    "score_count",
]
_VALID_FORMATS = ("table", "json", "csv")


def _get_storage():  # type: ignore[return]
    """Open a SQLiteStorageAdapter against the configured data directory."""
    from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
    from plumb.config import ensure_data_dir, get_settings

    settings = get_settings()
    data_dir = ensure_data_dir(settings)
    db_path = data_dir / "plumb.db"
    return SQLiteStorageAdapter(db_path, clock=_RealClock())


def _die(msg: str) -> NoReturn:
    """Print error to stderr and exit 1."""
    typer.echo(f"Error: {msg}", err=True)
    raise typer.Exit(1)


def _resolve_since(since_str: str | None) -> datetime | None:
    if since_str is None:
        return None
    try:
        return parse_since(since_str)
    except ValueError as exc:
        _die(f"Invalid --since value: {exc}")


def _validate_format(fmt: str) -> str:
    if fmt not in _VALID_FORMATS:
        _die("--format must be table, json, or csv.")
    return fmt


# ---------------------------------------------------------------------------
# plumb run stats
# ---------------------------------------------------------------------------

_SINCE_HELP = "Filter runs newer than this (e.g. 7d, 2w, 2026-01-01)."
_TASK_ID_HELP = "Filter to a specific task_id."
_FORMAT_HELP = "Output format: table, json, or csv."
_LIMIT_HELP = "Maximum number of rows to return."


@run_app.command("stats")
def run_stats(
    since: Annotated[str | None, typer.Option("--since", help=_SINCE_HELP)] = None,
    task_id: Annotated[str | None, typer.Option("--task-id", help=_TASK_ID_HELP)] = None,
    fmt: Annotated[str, typer.Option("--format", help=_FORMAT_HELP)] = "table",
    limit: Annotated[int, typer.Option("--limit", help=_LIMIT_HELP)] = 100,
) -> None:
    """List recent runs with span and score counts.

    Outputs the most recent runs sorted by start time (newest first).
    Defaults to a rich table on TTY; newline-delimited JSON otherwise.
    """
    _validate_format(fmt)
    since_dt = _resolve_since(since)

    try:
        with _get_storage() as storage:
            summaries = storage.list_runs_with_counts(since=since_dt, task_id=task_id, limit=limit)
    except typer.Exit:
        raise
    except Exception as exc:
        _die(str(exc))

    rows = []
    for s in summaries:
        duration_ms: int | None = None
        if s.start_ts and s.end_ts:
            try:
                start = datetime.fromisoformat(s.start_ts)
                end = datetime.fromisoformat(s.end_ts)
                duration_ms = int((end - start).total_seconds() * 1000)
            except (ValueError, TypeError):
                pass
        rows.append(
            {
                "run_id": s.run_id[:8],
                "task_id": s.task_id,
                "kind": s.kind,
                "status": s.status,
                "start_ts": s.start_ts,
                "duration_ms": duration_ms,
                "span_count": s.span_count,
                "score_count": s.score_count,
            }
        )

    format_output(rows, _RUN_STATS_COLUMNS, fmt)


# ---------------------------------------------------------------------------
# plumb score write
# ---------------------------------------------------------------------------

_SCORER_HELP = "Scorer kind: deterministic, judge, human, or user_signal."
_NUMERIC_HELP = "Numeric score value."
_LABEL_HELP = "Label score value."
_SPAN_ID_HELP = "Optional span to attach the score to."
_SCORER_VER_HELP = "Scorer version string."


@score_app.command("write")
def score_write(
    run_id: Annotated[str, typer.Option("--run-id", help="The run to score.")],
    metric: Annotated[str, typer.Option("--metric", help="Metric name.")],
    scorer: Annotated[str, typer.Option("--scorer", help=_SCORER_HELP)],
    value_numeric: Annotated[
        float | None, typer.Option("--value-numeric", help=_NUMERIC_HELP)
    ] = None,
    value_label: Annotated[str | None, typer.Option("--value-label", help=_LABEL_HELP)] = None,
    span_id: Annotated[str | None, typer.Option("--span-id", help=_SPAN_ID_HELP)] = None,
    scorer_version: Annotated[
        str | None, typer.Option("--scorer-version", help=_SCORER_VER_HELP)
    ] = None,
) -> None:
    """Write a score row for an existing run.

    Exactly one of ``--value-numeric`` or ``--value-label`` must be provided.
    If ``--scorer-version`` is omitted it defaults to ``cli-unversioned``.
    """
    from plumb.core.entities import Score, ScorerKind

    # XOR validation (also reject empty string label)
    if value_label is not None and not value_label:
        _die("--value-label must not be empty.")
    numeric_set = value_numeric is not None
    label_set = value_label is not None
    if numeric_set == label_set:
        _die("Exactly one of --value-numeric or --value-label must be provided.")

    # Validate scorer kind
    try:
        scorer_kind = ScorerKind(scorer)
    except ValueError:
        valid = ", ".join(k.value for k in ScorerKind)
        _die(f"Invalid --scorer {scorer!r}. Valid values: {valid}.")

    effective_version = scorer_version or "cli-unversioned"

    try:
        with _get_storage() as storage:
            run = storage.get_run(run_id)
            if run is None:
                _die(f"Run {run_id!r} not found.")

            score_id = uuid.uuid4().hex
            score = Score(
                score_id=score_id,
                run_id=run_id,
                metric_name=metric,
                scorer=scorer_kind,
                scorer_version=effective_version,
                scored_at=datetime.now(UTC),
                span_id=span_id,
                value_numeric=value_numeric,
                value_label=value_label,
            )
            storage.write_score(score)
    except typer.Exit:
        raise
    except Exception as exc:
        _die(str(exc))

    typer.echo(f"Score {score_id[:8]} written for run {run_id[:8]}.")


# ---------------------------------------------------------------------------
# plumb example promote
# ---------------------------------------------------------------------------

_RUBRIC_HELP = "Path to rubric markdown file."


@example_app.command("promote")
def example_promote(
    from_run: Annotated[str, typer.Option("--from-run", help="Run ID to promote to an example.")],
    rubric: Annotated[Path | None, typer.Option("--rubric", exists=True, help=_RUBRIC_HELP)] = None,
) -> None:
    """Promote a production run to the regression example dataset.

    Creates an example row with ``source=production_promotion`` and the
    best available ``inputs_hash`` from the run's spans.
    """
    import hashlib

    from plumb.core.entities import Example, ExampleSource, SpanKind

    rubric_text: str | None = None
    if rubric is not None:
        rubric_text = rubric.read_text(encoding="utf-8")

    try:
        with _get_storage() as storage:
            run = storage.get_run(from_run)
            if run is None:
                _die(f"Run {from_run!r} not found.")

            spans = storage.get_spans_for_run(from_run)

            # Input hash selection per plan §6.4
            llm_spans = [s for s in spans if s.kind == SpanKind.LLM and s.input_hash]
            if llm_spans:
                primary = max(llm_spans, key=lambda s: s.tokens_in or 0)
                inputs_hash_str = primary.input_hash
            elif spans and spans[0].input_hash:
                inputs_hash_str = spans[0].input_hash
            else:
                inputs_hash_str = None

            # DR-5: inputs_hash must be 64-char hex per entity validation. Use a
            # well-known deterministic sentinel for zero-span runs so consumers
            # can recognise it: sha256(b"no_spans") = 94a3...
            inputs_hash_final = (
                inputs_hash_str
                if inputs_hash_str is not None
                else hashlib.sha256(b"no_spans").hexdigest()
            )

            example_id = uuid.uuid4().hex
            example = Example(
                example_id=example_id,
                task_id=run.task_id,
                inputs_hash=inputs_hash_final,
                source=ExampleSource.PRODUCTION_PROMOTION,
                created_at=datetime.now(UTC),
                active=True,
                rubric=rubric_text,
                origin_run_id=from_run,
            )
            storage.write_example(example)
    except typer.Exit:
        raise
    except Exception as exc:
        _die(str(exc))

    typer.echo(f"Promoted run {from_run[:8]} → example {example_id[:8]}.")


# ---------------------------------------------------------------------------
# plumb judge run  (logic lives in plumb/_cli_judge.py per DR-2)
# ---------------------------------------------------------------------------

_register_judge(judge_app, _get_storage, _resolve_since, _die)


# ---------------------------------------------------------------------------
# plumb serve
# ---------------------------------------------------------------------------

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@app.command("serve")
def serve(
    host: Annotated[str, typer.Option("--host", help="Bind host address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Bind port.")] = 8765,
) -> None:
    """Start the plumb read-only HTTP service.

    Binds to ``127.0.0.1:8765`` by default. Passing a non-loopback host
    emits a warning before startup. Ctrl-C exits cleanly with code 0.
    """
    try:
        import uvicorn
    except ImportError as _e:
        _die(
            "plumb serve requires 'fastapi' and 'uvicorn'. "
            "Install them with: pip install 'plumb[http]'"
        )
        raise  # unreachable; satisfies type checker

    if host not in _LOOPBACK:
        logger.warning(
            "plumb serve: binding to non-loopback host %r — reachable on the network.",
            host,
        )

    try:
        uvicorn.run("plumb.http:app", host=host, port=port)
    except KeyboardInterrupt:
        raise typer.Exit(0) from None
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            _die(f"port {port} is already in use.")
        _die(str(exc))


# ---------------------------------------------------------------------------
# plumb attach
# ---------------------------------------------------------------------------

_AS_HELP = "Display alias for the attached database."
_PATH_HELP = "Path to the AgentsView SQLite database."


@app.command("attach")
def attach(
    path: Annotated[
        Path,
        typer.Argument(help=_PATH_HELP, exists=True, file_okay=True, dir_okay=False, readable=True),
    ],
    as_name: Annotated[str | None, typer.Option("--as", help=_AS_HELP)] = None,
) -> None:
    """Backfill plumb data from a legacy AgentsView SQLite database.

    Delegates to ``agentsview_attach.backfill``; the adapter implementation
    lands in a future slice.
    """
    from plumb.adapters.agentsview_attach import backfill
    from plumb.core.errors import StorageError

    try:
        result = backfill(path, alias=as_name)
        typer.echo(str(result))
    except StorageError as exc:
        _die(str(exc))


# ---------------------------------------------------------------------------
# plumb version
# ---------------------------------------------------------------------------


@app.command("version")
def version() -> None:
    """Print the installed plumb version and exit."""
    import plumb

    typer.echo(f"plumb {plumb.__version__}")
