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

Low-level dev-dependencies select:

```toml
latent-testkit = { path = "../latent-testkit", default-features = false }
```

The default `runtime` feature preserves the old conformance, node harness and
crate-root interfaces for existing callers. Only that feature enables the
optional activation/executor/node/telemetry dependencies. Neutral clocks and
coordination require neither the node binary, Wasmtime, nor provider crates.
No production dependency is added to admission or scheduler.

```sh
python3 tools/check_testkit_dependencies.py
cargo test -p latent-testkit --no-default-features --lib --locked -- --test-threads=1
cargo test -p latent-testkit --no-default-features --lib --locked -- --test-threads=4
cargo test -p latent-admission -p latent-scheduler --lib --locked
cargo test -p latent-testkit --lib --locked
```

The graph check inspects independently selected Cargo dependency trees, not the
all-feature workspace union. The tests cover fixed IDs, explicit wakeups, missing
readiness, stale/recycled/foreign tickets, premature retirement, buffer ownership,
capacity limits, abort, panic and real watchdog expiry. Both current-thread and
multi-thread Tokio runtimes exercise the controlled scripts. Existing ignored
resource/qualification tests remain ignored in ordinary unit runs and keep their
separate explicit entrypoints.

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
