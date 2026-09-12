# Phase 2 canary outcome observation

`latent-telemetry::BoundedPhase2CanaryOutcomeWindow` collects bounded activation
outcomes for control-registered rollout cohorts. The activation manager now owns
capture through terminal publication. The [rollout coordinator](phase-2-rollouts.md)
and [canary evaluator](phase-2-canary-promotion.md) use this primitive with explicit
policies. There is no public outcome-submission RPC.
The implementation evolves the outcome classes, finite labels, bounds and tests
contributed in PR176.

## Registration and exact attribution

A trusted host creates the shared owner, calls `register(&CanaryWindowSpec)` and
retains the returned `CanaryWindow`. Its immutable identity contains tenant,
service, deployment, rollout ID, coordinator step and route generation. Up to
eight revision bindings contain the exact revision and canonical component
`ReleaseDigest`, plus the actual optional `PackageDigest`. Package associations
come from the trusted control owner; capture does not infer them from arbitrary
route attributes or independently verify publication authority. Trusted-local
content without a package uses `None`.

The owner assigns a non-reused process-local epoch to each registration. At most
one open window observes a tenant/service pair. Registration validates and makes
fresh bounded copies of strings and revision rows, dropping caller spare
capacity. An expired or explicitly closed window may coexist with a new window,
but their epochs and sample owners remain separate. A `CanaryWindow` grants only
access to its own readout. The rollout adapter authenticates tenant administrators;
supplying tenant text is never an authorization grant. Rollout windows also bind
an opaque control digest covering the catalog owner, exact rollout revision,
policy and compiled cohort; diagnostic windows may omit it.

Install `Some(owner.capture_handle())` in `LocalActivationServices.canary` before
constructing the activation manager. This is optional and independent of its
structured telemetry observer. The standalone node supplies the same repository
and coordinator hub when optional `rollouts.canary` settings are enabled. Its
clock is shared with activation capture. Otherwise the node leaves capture off.
The maintained integration fixture shows the complete host setup in
[`canary.rs`](../crates/latent-node/tests/activation_lifecycle/canary.rs).

## One accepted activation, one sample owner

The manager attempts capture once after accepting the activation into its
journal, using the existing unique manager/sequence observation token. The
returned `CanarySample` is affine: it cannot be cloned or deserialized. The
existing lifecycle binds it to the checked selected revision, records actual
admission, and consumes it only after accounting and the terminal journal
transaction finalize. Repeated phase refreshes cannot change the selection.
Completion never resolves the current route again.

The canary-only path does not clone the structured observer context or retain
payloads, principal claims, trace baggage, arbitrary diagnostics or cancellation
reasons. Its Invoke hooks use fixed counters, existing immutable slots, Arc
ownership and nonblocking `try_lock`; they do not insert allocating maps, wait
for a query/exporter, perform I/O or start tasks. Control registration allocates
the bounded slots and metadata. This adds no blocking acquisition to Invoke and
does not remove unrelated pre-existing observer/execution locks.

The five fixed outcome classes remain success, declared domain error, other
platform error, deadline exceeded and cancelled. The finalized terminal result
is authoritative: a cancellation request that loses to committed success still
counts as success. The collector does not decide whether a domain error is
healthy. Dropping a sample without terminal publication records loss before
releasing its live allowance; it never refunds execution budgets or changes the
activation result.

## Window membership and denominators

Registration begins a half-open monotonic interval of at most one hour. A
successful capture inside that interval remains in its original cohort even
when it finishes after the interval closes. `close()` stops new memberships
without waiting for existing samples. Snapshot/registration use the same bounded
registry gate; terminal bookkeeping becomes visible before the live count falls.
A retained sample cannot inject into a replacement window or release its slot
prematurely. Dropping the control owner retires the window and prevents its
retained readouts from becoming complete evidence.

`window.snapshot(required_samples)` returns a bounded owned readout with:

- exact immutable identity, epoch and revision/package/component bindings;
- total starts, selected/admitted starts, terminal and live counts;
- unattributed terminal and abandoned counts;
- per-revision selected/admitted/admitted-terminal counts and outcome classes;
- nine fixed latency buckets from acceptance-relative monotonic elapsed time.

Latency bucket upper bounds, expressed in microseconds, are 100, 1,000, 5,000,
10,000, 50,000, 100,000, 1,000,000 and 10,000,000; the ninth is overflow. Latency
includes all selected terminal outcomes, including selected admission failures.
Comparison uses the exact duration: an edge plus one nanosecond is above that
inclusive bound, without rounding it down to whole microseconds.
Wall-clock sample timestamps are not used to choose cohort membership.

The required count is for the whole cohort, not an implicit minimum for each
candidate. Consumers have separate revision counts to choose their denominators.
Resolution failure and pre-resolution abandonment are explicitly unattributed;
they cannot be fabricated as candidate successes or failures.

`CanaryCoverage` distinguishes `Open`, `Draining`, `NoSamples`, `Insufficient`,
`Incomplete` and `CompleteData`. Complete data requires closure, zero live owners,
complete selected terminal accounting, no known loss and the requested count.
It is not permission to promote. Early explicit closure can produce complete
diagnostic accounting, but cannot produce a full-duration sealed window.
A drained closed window with no calls remains
`NoSamples` rather than becoming a zero-error success rate.

## Loss, ownership and bounds

Sample/window/live capacity failures mark the affected window incomplete. A
failed registry try-acquisition cannot identify the affected window reliably,
so it advances a shared loss epoch. Every retained window spanning that epoch
is conservatively incomplete. A retained snapshot's `coverage()` may therefore
downgrade after it was taken; its counters remain the historical copy. Epoch
saturation or competing loss updates that cannot be recorded in one atomic
attempt set a permanent unknown flag for that shared owner. Creating a fresh
owner establishes a new observation domain, never restores old healthy evidence.

Terminal gate contention, missing correlation, unexpected selection changes and
unfinished Drop likewise never disappear as healthy missing samples. Counts of
unknown dropped calls are intentionally not guessed. Structured exporter loss
is independent: the affine capture path neither depends on exporter delivery nor
creates a durable audit record per Invoke. Rollout decision audit records belong
to the control owner and the separate [Phase 2 audit](phase-2-audit.md) journal.

| Resource | Default | Hard ceiling |
| --- | ---: | ---: |
| Retained windows (`maximum_series`) | 16 | 64 |
| Revision bindings per window | 8 | 8 |
| Captured starts per window | 10,000 | 1,000,000 |
| Starts across retained windows | 100,000 | 16,000,000 |
| Bytes per arbitrary identity string | 256 | 1,024 |
| Live sample owners | 4,096 | 65,536 |
| Concurrent owned snapshots | 4 | 16 |

The finite window/revision/string product also bounds retained metadata; hashes
have fixed canonical length. Fixed arrays bound counter/histogram storage. Slots
and captured-start charges remain retained while samples or snapshots own a
retired window. A snapshot cannot be cloned and retains a read allowance until
Drop. Control reads return bounded errors on contention or pressure. Query and
capture do not evict earlier samples to manufacture coverage. Public diagnostic
counter `total()` saturates for arbitrary literals; validated retained counters
cannot approach u64 overflow under these limits.

There is no worker, connection, timer, execution cell or guest Store per window,
and no unbounded sample log. After restart the data is absent and a new epoch is
required. Counters, identities and snapshots are host observation data, not trust,
eligibility or promotion capabilities. Only fixed outcome/coverage labels are
suitable metric dimensions; never export identifiers or digests as labels.

## Sealed observation and validation

`window.try_seal()` returns a private-constructed, non-cloneable
`SealedCanaryWindow` only after the complete interval, closed membership, no live
samples and no loss. An atomic live-attempt guard covers registry acquisition
through loss publication. The seal requires that frontier to be quiescent, so a
failed capture paused before publishing loss cannot disappear from the decision.
Registration captures its loss baseline before the interval starts.

A sealed window owns the same actual window slot and a snapshot allowance. Its
frozen counters do not change when later, unrelated captures lose data. The
catalog still verifies exact configured owner/control binding and policy itself;
possession of copied counters or a diagnostic assessment cannot mint this input.
Each attempted seal has a finite immediate result and creates no waiting task.

The small unit tests retain PR176's limits/fresh-ownership/label cases and add
success-to-cap followed by rejected failure, exact selection, live retirement,
snapshot ownership, gate contention, shared loss, missing terminals, epoch
separation, half-open membership and late terminal accounting. Actual activation
manager tests cover selected generation changes, finalized outcome categories,
cancellation, pre-poll abandonment and unchanged resource accounting without
running a guest compiler or load benchmark.

```bash
cargo test -p latent-telemetry --locked
cargo test -p latent-node --test activation_lifecycle --locked
```

The evaluator uses candidate-specific minimums and exact integer rate criteria,
and promotion rechecks catalog state and release eligibility at commit. Tests
also cover early closure, the delayed-loss frontier, registration loss ordering,
nanosecond threshold boundaries, real retained proof allowances and restart
without old positive evidence. Promotion remains operator-triggered.
