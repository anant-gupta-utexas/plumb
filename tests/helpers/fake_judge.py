"""FakeJudgeAdapter — reusable test stub implementing the JudgeAdapter Protocol."""

from __future__ import annotations

from plumb.core.entities import JudgeResult


class FakeJudgeAdapter:
    """Deterministic judge that returns a fixed result or raises on demand."""

    name = "fake"
    version = "1.0"

    def __init__(
        self,
        *,
        value_label: str = "pass",
        value_numeric: float | None = None,
        scorer_version: str = "fake-v1",
        raise_on_run_id: str | None = None,
    ) -> None:
        self.value_label = value_label
        self.value_numeric = value_numeric
        self.scorer_version = scorer_version
        self.raise_on_run_id = raise_on_run_id
        self.calls: list[dict] = []

    def score(
        self,
        *,
        metric_name: str,
        prompt: str,
        content: str,
        model: str,
        timeout_s: float = 60.0,
    ) -> JudgeResult:
        """Return a fixed JudgeResult; raise RuntimeError if run_id matches raise_on_run_id."""
        self.calls.append(
            {"metric_name": metric_name, "prompt": prompt, "content": content, "model": model}
        )
        if self.raise_on_run_id and content.startswith(self.raise_on_run_id):
            raise RuntimeError(f"FakeJudgeAdapter forced error for content={content!r}")
        return JudgeResult(
            metric_name=metric_name,
            scorer_version=self.scorer_version,
            rationale="fake rationale",
            tokens_in=10,
            tokens_out=5,
            latency_ms=1.0,
            value_numeric=self.value_numeric,
            value_label=self.value_label if self.value_numeric is None else None,
        )
