# Orchestrator Handoff Patterns

Multi-process orchestrator systems often need to record a single logical job across several Python processes or sub-agents. plumb supports this through explicit `parent_run_id` threading (FR-GRAPH-2) and, as of v1.1, through `resume_run` for same-run continuation. This guide explains the four handoff shapes and when to use each.

---

## The three patterns

### Pattern 1 — Child run via `parent_run_id` (supported today)

The orchestrator starts a run, records its `run_id`, and passes it to the subprocess via an environment variable or any other IPC mechanism. The child process starts its own `with run(...)` block and supplies the parent's `run_id` through the `parent_run_id` kwarg. The child becomes a separate `runs` row linked to the parent via `runs.parent_run_id`.

**When to use:** the child has its own coherent lifecycle (start, spans, end) that is meaningfully distinct from the parent's. This is the correct model for an orchestrator that delegates a code-generation stage to a separate process.

```python
# orchestrator.py
import os
from plumb import run, SpanKind

with run(task_id="atlas.orchestrate", kind="online") as r:
    parent_run_id = r.run_id

    # Thread the run_id to the sub-process
    env = {**os.environ, "PLUMB_PARENT_RUN_ID": parent_run_id}
    subprocess.run(["python", "code_gen.py"], env=env, check=True)

    r.add_span(SpanKind.HANDOFF, "code_gen_handoff")
```

```python
# code_gen.py
import os
from plumb import run

parent_run_id = os.environ.get("PLUMB_PARENT_RUN_ID")

with run(task_id="atlas.code_gen", kind="online", parent_run_id=parent_run_id) as r:
    # child run — appears linked in plumb run stats
    r.add_span("llm", "generate")
```

The child row's `parent_run_id` FK is satisfied because the parent row was written to SQLite at `__enter__` time (status `'pending'`), before the subprocess starts (TRD FR-GRAPH-1).

**Important:** plumb does NOT inject `parent_run_id` automatically across process boundaries. The caller is responsible for threading it through.

---

### Pattern 2 — Sibling runs sharing a `task_id` (supported today)

When orchestrator and sub-agent are independent steps in the same pipeline but there is no explicit parent/child relationship, give them the same `task_id`. They become sibling rows in the `runs` table. Querying by `task_id` (via `plumb run stats --task-id <id>`) surfaces all of them together.

```python
# step_a.py
with run(task_id="atlas.pipeline.v2", kind="online") as r:
    ...

# step_b.py — separate process, same task_id
with run(task_id="atlas.pipeline.v2", kind="online") as r:
    ...
```

Use this when the two processes do not have a strict "started by" relationship or when you only need aggregate metrics across the whole task.

---

### Pattern 3 — Same-run continuation across processes (supported since v1.1)

Atlas's `code_gen` flow needs to *continue* an existing run from a new process — appending spans to a run that was opened by the orchestrator, rather than forking a child. This is semantically different from Pattern 1: there is one `runs` row, and multiple processes contribute to it.

`plumb.resume_run(run_id)` re-opens a run that a previous process left `pending` (i.e. it entered `with run(...)` but the process exited or handed off before the block closed). It is context-manager-only — there is no decorator form, since resuming requires an existing `run_id` that can't be bound at decoration time.

```python
# orchestrator.py — opens the run, leaves it pending, hands run_id to a worker
from plumb import run

r = run(task_id="atlas.code_gen").__enter__()  # entered, not yet exited
run_id = r.run_id
# ... signal run_id to the worker (queue, file, env var) and exit this process
# without calling __exit__ — the row stays status='pending' in SQLite
```

```python
# worker.py — resumes the same run in a different process
from plumb import resume_run, SpanKind

with resume_run(run_id) as r:
    r.add_span(SpanKind.LLM, "generate")
    r.set_usage(dollar_cost=0.004)
# finalize_run fires on exit — original start_ts is preserved,
# end_ts reflects this process's exit time
```

`resume_run` raises `NotFoundError` if `run_id` doesn't exist, and `ValidationError` if the run is already terminal (`success`/`failure`/`aborted`/`stalled`) — a `stalled` run has already been given up on by the 1-hour stalled-sweep, so resuming it would race that sweep rather than legitimately continue it.

**When to use:** the orchestrator and the continuing process are contributing to the *same* logical execution, not two related-but-distinct ones. If the child has its own coherent start/end lifecycle, prefer Pattern 1 (`parent_run_id`) instead.

---

## Handoff spans (FR-GRAPH-3)

When an orchestrator hands a brief to a sub-agent and receives a summary back, record the round-trip as a `kind='handoff'` span on the parent run:

```python
with run(task_id="atlas.orchestrate", kind="online") as r:
    brief_hash = blobstore.put(brief.encode())
    # ... start sub-agent process ...
    summary_hash = blobstore.put(summary.encode())

    r.add_span(
        "handoff",
        "code_gen_stage",
        input_hash=brief_hash,
        output_hash=summary_hash,
    )
```

The `handoff_roundtrip` metric (PRD §4) reads these two hashes from the blob store. Storing both blobs enables post-hoc quality review of brief fidelity.

---

## Decision guide

| Need | Pattern | Supported since |
|---|---|---|
| Sub-agent has its own start/end lifecycle | Child run (`parent_run_id`) | v1.0 |
| Two independent pipeline steps, same task | Sibling runs (same `task_id`) | v1.0 |
| One logical run, multiple processes | Same-run continuation (`resume_run`) | v1.1 |
| Post-hoc quality review of brief/summary | `kind='handoff'` span | v1.0 |
