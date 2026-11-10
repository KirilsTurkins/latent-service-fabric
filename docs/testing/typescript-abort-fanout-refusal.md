# Agent 1: signed abort fan-out refusal investigation

## Evidence boundary

This change removes avoidable generated-export Promise ownership and corrects
an independent completed-graph lifetime in the default-factory probe. The
failure and correction have been reproduced with the retained source-built
SpiderMonkey Wasm under a bounded diagnostic WIT ledger. That harness is **not**
the signed LSF host, and its zero terminal counters do not prove Store custody,
quarantine, pool reuse, or byte-accurate aggregate accounting. The strict signed
Fetch programme remains the acceptance gate. A queued job is not a pass.

## Original signed observations

Run `42516280360`, job `128915932731`, executed synthetic merge
`6ab3da5364ac3e7db57c7154f894bc6223ad728b`. Artifact `13644802996` has SHA-256
`819a3841b5a66e97e018a7ac0d4c761442613bccf40069ce99858c985eaace4f`.
Its `node/FAILED.json` records 15 completed cases, including ordinary nine-way
fan-out. `abort-fanout-refusal` returns `guest-trap/unreachable-code`, not a
successful typed response with a mismatched string. Later default-constructor
reentry and fresh fan-out were not reached. There is no post-failure retirement
sample; CLI process reaping is not native-owner cleanup evidence.

The signed diagnostic matrix in run `42697425825`, artifact `13714638110`
(SHA-256 `a91992853e74f118d7327ec03ac897eaf89a0a3ff084c0d2b6a157db9bdda06b`),
further separates the boundaries:

- Refusal-only returns the deliberately non-success value
  `diagnostic:fanout:refused-unchanged`.
- Original and awaited-checkpoint variants trap during the refusal scenario.
- An allocation-only diagnostic, replacing the await with `Promise.resolve()`,
  reaches the refusal success string and then fails default-factory reentry.
  Removing the await is **not** the correction and is not accepted qualification.

Every experiment failed the unchanged strict programme. The diagnostic
workflow's successful job conclusion must not be interpreted as qualification.
The later integrated engine in run `42705015452` also compiled successfully but
still failed the same signed refusal case after 15 completed cases.

## Generated export ownership defect

The selected binding already owns an asynchronous export frame, enters the real
task asynchronously, and awaits its application result. It additionally calls
`_withGlobalCurrentTaskMetaAsync`, which creates another Promise and adoption
reactions while the application's nine-dependent graph is still live.

The actual SpiderMonkey diagnostic trace shows the intended filler and fan-out
admission refusals, then physical filler retirement, followed by additional
native-owner admission refusals during this generated Promise path. Thus filler
removal does not fail to run, and the original successful ordinary fan-out does
not establish enough capacity for the awaited retry path.

`inlineExportTaskMeta` in `tools/typescript_guest/source_splicer.mjs` transplants
the exact selected private helper body into the existing export await frame.
It removes the redundant async wrapper, not the application checkpoint or a
resource charge. The transform checks the exact helper preimage and a closed AST
shape, rejects ambiguous/changed task or exception handling, and preserves:

- asynchronous `task.enter`, task creation, component/task identities;
- contention waits, exclusivity re-locking, and the application await;
- metadata installation and `finally` cleanup;
- the original export error/rejection path, typed result lowering, and task exit.

Framework callback wrappers remain unchanged. The original callback is captured
outside the helper's lexical scope so parameters named `args`, `fn`, `current`,
`componentIdx`, or other helper-local names keep their bindings. This is a
source-owned compiler change, not a special case keyed to a probe name/mode.
Internal redundant microtask/Promise overhead is intentionally removed; tests
do not claim identical internal scheduling counts for every possible user
object with changing `then` accessors.

With this transform, the actual retained SpiderMonkey guest reaches the exact
refusal success value with the two intended denials and no additional native
admission denial in the diagnostic trace. All modeled terminal counts are zero.
The same graph is checked unchanged both before and after the normal
`await Promise.resolve()`, then retried explicitly with all reason identity,
callback order, and `throwIfAborted` assertions retained.

## Separate default-factory probe lifetime correction

The reentry graph owns 50 native containers/listeners. The diagnostic trace
shows its reentrant abort and fan-out frame retirement complete successfully.
The old helper then attempts a separate fresh signal's four containers while
still retaining that completed graph alongside 11 live framework/Promise
owners. The fourth fresh container is correctly refused at the unchanged
64-owner ceiling. This is not a missing constructor reentry or a leaked fan-out
frame.

The helper now verifies the entire reentrant graph and returns only a plain
entry counter. Its graph frame then ends. The caller executes a normal Promise
checkpoint before constructing the independent fresh signal that verifies
constructor restoration. Reentry must still occur exactly once; root and all
nine dependents must still preserve the first reason and event order; the fresh
signal must still have `AbortError`; an unrestored factory must still fail.
This does not release the refusal scenario's graph before its retry.

## Regression and reproduction commands

The source/reference-host regression run covered 201 tests with no skips,
including the actual emitted native controls, selected compiler materials,
import/task retirement, Fetch probe assertions, and the new export controls.
Focused reproduction:

```sh
LSF_TYPESCRIPT_FRONTEND=/path/to/installed-tools python3 -B -m unittest \
  tools.tests.test_typescript_export_task_meta \
  tools.tests.test_typescript_native_task_meta \
  tools.tests.test_typescript_native_await \
  tools.tests.test_typescript_async_waiters \
  tools.tests.test_typescript_idle_tasks \
  tools.tests.test_typescript_source_splicer \
  tools.tests.test_typescript_fetch_runtime \
  tools.tests.test_typescript_fetch_boundaries -v
```

The captured export fixture is a generated-source control, not a substitute
for rebuilding and signing the guest. Probe fault injection requires missing
or wrong refusal, mutation before refusal, checkpoint mutation, checkpoint or
retry denial, lost callbacks, wrong restored reason, and failed constructor
restoration to remain failures. The unmodified Node primordial-factory behavior
is still rejected; it is never used as native reentry evidence.

Run the complete real programme with authenticated original products:

```sh
python3 tools/qualify_typescript_fetch_runtime.py \
  --tools /path/to/installed-tools \
  --engine /path/to/typescript-fetch-engine-input \
  --splicer /path/to/typescript-source-splicer-input \
  --prepared-qualification /path/to/typescript-fetch-native-input \
  --output /path/to/fresh-signed-output
```

The Agent 1 workflow invokes this unchanged command under the original compiler
isolation. It reuses the source-built native engine/splicer/host products from
run `42516280360` only through their existing authenticated receipts, without
rewriting source identities. It retains the current compiler/probe source,
normal build receipts, component, invocation results, and cleanup controls.
No owner limit, HTTP authority, timeout, success string, or cleanup requirement
is relaxed. Agent 2's `abort_engine.py` and Agent 3's native ownership paths are
not edited by this change. Final integration still requires rebuilding and
qualifying the combined agents' selected source.
