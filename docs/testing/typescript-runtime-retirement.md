# Ordinary pending Promise retirement inputs

This branch prepares a current compiler and signed-node gate for the root
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

The case signs and admits the actual products, waits for the original
Store/read-wait/broker pending-timer witness before root cancellation, and
checks `Cancelled`. The deadline invocation separately establishes the same
pending witness before its one-second original root deadline. A third path
checks a root trap after accepting a timer. Each outcome must retire the original
activation, Store, call and result owners before a fresh module returns 42.
Every idle boundary also checks all five original backend owner counters and
the original read-wait counter are zero.
The original runtime ceilings, five-second pending witness and two-second
physical-idle bound remain unchanged.

Three source controls pass, including actual native JavaScript execution of
the outside library with controlled timers. A bounded local normal npm
capture also passed with originals removed and the reviewed closure still
verifiable. Neither result proves emitted-component execution. Compiler and
signed native execution are pending. The CLOCK build also needs the verified
native-world/application-import separation repaired by #1148; no historical
build observation may be relabelled as a current one.

An accepted callback error has a distinct source/reference mode, but the
native case does not use a generic trap to infer that callback's origin.
Cross-tenant state, late-wake races, exhaustion, fairness, callback drain and
the remaining shutdown/accounting matrix still require separate actual
evidence. Both issues remain open.
