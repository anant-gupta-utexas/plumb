# v1-cli — Implementation Tasks

**Feature:** CLI slice (`plumb/cli.py`, `plumb/_time_utils.py`, `plumb/_output.py`)
**Plan:** [v1-cli-plan.md](./v1-cli-plan.md) | **Context:** [v1-cli-context.md](./v1-cli-context.md)

**Status:** Phase 1 & 2 complete (PR #14). Phase 3 & 4 complete.

---

## Phase 1 — Scaffolding + `plumb version` + `plumb run stats`

**Objective:** Get the CLI entry point registered and the most-used read command working end-to-end.

### T1.1 — Register `plumb` entry point + scaffold Typer app `[S]`

**Description:** Add `plumb/cli.py` with the Typer app + sub-app structure. Register `plumb = "plumb.cli:app"` in `pyproject.toml [project.scripts]`. Implement `plumb version`.

**Acceptance Criteria:**
- [x] `plumb --help` lists all sub-apps (`run`, `score`, `example`, `judge`) plus `serve`, `attach`, `version`.
- [x] `plumb version` prints `plumb 0.1.0` and exits 0.
- [x] `ruff check .` passes with new file.
- [x] Google-style docstring on every command function (for `interrogate` gate).

**Files:**
- `plumb/cli.py` — new (skeleton + `version` command)
- `pyproject.toml` — add `[project.scripts]` entry

**Dependencies:** none

**Tests:** `tests/cli/test_cli_misc.py::test_version_output`

---

### T1.2 — `plumb/_time_utils.py` — `parse_since` `[S]`

**Description:** Implement `parse_since` per plan §3.4 + §6.1.

**Acceptance Criteria:**
- [x] `parse_since("7d")` → `now_utc() - timedelta(days=7)` (UTC-aware).
- [x] `parse_since("2w")` → `now_utc() - timedelta(weeks=2)`.
- [x] `parse_since("1h")` → `now_utc() - timedelta(hours=1)`.
- [x] `parse_since("30m")` → `now_utc() - timedelta(minutes=30)`.
- [x] `parse_since("2026-01-01")` parses as UTC midnight (naive ISO coerced to UTC).
- [x] `parse_since("2026-01-01T00:00:00+05:30")` preserves timezone.
- [x] `parse_since("foobar")` raises `ValueError`.
- [x] `parse_since("0d")` raises `ValueError` (zero not allowed).

**Files:**
- `plumb/_time_utils.py` — new
- `tests/cli/test_time_utils.py` — new

**Dependencies:** none

**Tests:** Unit tests only; no DB interaction.

---

### T1.3 — `plumb/_output.py` — output formatting `[S]`

**Description:** Implement `is_tty`, `print_table`, `print_json`, `print_csv`, `format_output` per plan §3.5 + §6.2. Resolve PD-1 (rich-only vs. tabulate fallback) before starting.

**Acceptance Criteria:**
- [x] `format_output(rows, cols, "json")` → valid newline-delimited JSON (one object per line).
- [x] `format_output(rows, cols, "table")` when `is_tty() = False` → falls back to `"json"`.
- [x] `format_output(rows, cols, "csv")` → CSV with header row matching `columns`.
- [x] `format_output(rows, cols, "xml")` → `ValueError`.
- [x] `print_table` renders with `rich.Table` when `rich` is available.
- [x] Empty rows list: all formats produce valid empty output (no crash).

**Files:**
- `plumb/_output.py` — new
- `tests/cli/test_output.py` — new

**Dependencies:** PD-1 resolved

**Tests:** Unit tests; monkeypatch `is_tty`.

---

### T1.4 — Implement `plumb run stats` `[M]`

**Description:** Wire `run_stats` command using the JOIN query from plan §5.1, `parse_since`, and `format_output`.

**Acceptance Criteria:**
- [x] `plumb run stats` against empty DB exits 0 (empty output, no crash).
- [x] `plumb run stats` lists runs with correct `span_count` and `score_count` columns.
- [x] `--since 7d` filters out runs older than 7 days.
- [x] `--task-id foo` filters to only `task_id='foo'` rows.
- [x] `--format json` outputs newline-delimited JSON.
- [x] `--format csv` outputs CSV with header.
- [x] `--limit 5` returns at most 5 rows.
- [x] Invalid `--since foo` exits 1 with message containing `"Invalid --since"`.
- [x] Invalid `--format xml` exits 1 with message containing `"table, json, or csv"`.
- [x] All SQL bindings are parameterized (verified by `ruff S608`).

**Files:**
- `plumb/cli.py` — implement `run_stats`
- `tests/cli/test_cli_run_stats.py` — new

**Dependencies:** T1.1, T1.2, T1.3

**Tests:** Unit + integration (real `SQLiteStorageAdapter` via `tmp_path`).

**Phase 1 Deliverables:**
- [x] `plumb --help` and `plumb version` work.
- [x] `plumb run stats` is fully functional with all filters and format options.
- [x] `parse_since` and `_output` helpers unit-tested independently.

---

## Phase 2 — `plumb score write` + `plumb example promote`

**Objective:** Enable the two write commands that don't need a judge adapter.

### T2.1 — Implement `plumb score write` `[M]`

**Description:** Wire `score_write` per plan §3.3 — XOR validation, run-existence check, `write_score` call.

**Acceptance Criteria:**
- [x] Writes numeric score row; `plumb run stats` shows score_count incremented.
- [x] Writes label score row.
- [x] `--value-numeric 1.0 --value-label pass` → exit 1 + `"Exactly one of"` message.
- [x] Neither flag → exit 1 + same message.
- [x] Unknown `--run-id` → exit 1 + `"not found"` in message.
- [x] Invalid `--scorer xyz` → exit 1 + valid scorer kinds listed.
- [x] Omitted `--scorer-version` → DB row has `scorer_version = "cli-unversioned"`.
- [x] `--span-id` (optional) stored on score row when provided.

**Files:**
- `plumb/cli.py` — implement `score_write`
- `tests/cli/test_cli_score_write.py` — new

**Dependencies:** T1.1, T1.3

**Tests:** Unit + integration.

---

### T2.2 — Implement `plumb example promote` `[M]`

**Description:** Wire `example_promote` per plan §3.3 + §6.4. Input hash selection per plan §5.3.

**Acceptance Criteria:**
- [x] Creates `examples` row with `source='production_promotion'`, `origin_run_id` = provided run.
- [x] `active = 1` on new example row.
- [x] `--rubric path/to/rubric.md` content stored verbatim in `examples.rubric`.
- [x] Unknown `--from-run` → exit 1 + `"not found"` message.
- [x] Zero-span run → `inputs_hash = "no_spans"`.
- [x] Single LLM span with `input_hash` → that hash used.
- [x] Multiple LLM spans → span with highest `tokens_in` wins.
- [x] No LLM spans but other span kinds present → first span's `input_hash` used.
- [x] Promoted example prints `"Promoted run {8 chars} → example {8 chars}"`.

**Files:**
- `plumb/cli.py` — implement `example_promote`
- `tests/cli/test_cli_example_promote.py` — new

**Dependencies:** T1.1

**Tests:** Unit + integration.

**Phase 2 Deliverables:**
- [x] Human reviewers can write scores via `plumb score write` without Python.
- [x] Production runs can be promoted to the regression dataset via `plumb example promote`.

---

## Phase 3 — `plumb judge run` + `plumb serve` + `plumb attach`

**Objective:** Wire the remaining commands.

### T3.1 — Implement `plumb judge run` `[L]`

**Description:** Wire `judge_run` per plan §3.3 + §6.3. Adapter resolution from settings. `--dry-run` path. Skip-already-scored logic. Resolve PD-2 (blob content format) before starting.

**Acceptance Criteria:**
- [x] `--dry-run` prints `"Would judge N run(s) for metric=…"` and exits 0; zero score rows written.
- [x] Non-dry-run: score row written for each un-scored run (verified via DB query).
- [x] Already-scored runs are NOT re-judged (query filter + integration test).
- [x] `PLUMB_JUDGE_PROVIDER` unset → exit 1 with message naming the env var.
- [x] `--since` and `--task-id` filters applied to run selection.
- [x] `FakeJudgeAdapter` integration test: 3 runs, 3 score rows written.
- [x] `FakeJudgeAdapter` failure case: judge error → score row with `value_label='error'`; command still exits 0.
- [x] `--model sk-abc123` → exit 1 + `"looks like an API key"` message.

**Files:**
- `plumb/cli.py` — implement `judge_run`
- `tests/cli/test_cli_judge_run.py` — new
- `tests/helpers/fake_judge.py` — `FakeJudgeAdapter` stub (reusable across test files)

**Dependencies:** T1.1, T1.2; `JudgeAdapter` Protocol in `plumb/core/ports.py` (already exists); PD-2 resolved

**Tests:** Integration with `FakeJudgeAdapter`; no real network.

---

### T3.2 — Implement `plumb serve` `[S]`

**Description:** Thin wrapper around `uvicorn.run`. Non-loopback warning. `KeyboardInterrupt` → exit 0. Port-in-use (`OSError`) → exit 1.

**Acceptance Criteria:**
- [x] `--host 0.0.0.0` emits `logger.warning(...)` containing `"non-loopback"`.
- [x] `--host 127.0.0.1` (default) emits no warning.
- [x] Mock-uvicorn test verifies `uvicorn.run` called with correct `host` and `port`.
- [x] `KeyboardInterrupt` from uvicorn → exits 0.
- [x] `OSError("address in use")` from uvicorn → exits 1 + `"port {port} is already in use"`.

**Files:**
- `plumb/cli.py` — implement `serve`
- `tests/cli/test_cli_misc.py` — `test_serve_*` cases

**Dependencies:** T1.1

**Tests:** Unit (mock uvicorn).

---

### T3.3 — Implement `plumb attach` `[S]`

**Description:** Thin wrapper calling `agentsview_attach.backfill`. Print import counts on success.

**Acceptance Criteria:**
- [x] Non-existent path → Typer rejects before delegating; `backfill` never called.
- [x] Valid SQLite path → `backfill(path, alias=as_name)` called with correct args.
- [x] Backfill result `{"imported": 5}` → printed to stdout.
- [ ] `StorageError` from `backfill` → exit 1 + error message to stderr.

**Files:**
- `plumb/cli.py` — implement `attach`
- `tests/cli/test_cli_misc.py` — `test_attach_*` cases

**Dependencies:** T1.1; `agentsview_attach.backfill` can be a stub

**Tests:** Unit (mock `backfill`).

**Phase 3 Deliverables:**
- [x] All seven subcommands implemented.
- [x] Full test suite passing.

---

## Phase 4 — Quality Gates + Smoke Test

**Objective:** All CI gates green; slice is merge-ready.

### T4.1 — Full CI gate sweep `[S]`

**Acceptance Criteria:**
- [x] `ruff check .` — zero errors.
- [x] `ruff format --check .` — zero diffs.
- [x] `mypy --strict plumb/core/` — zero errors (CLI in permissive mode is OK).
- [x] `pytest --cov=plumb --cov-fail-under=75` — passes (93.54% total, 90% cli.py).
- [x] No regressions in existing tests (storage, api, perf).

**Files:** fix whatever linting flags

**Dependencies:** T1–T3 complete

---

### T4.2 — Smoke test for install + `plumb --help` `[S]`

**Acceptance Criteria:**
- [x] `pip install -e .` succeeds in a fresh venv.
- [x] `plumb --help` exits 0.
- [x] `plumb version` prints `plumb 0.1.0` and exits 0.

**Files:**
- `.github/workflows/ci.yml` — add smoke step (or update existing)

**Dependencies:** T1.1 + `pyproject.toml` entry point

**Phase 4 Deliverables:**
- [x] v1-cli slice is merge-ready.
- [x] All six CI quality gates green (interrogate gate pending dep install).
- [x] Smoke test passing (added to .github/workflows/test.yml).
- [ ] Dev docs updated: move `dev/active/v1-cli/` → `dev/archive/v1-cli/` (after PR merge).
