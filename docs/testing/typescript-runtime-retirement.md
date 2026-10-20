# Ordinary pending Promise retirement

The maintained compiler and signed-node gate covers the root
cancellation and retirement portions of issues #736 and #745. It does not
qualify the whole TypeScript runtime or change the runtime implementation.

`tools/typescript_runtime_retirement_fixture.py` creates an ordinary async WIT
export and an outside local npm package. Normal native npm locking, resolution
and exact review capture that package. The original package directory is
removed before compilation. The package uses ordinary `Promise`, `setTimeout`
and `clearTimeout`; it does not call an SDK scheduler or shutdown bridge. This
is a local outside package, not a published npm-package claim.

The explicit compiler gate needs the maintained CLOCK engine and its exact
input envelope, pinned compiler tools, and normal contracts/packaging tools:

```sh
python3 -B tools/typescript_runtime_retirement_fixture.py \
  --output "$RUNNER_TEMP/typescript-retirement" --tools "$TS_TOOLS" \
  --contracts "$CONTRACTS" --packager "$PACKAGER" \
  --engine "$CLOCK_ENGINE" --envelope "$CLOCK_ENGINE_INPUT"
```

The generated caller and synchronous fixture companion retain actual build
observations. With `LSF_GUEST_SDK_LANGUAGE=typescript` and
`LSF_GUEST_CAPSULES` pointing to that output, the existing native signed-node
suite can select this ignored case explicitly:

```sh
cargo test --locked -p latent-wasmtime --test local_service -- \
  --ignored --exact \
  runtime::typescript::signed_pending_promise_cancellation_deadline_and_timer_failures_retire_before_fresh_state
```

The separate default-false `qualify-runtime-retirement` workflow selector
reuses the authenticated 02f compiler products and CLOCK engine. It compiles
two fresh components with current tooling and genuine build observations,
then builds only the current `latent-wasmtime --test local_service` native
test target against the pinned lock. It does not rebuild the engine, the
historical native five, or the SDK distribution. The 25-minute job has a
20-minute command deadline and a 15-minute per-command ceiling. The existing
PR/push jobs and guest budgets remain unchanged.

The case signs and admits the actual products, waits for the original
Store/read-wait/broker pending-timer witness before root cancellation, and
checks `Cancelled`. The deadline invocation separately establishes the same
pending witness before its one-second original root deadline. A one-second
ordinary timer also establishes pending state before resolving its Promise
to 42. A third failure path observes the root-trap mode; a generic trap alone
does not prove callback execution or timer registration. Each outcome must retire the original
activation, Store, call and result owners before a fresh module returns 42.
All ten outcomes retain the original six backend owner counters, broker
calls/sessions/handles/results/buffers, read waits, quota activations,
instance reservations and cancellation registrations at the idle boundary.
The original runtime ceilings, five-second pending witness and two-second
physical-idle bound remain unchanged.

Focused source controls include actual native JavaScript execution of
the outside library with controlled timers. A bounded local normal npm
capture also passed with originals removed and the reviewed closure still
verifiable. These source controls are separate from the actual signed result.

[Run 39358519866, job 118418918078](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39358519866/job/118418918078)
passed at source `f25f3c455d5a713b2e087fdf27212b87cc36c00a`. The
[authenticated observation](evidence/typescript-runtime-retirement-signed-2026-10-20.json)
records both fresh component builds and all ten outcomes. Each of the three
pending witnesses observed one Store, one read wait and one broker call; all
fifteen counters were zero at every idle boundary. The original timer resolved
to 42, cancellation returned `Cancelled`, the original root deadline returned
`DeadlineExceeded`, and fresh invocations returned 42 after each terminal path.

The full recorded native source identity was recomputed from the exact Git
source: 3,293 files and 25,783,702 bytes. All eight named material rows and both
component/source/observation/package identities match the artifact. The later
strict reader independently accepted exactly one named libtest case with
47 filtered cases against the authenticated frozen registry. Current
development adds an unrelated Go synchronization test, so a future fresh
selection has 48 filtered cases; the historical result retains its original
registry. The final composition preserves all exercised TypeScript and native
production inputs; only the independent Go test files differ in the native
source scope. Historical compiler ancestry remains 02f/2cd, and the CLOCK
engine envelope remains unchanged. No historical receipt is rebound to the
composition. Synthetic reader controls remain separate from signed evidence.

An accepted callback error has a distinct source/reference mode, but the
native case does not use a generic trap to infer that callback's origin.
Cross-tenant state, late-wake races, exhaustion, fairness, callback drain and
the remaining shutdown/accounting matrix still require separate actual
evidence. Both issues remain open.
