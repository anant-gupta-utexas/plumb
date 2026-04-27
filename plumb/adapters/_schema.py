"""Canonical DDL for plumb's four-table SQLite schema (TRD §7.1).

SQL strings are reproduced verbatim from TRD §7.1 — do not reformat them.
"""
# ruff: noqa: E501

SCHEMA_VERSION: int = 1

DDL_STATEMENTS: tuple[str, ...] = (
    # -------------------------------------------------------------------------
    # runs
    # -------------------------------------------------------------------------
    """\
CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT    PRIMARY KEY,
    kind                TEXT    NOT NULL CHECK (kind IN ('offline', 'online')),
    task_id             TEXT    NOT NULL,
    parent_run_id       TEXT             REFERENCES runs(run_id) ON DELETE SET NULL,
    orchestrator_model  TEXT,
    sub_agent_model     TEXT,
    prompt_version      TEXT,
    tool_schema_version TEXT,
    git_sha             TEXT,
    start_ts            TEXT    NOT NULL,
    end_ts              TEXT,
    tokens_in           INTEGER,
    tokens_out          INTEGER,
    dollar_cost         REAL,
    status              TEXT    NOT NULL CHECK (status IN ('pending', 'success', 'failure', 'aborted', 'stalled')),
    error_type          TEXT
) STRICT""",
    "CREATE INDEX IF NOT EXISTS idx_runs_task_start     ON runs(task_id, start_ts)",
    "CREATE INDEX IF NOT EXISTS idx_runs_kind_start     ON runs(kind, start_ts)",
    "CREATE INDEX IF NOT EXISTS idx_runs_parent         ON runs(parent_run_id)",
    # -------------------------------------------------------------------------
    # spans
    # -------------------------------------------------------------------------
    """\
CREATE TABLE IF NOT EXISTS spans (
    span_id         TEXT    PRIMARY KEY,
    run_id          TEXT    NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    parent_span_id  TEXT             REFERENCES spans(span_id) ON DELETE SET NULL,
    kind            TEXT    NOT NULL CHECK (kind IN ('llm', 'tool', 'subagent', 'handoff', 'plan', 'verify')),
    name            TEXT    NOT NULL,
    input_hash      TEXT,
    output_hash     TEXT,
    tokens          INTEGER,
    latency_ms      INTEGER,
    status          TEXT             CHECK (status IS NULL OR status IN ('success', 'failure', 'aborted')),
    error_type      TEXT
) STRICT""",
    "CREATE INDEX IF NOT EXISTS idx_spans_run           ON spans(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_spans_kind          ON spans(kind)",
    "CREATE INDEX IF NOT EXISTS idx_spans_input_hash    ON spans(input_hash)",
    "CREATE INDEX IF NOT EXISTS idx_spans_output_hash   ON spans(output_hash)",
    # -------------------------------------------------------------------------
    # scores
    # -------------------------------------------------------------------------
    """\
CREATE TABLE IF NOT EXISTS scores (
    score_id         TEXT    PRIMARY KEY,
    run_id           TEXT    NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    span_id          TEXT             REFERENCES spans(span_id) ON DELETE SET NULL,
    metric_name      TEXT    NOT NULL,
    scorer           TEXT    NOT NULL CHECK (scorer IN ('deterministic', 'judge', 'human', 'user_signal')),
    scorer_version   TEXT    NOT NULL,
    value_numeric    REAL,
    value_label      TEXT,
    scored_at        TEXT    NOT NULL,
    CHECK ((value_numeric IS NULL) <> (value_label IS NULL))
) STRICT""",
    "CREATE INDEX IF NOT EXISTS idx_scores_run_metric   ON scores(run_id, metric_name)",
    "CREATE INDEX IF NOT EXISTS idx_scores_metric_time  ON scores(metric_name, scored_at)",
    "CREATE INDEX IF NOT EXISTS idx_scores_scorer_ver   ON scores(scorer, scorer_version)",
    # -------------------------------------------------------------------------
    # examples
    # -------------------------------------------------------------------------
    """\
CREATE TABLE IF NOT EXISTS examples (
    example_id             TEXT    PRIMARY KEY,
    task_id                TEXT    NOT NULL,
    inputs_hash            TEXT    NOT NULL,
    expected_output_hash   TEXT,
    rubric                 TEXT,
    source                 TEXT    NOT NULL CHECK (source IN ('synthetic', 'production_promotion', 'human_authored')),
    origin_run_id          TEXT             REFERENCES runs(run_id) ON DELETE SET NULL,
    active                 INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at             TEXT    NOT NULL
) STRICT""",
    "CREATE INDEX IF NOT EXISTS idx_examples_task_active ON examples(task_id, active)",
    "CREATE INDEX IF NOT EXISTS idx_examples_source      ON examples(source)",
    "CREATE INDEX IF NOT EXISTS idx_examples_origin      ON examples(origin_run_id)",
)
