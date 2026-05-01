"""judge run subcommand — extracted from cli.py per DR-2 (> 400 LOC threshold)."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Annotated

import typer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Help strings (keep in sync with cli.py's _*_HELP constants for consistency)
# ---------------------------------------------------------------------------

_MODEL_HELP = "Model identifier for the judge."
_METRIC_HELP = "Metric name to evaluate."
_SINCE_JUDGE_HELP = "Only evaluate runs newer than this."
_TASK_JUDGE_HELP = "Only evaluate runs with this task_id."
_DRY_RUN_HELP = "Print count without writing scores."


def register(judge_app: typer.Typer, get_storage, resolve_since, die) -> None:  # type: ignore[type-arg]
    """Register the ``judge run`` command on *judge_app*.

    Accepts injected helpers (``get_storage``, ``resolve_since``, ``die``) so
    this module does not import from ``plumb.cli`` (avoiding circular imports).
    """

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
            die("--model looks like an API key. Pass the model name, not the key.")

        since_dt = resolve_since(since)

        # Resolve judge adapter
        try:
            from plumb.config import get_settings

            settings = get_settings()
            provider = getattr(settings, "judge_provider", None)
            if not provider:
                die("PLUMB_JUDGE_PROVIDER is not set. Configure it to use 'plumb judge run'.")
        except typer.Exit:
            raise
        except Exception as exc:
            die(str(exc))

        # Fetch un-scored runs via adapter method (PD-4: SQL stays inside the adapter)
        try:
            with get_storage() as storage:
                runs = storage.list_runs_unscored_for_metric(
                    metric=metric, since=since_dt, task_id=task_id
                )

                if dry_run:
                    typer.echo(f"Would judge {len(runs)} run(s) for metric={metric!r}.")
                    return

                if not runs:
                    typer.echo("Nothing to judge.")
                    return

                adapter = _load_judge_adapter(provider, model)

                blob_store = _make_blob_store()
                for run in runs:
                    try:
                        content = _load_run_content(storage, blob_store, run.run_id)
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
                    try:
                        storage.write_score(score)
                    except Exception as exc:
                        logger.warning(
                            "Failed to write error-score for run %s: %s", run.run_id[:8], exc
                        )
        except typer.Exit:
            raise
        except Exception as exc:
            die(str(exc))


def _load_judge_adapter(provider: str, model: str):  # type: ignore[return]
    """Instantiate the judge adapter for the given provider string.

    # TODO(adapter-slice): wire real adapters per PD-2; dispatch on provider here.
    """
    raise NotImplementedError(f"Judge provider {provider!r} not yet implemented.")


def _make_blob_store():
    """Construct a FilesystemBlobStore from current settings, or return None on error."""
    try:
        from plumb.adapters.blobstore_fs import FilesystemBlobStore
        from plumb.config import ensure_data_dir, get_settings

        return FilesystemBlobStore(ensure_data_dir(get_settings()))
    except Exception:
        return None


def _load_run_content(storage, blob_store, run_id: str) -> str:
    """Return the primary span's blob content decoded as UTF-8, or '' if absent."""
    from plumb.core.entities import SpanKind

    if blob_store is None:
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
    except (OSError, Exception):
        return ""
