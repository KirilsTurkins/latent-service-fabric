# Phase 2 canary outcome observation

`latent-telemetry::BoundedPhase2CanaryOutcomeWindow` is the initial shared
observation contract for attributing bounded canary outcomes to one exact
single-node rollout candidate. It is a Phase 2 foundation for #152 and later
#154 integration; it does not implement rollout policy, promotion, persistence,
or a public management API.

## Attribution and ownership

Each series is keyed by the exact tenant, service, rollout identity, revision,
and route generation. These values remain query/attribution identities and are
not exported as metric dimensions. Outcome and coverage labels are fixed enums,
so an integration can emit bounded-cardinality counters without creating a time
series per tenant, service, digest, revision, rollout, or external error string.

The window is a shared node-owned object. It creates no worker, listener, timer,
connection, execution cell, guest Store, or service-specific background loop.
The rollout owner creates and retires the window as part of its bounded stage
lifecycle.

`snapshot_tenant` requires the caller-authorized tenant to match the requested
identity. The identity itself is not an authorization capability. All retained
string-backed identity fields are length checked and copied into fresh bounded
ownership so caller-controlled spare capacity is not retained.

## Missing and incomplete samples

A query always supplies a non-zero required sample count. A series with no
observations returns `Phase2CanaryCoverage::NoSamples`; fewer than the required
samples returns `Insufficient`. Only a series meeting the caller's declared
sample count returns `Ready`.

`Ready` means only that enough attributed observations exist. It is not a
promotion decision and does not classify the observed success/failure mix as
healthy. Canary policy remains the responsibility of the rollout/evaluation
owner. Missing samples are therefore never silently converted into successful
samples.

The fixed outcome classes are success, declared domain error, platform error,
deadline exceeded, and cancelled. Arbitrary error messages or external response
strings are intentionally not retained by this contract.

## Bounds and failure behavior

Configuration independently bounds:

- retained attribution series,
- samples accepted per series,
- samples accepted by the whole window, and
- bytes in each string-backed identity field.

Hard implementation ceilings and checked aggregate identity accounting reject
pathological configurations before allocation. Capacity exhaustion rejects the
new observation with `ResourceExhausted`; existing counts are not evicted or
relabelled to manufacture coverage. Counter overflow also fails closed.

The window retains only aggregate counters plus first/last observation times,
not an unbounded sample log. Durable audit history belongs to the separate #152
audit work; feature owners must emit their audit records independently rather
than treating these aggregate canary counters as an audit trail.

## Integration boundary

The current slice deliberately has no dependency on the unmerged Phase 2 audit
journal. Later rollout/canary integration should:

1. record only outcomes that can be attributed to the exact pinned candidate
   revision/generation;
2. keep rollout policy thresholds separate from observation collection;
3. treat telemetry/audit loss or unavailable outcome attribution explicitly
   rather than as healthy evidence;
4. emit only fixed low-cardinality metric dimensions; and
5. preserve the existing activation outcome and resource accounting semantics.

Durable persistence, audit/export sinks, rollout wiring, cancellation/shutdown
integration, and the final canary evaluator remain follow-up Phase 2 work.

## Validation

Focused unit tests cover exact attribution and counts, explicit no-sample and
insufficient coverage, tenant query isolation, bounded/fresh identity retention,
series/sample capacity exhaustion, pathological configuration rejection, and
the fixed exported label vocabulary.

```bash
cargo test -p latent-telemetry --locked
```
