# v1-cli — Implementation Tasks

**Feature:** CLI slice (`plumb/cli.py`, `plumb/_time_utils.py`, `plumb/_output.py`)
**Plan:** [v1-cli-plan.md](./v1-cli-plan.md) | **Context:** [v1-cli-context.md](./v1-cli-context.md)

---

## Phase 1 — Scaffolding + `plumb version` + `plumb run stats`

**Objective:** Get the CLI entry point registered and the most-used read command working end-to-end.

### T1.1 — Register `plumb` entry point + scaffold Typer app `[S]`

**Description:** Add `plumb/cli.py` with the Typer app + sub-app structure. Register `plumb = "plumb.cli:app"` in `pyproject.toml [project.scripts]`. Implement `plumb version`.

**Acceptance Criteria:**
- [ ] `plumb --help` lists all sub-apps (`run`, `score`, `example`, `judge`) plus `serve`, `attach`, `version`.
- [ ] `plumb version` prints `plumb 0.1.0` and exits 0.
- [ ] `ruff check .` passes with new file.
- [ ] Google-style docstring on every command function (for `interrogate` gate).

**Files:**
- `plumb/cli.py` — new (skeleton + `version` command)
- `pyproject.toml` — add `[project.scripts]` entry

**Dependencies:** none

**Tests:** `tests/cli/test_cli_misc.py::test_version_output`

---

### T1.2 — `plumb/_time_utils.py` — `parse_since` `[S]`

**Description:** Implement `parse_since` per plan §3.4 + §6.1.

**Acceptance Criteria:**
- [ ] `parse_since("7d")` → `now_utc() - timedelta(days=7)` (UTC-aware).
- [ ] `parse_since("2w")` → `now_utc() - timedelta(weeks=2)`.
- [ ] `parse_since("1h")` → `now_utc() - timedelta(hours=1)`.
- [ ] `parse_since("30m")` → `now_utc() - timedelta(minutes=30)`.
- [ ] `parse_since("2026-01-01")` parses as UTC midnight (naive ISO coerced to UTC).
- [ ] `parse_since("2026-01-01T00:00:00+05:30")` preserves timezone.
- [ ] `parse_since("foobar")` raises `ValueError`.
- [ ] `parse_since("0d")` raises `ValueError` (zero not allowed).

**Files:**
- `plumb/_time_utils.py` — new
- `tests/cli/test_time_utils.py` — new

**Dependencies:** none

**Tests:** Unit tests only; no DB interaction.

---

### T1.3 — `plumb/_output.py` — output formatting `[S]`

**Description:** Implement `is_tty`, `print_table`, `print_json`, `print_csv`, `format_output` per plan §3.5 + §6.2. Resolve PD-1 (rich-only vs. tabulate fallback) before starting.

**Acceptance Criteria:**
- [ ] `format_output(rows, cols, "json")` → valid newline-delimited JSON (one object per line).
- [ ] `format_output(rows, cols, "table")` when `is_tty() = False` → falls back to `"json"`.
- [ ] `format_output(rows, cols, "csv")` → CSV with header row matching `columns`.
- [ ] `format_output(rows, cols, "xml")` → `ValueError`.
- [ ] `print_table` renders with `rich.Table` when `rich` is available.
- [ ] Empty rows list: all formats produce valid empty output (no crash).

**Files:**
- `plumb/_output.py` — new
- `tests/cli/test_output.py` — new

**Dependencies:** PD-1 resolved

**Tests:** Unit tests; monkeypatch `is_tty`.

---

### T1.4 — Implement `plumb run stats` `[M]`

**Description:** Wire `run_stats` command using the JOIN query from plan §5.1, `parse_since`, and `format_output`.

**Acceptance Criteria:**
- [ ] `plumb run stats` against empty DB exits 0 (empty output, no crash).
- [ ] `plumb run stats` lists runs with correct `span_count` and `score_count` columns.
- [ ] `--since 7d` filters out runs older than 7 days.
- [ ] `--task-id foo` filters to only `task_id='foo'` rows.
- [ ] `--format json` outputs newline-delimited JSON.
- [ ] `--format csv` outputs CSV with header.
- [ ] `--limit 5` returns at most 5 rows.
- [ ] Invalid `--since foo` exits 1 with message containing `"Invalid --since"`.
- [ ] Invalid `--format xml` exits 1 with message containing `"table, json, or csv"`.
- [ ] All SQL bindings are parameterized (verified by `ruff S608`).

**Files:**
- `plumb/cli.py` — implement `run_stats`
- `tests/cli/test_cli_run_stats.py` — new

**Dependencies:** T1.1, T1.2, T1.3

**Tests:** Unit + integration (real `SQLiteStorageAdapter` via `tmp_path`).

**Phase 1 Deliverables:**
- [ ] `plumb --help` and `plumb version` work.
- [ ] `plumb run stats` is fully functional with all filters and format options.
- [ ] `parse_since` and `_output` helpers unit-tested independently.

---

## Phase 2 — `plumb score write` + `plumb example promote`

**Objective:** Enable the two write commands that don't need a judge adapter.

### T2.1 — Implement `plumb score write` `[M]`

**Description:** Wire `score_write` per plan §3.3 — XOR validation, run-existence check, `write_score` call.

**Acceptance Criteria:**
- [ ] Writes numeric score row; `plumb run stats` shows score_count incremented.
- [ ] Writes label score row.
- [ ] `--value-numeric 1.0 --value-label pass` → exit 1 + `"Exactly one of"` message.
- [ ] Neither flag → exit 1 + same message.
- [ ] Unknown `--run-id` → exit 1 + `"not found"` in message.
- [ ] Invalid `--scorer xyz` → exit 1 + valid scorer kinds listed.
- [ ] Omitted `--scorer-version` → DB row has `scorer_version = "cli-unversioned"`.
- [ ] `--span-id` (optional) stored on score row when provided.

**Files:**
- `plumb/cli.py` — implement `score_write`
- `tests/cli/test_cli_score_write.py` — new

**Dependencies:** T1.1, T1.3

**Tests:** Unit + integration.

---

### T2.2 — Implement `plumb example promote` `[M]`

**Description:** Wire `example_promote` per plan §3.3 + §6.4. Input hash selection per plan §5.3.

**Acceptance Criteria:**
- [ ] Creates `examples` row with `source='production_promotion'`, `origin_run_id` = provided run.
- [ ] `active = 1` on new example row.
- [ ] `--rubric path/to/rubric.md` content stored verbatim in `examples.rubric`.
- [ ] Unknown `--from-run` → exit 1 + `"not found"` message.
- [ ] Zero-span run → `inputs_hash = "no_spans"`.
- [ ] Single LLM span with `input_hash` → that hash used.
- [ ] Multiple LLM spans → span with highest `tokens_in` wins.
- [ ] No LLM spans but other span kinds present → first span's `input_hash` used.
- [ ] Promoted example prints `"Promoted run {8 chars} → example {8 chars}"`.

**Files:**
- `plumb/cli.py` — implement `example_promote`
- `tests/cli/test_cli_example_promote.py` — new

**Dependencies:** T1.1

**Tests:** Unit + integration.

**Phase 2 Deliverables:**
- [ ] Human reviewers can write scores via `plumb score write` without Python.
- [ ] Production runs can be promoted to the regression dataset via `plumb example promote`.

---

## Phase 3 — `plumb judge run` + `plumb serve` + `plumb attach`

**Objective:** Wire the remaining commands.

### T3.1 — Implement `plumb judge run` `[L]`

**Description:** Wire `judge_run` per plan §3.3 + §6.3. Adapter resolution from settings. `--dry-run` path. Skip-already-scored logic. Resolve PD-2 (blob content format) before starting.

**Acceptance Criteria:**
- [ ] `--dry-run` prints `"Would judge N run(s) for metric=…"` and exits 0; zero score rows written.
- [ ] Non-dry-run: score row written for each un-scored run (verified via DB query).
- [ ] Already-scored runs are NOT re-judged (query filter + integration test).
- [ ] `PLUMB_JUDGE_PROVIDER` unset → exit 1 with message naming the env var.
- [ ] `--since` and `--task-id` filters applied to run selection.
- [ ] `FakeJudgeAdapter` integration test: 3 runs, 3 score rows written.
- [ ] `FakeJudgeAdapter` failure case: judge error → score row with `value_label='error'`; command still exits 0.
- [ ] `--model sk-abc123` → exit 1 + `"looks like an API key"` message.

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
- [ ] `--host 0.0.0.0` emits `logger.warning(...)` containing `"non-loopback"`.
- [ ] `--host 127.0.0.1` (default) emits no warning.
- [ ] Mock-uvicorn test verifies `uvicorn.run` called with correct `host` and `port`.
- [ ] `KeyboardInterrupt` from uvicorn → exits 0.
- [ ] `OSError("address in use")` from uvicorn → exits 1 + `"port {port} is already in use"`.

**Files:**
- `plumb/cli.py` — implement `serve`
- `tests/cli/test_cli_misc.py` — `test_serve_*` cases

**Dependencies:** T1.1

**Tests:** Unit (mock uvicorn).

---

### T3.3 — Implement `plumb attach` `[S]`

**Description:** Thin wrapper calling `agentsview_attach.backfill`. Print import counts on success.

**Acceptance Criteria:**
- [ ] Non-existent path → Typer rejects before delegating; `backfill` never called.
- [ ] Valid SQLite path → `backfill(path, alias=as_name)` called with correct args.
- [ ] Backfill result `{"imported": 5}` → printed to stdout.
- [ ] `StorageError` from `backfill` → exit 1 + error message to stderr.

**Files:**
- `plumb/cli.py` — implement `attach`
- `tests/cli/test_cli_misc.py` — `test_attach_*` cases

**Dependencies:** T1.1; `agentsview_attach.backfill` can be a stub

**Tests:** Unit (mock `backfill`).

**Phase 3 Deliverables:**
- [ ] All seven subcommands implemented.
- [ ] Full test suite passing.

---

## Phase 4 — Quality Gates + Smoke Test

**Objective:** All CI gates green; slice is merge-ready.

### T4.1 — Full CI gate sweep `[S]`

**Acceptance Criteria:**
- [ ] `ruff check .` — zero errors.
- [ ] `ruff format --check .` — zero diffs.
- [ ] `mypy --strict plumb/core/` — zero errors (CLI in permissive mode is OK).
- [ ] `pytest --cov=plumb --cov-fail-under=75` — passes.
- [ ] `interrogate --fail-under 95 plumb/cli.py` — passes.
- [ ] No regressions in existing tests (storage, api, perf).

**Files:** fix whatever linting flags

**Dependencies:** T1–T3 complete

---

### T4.2 — Smoke test for install + `plumb --help` `[S]`

**Acceptance Criteria:**
- [ ] `pip install -e .` succeeds in a fresh venv.
- [ ] `plumb --help` exits 0.
- [ ] `plumb version` prints `plumb 0.1.0` and exits 0.

**Files:**
- `.github/workflows/ci.yml` — add smoke step (or update existing)

**Dependencies:** T1.1 + `pyproject.toml` entry point

**Phase 4 Deliverables:**
- [ ] v1-cli slice is merge-ready.
- [ ] All six CI quality gates green.
- [ ] Smoke test passing.
- [ ] Dev docs updated: move `dev/active/v1-cli/` → `dev/archive/v1-cli/`.
