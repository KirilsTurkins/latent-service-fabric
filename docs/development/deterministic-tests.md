# Deterministic timing and cancellation tests

Use committed state and explicitly owned futures as readiness witnesses. A sleep,
a yield count, a sent cancellation request, or a historical arrival is not proof
that work is currently queued, executing, or retired. These helpers are test-only;
production scheduling, deadline enforcement, resource receipts and phase gates do
not depend on them.

## Existing coordination inventory and the first migration

Reviewed against `50f003dd006e0786494936c49e55dc683cf26fd6` on `development`.
This is a bounded migration, not a replacement of all timing or containment tests.

| Owner | Existing mechanism | Decision |
| --- | --- | --- |
| `latent-testkit/src/deterministic.rs` | Deterministic IDs, raw nanosecond `ManualClock`, temporary directories, thread-parking `block_on` | Reuse IDs and executor. Preserve `ManualClock` for raw counters; its freely settable nanos are **not** an `ActivationClock` monotonic domain. Pair parked futures with a finite watchdog. |
| `latent-admission/src/tests/stress.rs` | A 75 ms policy sleep expires a 50 ms live admission deadline | Replace this one deadline suite with shared `TestClock`, eight exact policy-time/wall-jump combinations, the production injected-clock path, unchanged deadline and quota assertions. |
| `latent-admission/src/tests/incoming.rs` | Local clock with read/sample counters and deadline diagnostic observations | Retain specialized observer/read-count tests. Shared helpers do not add hidden clock reads or replace these diagnostics. |
| `latent-scheduler/src/fixed_pool/tests/races.rs` | Repeated barrier races, one explicit first-poll handshake, bounded yield-loop settling | Migrate the entire race suite. Explicitly poll the actual acquisition, assert live queue/accounting state, exercise both linearization orders and join cancelled owners. Add retained native-work/buffer ownership after client abandonment. |
| `latent-scheduler/src/fixed_pool/tests/support.rs` | Private wall-clock adapter and observation/yield helpers used by other suites | Keep legacy wall-clock and real timer coverage outside this selection. Do not pretend that advancing `TestClock` controls these Tokio timers. |
| `latent-scheduler/src/fixed_pool/mod.rs` | Committed test-transition history and coalescing production change notifications | Preserve both production seams. A transition notification alone does not prove a task is still blocked; resample live state. |
| `latent-node/tests/activation_runner_race_support/backend_and_pools.rs` | Entry/proceed barriers, backend and disposition doubles, finite rendezvous timeout | Retain activation-runner integration. Future migrations can use the same stages without importing the node into low-level tests. |
| `latent-core/src/deadline_wait_observer.rs` | Affine counters around the actual manager-owned deadline wait | Retain this production-boundary observer; manual timer registrations are a different measurement and never substitute for it. |
| `latent-wasmtime/tests/containment_backend/rendezvous.rs` | Mixed-memory guest arrivals plus explicit unfinished-task verification, timeout/failure cleanup | Retain native containment: its current-liveness requirement informs the shared pause contract. No real Wasmtime or physical-resource test is replaced with a mock or virtual-time result. |

The provisional local measurement IDs are `admission.policy-deadline` and
`scheduler.fixed-pool-races`. Issues #426 (stage timing) and #427 (suite inventory)
were still open without a landed shared contract at this baseline. The measurement
script retains exact package, selector, names, source revision and counts so those
owners can adopt these selections. It is not a new CI classifier or general
Actions comparison engine. No additional phase dependency is introduced.

## Clock domains

`TestClock::new(wall_unix_millis, monotonic, maximum_waiters)` implements the
existing `latent_core::ActivationClock` interface. Clones share one coherent
sample. `advance` moves only monotonic time forward with checked arithmetic;
`set_wall_unix_millis` independently changes wall observations. Convert an incoming
wall deadline once through the existing production admission seam; never restart
an already granted monotonic deadline when wall time changes.

`sleep_until` registers on its first poll, not construction. At the exact deadline,
`advance` removes due registrations and wakes them outside the clock lock. Dropping
a pending sleep removes its registration. Capacity is fixed, stale dropped timers
do not consume reused capacity, and counter arithmetic never wraps.

Advancing this clock wakes **only its own manual sleeps**. An `ActivationClock`
consumer's existing production wait mechanism is unchanged. Tokio `start_paused`
and `advance` affect Tokio's timer driver, not this clock or `std::time::Instant`.
Neither clock controls a native backend or child process. Use the real execution
and process supervision boundaries for those. The helper tests retain a real
`SystemActivationClock`/Tokio timer integration check and verify the separation
between all three host clock domains.

The executable [deadline example](../../crates/latent-testkit/examples/deadline.rs)
registers a timer, jumps wall time backwards, advances to just before expiry, and
then asserts the exact wake and zero remaining registrations:

```sh
cargo run -p latent-testkit --no-default-features --example deadline --locked
```

## Current readiness and owner retirement

`Rendezvous::new(capacity)` retains fixed-size metadata, never work or buffers.
`track(owner)` returns an opaque registration and a `Tracked<T>` owner. Record
`Requested -> Queued -> Entered -> CancellationObserved` only after the relevant
subsystem action commits. Legal bypasses include immediate entry and cancellation
before entry. `Retired` cannot be manually committed: it is published only after
the tracked value is dropped, including unwinding.

`Tracked::pause` registers a live gate on poll. `blocked(registration, stage)`
checks the current stage and pause and issues a generation-bound ticket. Release,
dropped pauses, recycled slots and tickets from another fixture cannot establish
readiness for a later pause. A release clears the blocked witness immediately,
not when the task happens to be scheduled again. Observers retain no owner.

`PollProbe::pending` performs one poll without executor luck. Also check the
**actual** subsystem queue, reservation or lease state: an arbitrary pending
future is not proof of queue registration. The scheduler migration deliberately
keeps a queued acquisition unpolled after grant delivery so task abort tests cover
both queued cleanup and delivery-before-acceptance cleanup exactly.

An abort request is not retirement. Join the task that actually owns the resource,
then check both retirement and actual quota/cell/buffer accounting. Cancelling a
client waiting on independently owned native work must not refund the worker's
lease or buffer. The migrated scheduler test keeps that worker at a live gate,
asserts charged ownership after client cancellation, and only permits retirement
after the worker drops its buffer and cell owner.

The executable [cancellation example](../../crates/latent-testkit/examples/cancellation.rs)
uses a weak buffer reference to verify actual destruction, not only an observer
counter:

```sh
cargo run -p latent-testkit --no-default-features --example cancellation --locked
```

Every new asynchronous wait uses `with_watchdog` or the watchdog inside `pause`.
These finite **real-clock** guards detect deadlocks even with paused Tokio time;
they are not readiness mechanisms or performance gates. The guard owns and joins
its watchdog thread on success, cancellation and panic. A watchdog cannot preempt
a blocking `Future::poll`; retain a finite outer process/job timeout for native
or blocking code. Do not retry a failed test until it passes.

## Dependency isolation and validation

Low-level admission/scheduler tests select the neutral implementation directly:

```toml
[dev-dependencies]
latent-core = { path = "../latent-core", features = ["test-support"] }
```

Use `latent_core::test_support::{TestClock, DeterministicIds}` and
`latent_core::test_support::coordination::{Rendezvous, PollProbe, Stage}` there.
The standard-library-only helpers and their 21 unit tests live together under
`latent-core/src/test_support/`. The feature is opt-in. Tokio and tempfile are
**dev-dependencies only** of core, used to run the relocated tests; core has no
production dependencies and no back edge into a workspace crate. No new crate,
production clock hook or scheduling semantics are introduced.

`latent-testkit` re-exports those exact modules and types, including its existing
root-level exports. Existing harness users and the executable examples retain
their import paths. Its default `runtime` feature still gates the optional
activation/executor/node/telemetry harness dependencies, but **feature gating is
not an exception to the workspace acyclicity rule**. Upstream crates must not add
a testkit dependency, even with `default-features = false`.

```sh
python3 tools/validate_foundation.py
python3 tools/check_testkit_dependencies.py
python3 -m unittest tools.tests.test_deterministic_tests tools.tests.test_testkit_dependencies
cargo test -p latent-core --features test-support --lib --locked test_support:: -- --test-threads=1
cargo test -p latent-core --features test-support --lib --locked test_support:: -- --test-threads=4
cargo test -p latent-admission -p latent-scheduler --lib --locked
cargo test -p latent-testkit --no-default-features --lib --test test_support_compatibility --locked
cargo test -p latent-testkit --lib --test test_support_compatibility --locked
```

The guard first invokes the existing foundation validator over **all** workspace
manifest edges, including optional, development, build and target-specific edges.
Only then does it inspect independently selected Cargo graphs, including their
test dependencies. The Python regressions reconstruct the originally missed
admission/testkit/node and scheduler/testkit/node cycles and require failure
before Cargo is invoked. They also cover aliases, optional/target/build edges,
missing feature selection, empty graphs and heavyweight dependencies. CI runs
these regressions and the guard before the expensive workspace build; it does
not weaken or bypass the foundation validator.

The relocated tests retain fixed IDs, explicit wakeups, missing readiness,
stale/recycled/foreign tickets, premature retirement, buffer ownership, capacity
limits, abort, panic and real watchdog expiry. Both current-thread and
multi-thread Tokio runtimes exercise the controlled scripts. Re-export tests
ensure both import surfaces use identical types and shared clock state. Existing
ignored resource/qualification tests keep their separate explicit entrypoints.

## Before/after execution evidence

Build both source revisions before measuring the selected prebuilt test binaries.
On the same host, run:

```sh
git worktree add /tmp/lsf-before-433 50f003dd006e0786494936c49e55dc683cf26fd6
python3 tools/measure_deterministic_tests.py \
  --baseline /tmp/lsf-before-433 --output target/deterministic-tests.json
```

The script verifies nonempty discovery and exact expected test counts, then runs
five required passing repetitions with one and four libtest threads. Each suite
contains its own current-/multi-thread runtime cases where applicable. Baseline
admission has one test with the live sleep; the migrated test has eight controlled
subcases. Scheduler grows from three tests with 128 probabilistic race repetitions
to seven tests covering both orders and owner-lifetime boundaries. Compilation is
excluded from the reported process execution durations; startup and teardown are
included. This does not claim equivalent interleavings or a whole-CI speedup.
Failed/partial runs are retained as failed evidence, not included in success
claims. There is no timing threshold and no retry-to-green policy.

### Retained run on September 20, 2026

The [raw execution receipt](../../benchmarks/ci/deterministic-tests/2026-09-20.json)
is retained byte-for-byte from artifact `10606779086` in successful
[validation run 35516638297](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35516638297).
Both source trees were clean. The runner was Ubuntu 24.04.5, x86-64 Linux,
with Rust 1.97.1. All five repetitions of each selection passed; no failed
execution was discarded or retried by the measurement script.

| Suite | Libtest threads | Before tests | After tests | Before median (ms) | After median (ms) |
| --- | --- | --- | --- | --- | --- |
| Admission policy deadline | 1 | 1 | 1 (8 controlled subcases) | 76.846 | 1.956 |
| Admission policy deadline | 4 | 1 | 1 (8 controlled subcases) | 76.986 | 1.928 |
| Scheduler fixed-pool races | 1 | 3 | 7 | 27.138 | 5.648 |
| Scheduler fixed-pool races | 4 | 3 | 7 | 17.460 | 4.247 |

The before revision is `50f003dd006e0786494936c49e55dc683cf26fd6`; the tested and
measured after revision is `b27113253dfaead86f549087fa31363c8bc43cda`. The Actions
run was triggered at `e1fe49d941550e404e8c5fb8a110bf43f21a872b` and committed
formatting before executing its checks. The receipt records the actual checked-out
revision, rather than mistaking the trigger revision for the measured source.

That run also passed 42 no-default-feature testkit tests under each of one and four
libtest threads, 52 admission tests, 43 scheduler tests, 61 default-feature testkit
tests, five Python tests, and both executable contributor examples. The admission
and scheduler commands each retained one existing ignored qualification test;
these were not counted as passes. The doctest command succeeded with zero cases.
The independently selected dependency graphs had 21, 33 and 35 nodes for neutral
testkit, admission and scheduler respectively, with no forbidden runtime/provider
dependencies. Strict testkit/admission Clippy checks and documentation validation
passed. Scheduler Clippy retained existing warnings outside the migrated module;
the migrated module independently denies `clippy::all` and `clippy::pedantic`.

The temporary branch-only, write-enabled formatting/validation workflow was
removed after retaining this evidence. Ordinary repository CI remains unchanged;
the scoped run does not replace full PR, native-runtime or containment validation.

### Dependency-cycle correction

The initial `b6ae23b` publication failed the unconditional foundation graph:
`latent-admission -> latent-testkit -> latent-node -> latent-admission`, with
corresponding scheduler cycles. The earlier feature-selected 21/33/35-node graph
observations below were not evidence of workspace acyclicity. The retained
receipt is historical execution evidence for its named revisions, not a passing
foundation result or a measurement of this corrected revision. The correction
moves the shared implementation and all 21 helper tests into feature-gated core,
removes both upstream testkit edges, and preserves the measured admission and
scheduler case bodies apart from import paths. Testkit's remaining library counts
therefore change; the original receipt and its source identities are not rewritten.
