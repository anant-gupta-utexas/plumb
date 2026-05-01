"""Typer-driven CLI for plumb (FR-CLI-1).

Seven subcommands: run stats, score write, example promote, judge run,
serve, attach, version.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from plumb._output import format_output
from plumb._time_utils import parse_since

logger = logging.getLogger(__name__)

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

    class _RealClock:
        def now(self) -> datetime:
            return datetime.now(UTC)

    settings = get_settings()
    data_dir = ensure_data_dir(settings)
    db_path = data_dir / "plumb.db"
    return SQLiteStorageAdapter(db_path, clock=_RealClock())


def _die(msg: str) -> None:
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

    # XOR validation
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

            # Sentinel: "no_spans" encoded as a 64-char hex for schema compliance
            if inputs_hash_str is None:
                inputs_hash_final = hashlib.sha256(b"no_spans").hexdigest()
            else:
                inputs_hash_final = inputs_hash_str

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
    except Exception as exc:
        _die(str(exc))

    typer.echo(f"Promoted run {from_run[:8]} → example {example_id[:8]}.")


# ---------------------------------------------------------------------------
# plumb judge run
# ---------------------------------------------------------------------------

_MODEL_HELP = "Model identifier for the judge."
_METRIC_HELP = "Metric name to evaluate."
_SINCE_JUDGE_HELP = "Only evaluate runs newer than this."
_TASK_JUDGE_HELP = "Only evaluate runs with this task_id."
_DRY_RUN_HELP = "Print count without writing scores."


@judge_app.command("run")
def judge_run(
    model: Annotated[str, typer.Option("--model", help=_MODEL_HELP)],
    metric: Annotated[str, typer.Option("--metric", help=_METRIC_HELP)],
    since: Annotated[str | None, typer.Option("--since", help=_SINCE_JUDGE_HELP)] = None,
    task_id: Annotated[str | None, typer.Option("--task-id", help=_TASK_JUDGE_HELP)] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help=_DRY_RUN_HELP)] = False,
) -> None:
    """Run a batch judge evaluation over un-scored runs.

    Skips runs that already have a score for the given metric.
    Individual judge failures are recorded as ``value_label='error'`` rows;
    the command still exits 0 unless the adapter is not configured.
    """
    from plumb.core.entities import Score, ScorerKind

    # Guard: reject API-key-shaped model values
    if re.match(r"^(sk-|anthropic_)", model):
        _die("--model looks like an API key. Pass the model name, not the key.")

    since_dt = _resolve_since(since)

    # Resolve judge adapter
    try:
        from plumb.config import get_settings

        settings = get_settings()
        provider = getattr(settings, "judge_provider", None)
        if not provider:
            _die("PLUMB_JUDGE_PROVIDER is not set. Configure it to use 'plumb judge run'.")
    except Exception as exc:
        _die(str(exc))

    # Fetch un-scored runs via raw parameterized query
    try:
        with _get_storage() as storage:
            since_iso = since_dt.isoformat() if since_dt else None
            db_rows = storage._conn.execute(  # noqa: SLF001
                """
                SELECT r.*
                FROM runs r
                WHERE
                    (? IS NULL OR r.start_ts >= ?)
                    AND (? IS NULL OR r.task_id = ?)
                    AND NOT EXISTS (
                        SELECT 1 FROM scores s
                        WHERE s.run_id = r.run_id AND s.metric_name = ?
                    )
                ORDER BY r.start_ts DESC
                LIMIT 500
                """,
                (since_iso, since_iso, task_id, task_id, metric),
            ).fetchall()

            from plumb.adapters.storage_sqlite import _row_to_run

            runs = [_row_to_run(r) for r in db_rows]

            if dry_run:
                typer.echo(f"Would judge {len(runs)} run(s) for metric={metric!r}.")
                return

            if not runs:
                typer.echo("Nothing to judge.")
                return

            adapter = _load_judge_adapter(provider, model)

            for run in runs:
                try:
                    content = _load_run_content(storage, run.run_id)
                    result = adapter.score(
                        metric_name=metric,
                        prompt="",
                        content=content,
                        model=model,
                    )
                    score = Score(
                        score_id=uuid.uuid4().hex,
                        run_id=run.run_id,
                        metric_name=metric,
                        scorer=ScorerKind.JUDGE,
                        scorer_version=result.scorer_version,
                        scored_at=datetime.now(UTC),
                        value_numeric=result.value_numeric,
                        value_label=result.value_label,
                    )
                except Exception as exc:
                    logger.warning("Judge failed for run %s: %s", run.run_id[:8], exc)
                    score = Score(
                        score_id=uuid.uuid4().hex,
                        run_id=run.run_id,
                        metric_name=metric,
                        scorer=ScorerKind.JUDGE,
                        scorer_version="error",
                        scored_at=datetime.now(UTC),
                        value_label="error",
                    )
                storage.write_score(score)
    except typer.Exit:
        raise
    except Exception as exc:
        _die(str(exc))


def _load_judge_adapter(provider: str, model: str):  # type: ignore[return]
    """Instantiate the judge adapter for the given provider string."""
    # Real adapters land in a future slice; tests inject via monkeypatch.
    raise NotImplementedError(f"Judge provider {provider!r} not yet implemented.")


def _load_run_content(storage, run_id: str) -> str:
    """Return the primary span's blob content decoded as UTF-8, or '' if absent."""
    from plumb.core.entities import SpanKind

    try:
        from plumb.adapters.blobstore_fs import FilesystemBlobStore
        from plumb.config import ensure_data_dir, get_settings

        blob_store = FilesystemBlobStore(ensure_data_dir(get_settings()))
    except Exception:
        return ""

    spans = storage.get_spans_for_run(run_id)
    llm_spans = [s for s in spans if s.kind == SpanKind.LLM and s.input_hash]
    if llm_spans:
        primary = max(llm_spans, key=lambda s: s.tokens_in or 0)
        target_hash = primary.input_hash
    elif spans and spans[0].input_hash:
        target_hash = spans[0].input_hash
    else:
        return ""

    try:
        data = blob_store.get(target_hash)  # type: ignore[arg-type]
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


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
    import uvicorn

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
        if "address" in str(exc).lower() or "in use" in str(exc).lower():
            _die(f"port {port} is already in use.")
        _die(str(exc))


# ---------------------------------------------------------------------------
# plumb attach
# ---------------------------------------------------------------------------

_AS_HELP = "Display alias for the attached database."
_PATH_HELP = "Path to the AgentsView SQLite database."


@app.command("attach")
def attach(
    path: Annotated[Path, typer.Argument(help=_PATH_HELP)],
    as_name: Annotated[str | None, typer.Option("--as", help=_AS_HELP)] = None,
) -> None:
    """Backfill plumb data from a legacy AgentsView SQLite database.

    Delegates to ``agentsview_attach.backfill``; the adapter implementation
    lands in a future slice.
    """
    from plumb.adapters.agentsview_attach import backfill
    from plumb.core.errors import StorageError

    if not path.exists():
        _die(f"Path {path} does not exist.")

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
