"""Tests for _schema.py — DDL string correctness (Task 1.2)."""

import sqlite3

import pytest

from plumb.adapters._schema import DDL_STATEMENTS, SCHEMA_VERSION

# Pinned copy of TRD §7.1 SQL block — test diffs DDL_STATEMENTS against this
_TRD_DDL = """\
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
) STRICT;
CREATE INDEX IF NOT EXISTS idx_runs_task_start     ON runs(task_id, start_ts);
CREATE INDEX IF NOT EXISTS idx_runs_kind_start     ON runs(kind, start_ts);
CREATE INDEX IF NOT EXISTS idx_runs_parent         ON runs(parent_run_id);
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
) STRICT;
CREATE INDEX IF NOT EXISTS idx_spans_run           ON spans(run_id);
CREATE INDEX IF NOT EXISTS idx_spans_kind          ON spans(kind);
CREATE INDEX IF NOT EXISTS idx_spans_input_hash    ON spans(input_hash);
CREATE INDEX IF NOT EXISTS idx_spans_output_hash   ON spans(output_hash);
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
) STRICT;
CREATE INDEX IF NOT EXISTS idx_scores_run_metric   ON scores(run_id, metric_name);
CREATE INDEX IF NOT EXISTS idx_scores_metric_time  ON scores(metric_name, scored_at);
CREATE INDEX IF NOT EXISTS idx_scores_scorer_ver   ON scores(scorer, scorer_version);
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
) STRICT;
CREATE INDEX IF NOT EXISTS idx_examples_task_active ON examples(task_id, active);
CREATE INDEX IF NOT EXISTS idx_examples_source      ON examples(source);
CREATE INDEX IF NOT EXISTS idx_examples_origin      ON examples(origin_run_id)"""


def _normalize(sql: str) -> str:
    """Strip trailing semicolons and collapse whitespace for comparison."""
    import re
    sql = sql.rstrip(";").strip()
    sql = re.sub(r"[ \t]+", " ", sql)
    sql = re.sub(r"\n ", "\n", sql)
    return sql


def test_schema_version() -> None:
    assert SCHEMA_VERSION == 1


def test_ddl_statement_count() -> None:
    # 4 CREATE TABLE + 13 CREATE INDEX = 17
    create_tables = [s for s in DDL_STATEMENTS if "CREATE TABLE" in s]
    create_indexes = [s for s in DDL_STATEMENTS if "CREATE INDEX" in s]
    assert len(create_tables) == 4, f"expected 4 CREATE TABLE, got {len(create_tables)}"
    assert len(create_indexes) == 13, f"expected 13 CREATE INDEX, got {len(create_indexes)}"


def test_ddl_matches_trd() -> None:
    """Each statement in DDL_STATEMENTS matches the pinned TRD §7.1 block."""
    trd_statements = [_normalize(s) for s in _TRD_DDL.split(";") if s.strip()]
    impl_statements = [_normalize(s) for s in DDL_STATEMENTS]
    assert impl_statements == trd_statements


def test_each_statement_parses() -> None:
    """Every DDL statement executes without error against an in-memory DB."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    for stmt in DDL_STATEMENTS:
        conn.execute(stmt)
    conn.close()


def test_all_create_table_use_if_not_exists() -> None:
    tables = [s for s in DDL_STATEMENTS if s.lstrip().startswith("CREATE TABLE")]
    for stmt in tables:
        assert "IF NOT EXISTS" in stmt, f"Missing IF NOT EXISTS: {stmt[:60]}"


def test_all_create_table_use_strict() -> None:
    tables = [s for s in DDL_STATEMENTS if s.lstrip().startswith("CREATE TABLE")]
    for stmt in tables:
        assert stmt.rstrip().endswith("STRICT"), f"Missing STRICT: {stmt[:60]}"


def test_all_create_index_use_if_not_exists() -> None:
    indexes = [s for s in DDL_STATEMENTS if s.lstrip().startswith("CREATE INDEX")]
    for stmt in indexes:
        assert "IF NOT EXISTS" in stmt, f"Missing IF NOT EXISTS: {stmt[:60]}"


def test_foreign_key_clauses() -> None:
    combined = " ".join(DDL_STATEMENTS)
    assert "REFERENCES runs(run_id) ON DELETE SET NULL" in combined
    assert "REFERENCES runs(run_id) ON DELETE CASCADE" in combined
    assert "REFERENCES spans(span_id) ON DELETE SET NULL" in combined


def test_check_xor_constraint() -> None:
    scores_stmt = next(s for s in DDL_STATEMENTS if "scores" in s and "CREATE TABLE" in s)
    assert "CHECK ((value_numeric IS NULL) <> (value_label IS NULL))" in scores_stmt


@pytest.mark.parametrize("table", ["runs", "spans", "scores", "examples"])
def test_idempotent_reinit(table: str) -> None:
    """Running DDL twice on same DB is a no-op (IF NOT EXISTS)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    for stmt in DDL_STATEMENTS:
        conn.execute(stmt)
    # second pass must not error
    for stmt in DDL_STATEMENTS:
        conn.execute(stmt)
    conn.close()
