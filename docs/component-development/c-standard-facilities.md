# C standard clock and entropy profile

The opt-in `c-standard-clock-entropy-v1` compiler profile ports the pinned Zig
0.16.0 WASI libc clock and entropy calls onto existing typed LSF providers. It
does not install an ambient WASI host. The compiler selects the maintained port
automatically beneath ordinary application and dependency calls.

**Qualification: signed-node qualification for this finite profile.** The
[recorded corrected programme](../testing/evidence/c-standard-facilities-passed-2026-10-16.json)
passed all 38 expected invocation outcomes on the captured ordinary native tuple.
Source, compiler, component and retirement identities remain bound to that
receipt. This profile does not
complete [resource and runtime facilities #681](https://github.com/KirilsTurkins/latent-service-fabric/issues/681)
or [C runtime #744](https://github.com/KirilsTurkins/latent-service-fabric/issues/744).

The maintained contributor qualification captures a new outside-checkout
library using ordinary libc calls, removes its original sources, builds all
five existing C authoring controls and signs them on an explicitly selected
ordinary native tuple. It adds sequential missing-grant observations and eight
finite clock/entropy error and budget probes to the existing node suite. Run
as an unprivileged user on the supported Linux compiler host with the pinned
tools and bubblewrap containment:

```bash
python3 tools/qualify_c_standard_facilities.py \
  --native-directory "$NATIVE" --native-tuple "$NATIVE/native-tuple.json" \
  --zig "$C_TOOLS/zig/zig" --wit-bindgen "$C_TOOLS/wit-bindgen" \
  --wasm-tools "$C_TOOLS/wasm-tools" --output /tmp/c-standard-qualification
```

This explicit disposable test setup grants random byte input/output ceilings
of 128 and 65,536 bytes to exercise the provider's existing activation limit;
it does not change application budgets or install application grants. All
original authoring cases and failed attempts remain part of the result.
The same qualifier accepts `--build-native` instead of the two native input
arguments. The separate C standard-facilities CI job uses that mode to capture
default-feature native products from its own tested commit; it retains public
node observations without copying private node configuration or signing keys.

Set `runtimeProfile` in the captured `capsule-project.json` to
`c-standard-clock-entropy-v1`. If the application has a dependency lock whose
selection declares a runtime profile, select the same profile and resolve and
review that lock again. Existing projects default to `closed-synchronous-v1`.
The profile change changes source and runtime selection identities; it does
not install providers or grant authority.

| Ordinary API | Port and finite semantics |
| --- | --- |
| `clock_gettime(CLOCK_MONOTONIC, ...)` | Full-width `latent:clock/monotonic@0.1.0` nanoseconds; no truncation through milliseconds. |
| `clock_gettime(CLOCK_REALTIME, ...)` | `latent:clock/wall@0.1.0` Unix milliseconds, checked multiplication to nanoseconds; effective resolution remains one millisecond. |
| `clock_getres(CLOCK_REALTIME, ...)` | One millisecond, reflecting the selected wall contract. |
| Other raw WASI clock IDs; monotonic `clock_getres` | `ENOTSUP`; the provider contract does not declare monotonic resolution or CPU clocks. |
| POSIX `CLOCK_PROCESS_CPUTIME_ID` | The pinned libc does not declare this constant; an ordinary source use fails compilation. The actual retained failure is separate from the raw WASI runtime-denial probe. |
| `getentropy(buffer, length)` | The pinned libc enforces its 256-byte limit; accepted requests use genuine `latent:random/random@0.1.0` bytes. |
| Lower-level WASI `random_get` | At most 4096 bytes per call. Zero length requires no host call. Invalid memory is rejected before dispatch. |
| Entropy errors | Invalid length maps to `EINVAL`, provider budget exhaustion to `EAGAIN`, and unavailable/invalid provider output to `EIO`; no fabricated bytes. |

The compiler adds `_POSIX_C_SOURCE=200809L` and `_DEFAULT_SOURCE` only when the
captured dependency defines do not already select those feature macros.
It derives a fresh WIT world with monotonic, wall and random imports from the
captured original; generated application bindings, derived contracts, package
inputs and runtime selection bind that transformation. The SDK binding check
and original-source recheck remain separate. Neither original WIT nor the
vendored SDK is edited during compilation.

The [first hosted qualification failure](../testing/evidence/c-standard-facilities-failed-2026-10-16.json)
records the unavailable POSIX CPU-clock declaration. The replacement runtime
probe calls the pinned raw WASI clock API with CPU-clock ID 2, requires
`ENOTSUP`, and verifies that its output remains unchanged. This does not add a
POSIX CPU clock or turn the original compiler rejection into a pass.

The later native attempt compiled all five C applications and reached signed
node execution. Its ungranted clock activations were rejected before guest
execution. The random-grant probe incorrectly expected a guest declared error;
the corrected probe requires the original rejected admission receipt for every
ungranted capability, with known outcome and zero guest fuel and memory. Failed
denial observations are retained before assertions. The [corrected native programme](../testing/evidence/c-standard-facilities-passed-2026-10-16.json)
passed all 38 invocations: three rejected grant admissions, eight facility
checks, and the 27 existing tutorial and recovery cases. The five ordinary
default native products, compiler inputs and actual components are digest
bound. The source library was removed before compilation. Provider idle checks,
clean node shutdown, compiler retirement and all three held peer connections
were confirmed within the original limits. This is an isolated signed fixture;
it does not claim authenticated publisher access or a production release.

The initial profile supports one selected lower-kebab-case world declaration
in a root WIT file. Explicit profile imports in that file, duplicate world
declarations and ambiguous selection are rejected. The real WIT parser and
final component inspection remain authoritative. Missing provider or grant
follows the existing host failure path; a clock call is not replaced with zero
or a requested duration.

Logging, stdio buffering and flush, filesystem and process environment,
CPU-time emulation, pthreads, sockets, concurrent callbacks and persistent
workers are outside this profile. No larger execution budget is implied.
See the [C authoring guide](c-authoring.md) and
[library compatibility and runtime selection](library-compatibility.md).

The separate [standard stdio logging profile](c-standard-logging.md) selects
only the bounded log contract; it does not implicitly select these clocks or
entropy providers.

## Derived WIT source handling

The maintained C standard-profile derivation identifies the selected world and
profile-owned imports in a same-offset lexical view. Line comments, nested block
comments and quoted literals cannot impersonate declarations or imports. Comments
between tokens remain whitespace, following the [WIT lexical structure](https://github.com/WebAssembly/component-model/blob/main/design/mvp/WIT.md#lexical-structure).
The derived file retains the original text and inserts only the selected profile's
imports at the actual world opening. Captured application/platform files are not
modified. Real duplicate imports and ambiguous worlds still fail; unterminated
comments or strings fail before a derived directory is published.

This preliminary selection is not a replacement WIT parser: the pinned generator
and component validator still enforce the actual contract. It adds no provider,
grant, WASI fallback, scheduler or ordinary C HTTP implementation. The focused
source controls qualify derivation only. Fresh C compiler/signed component
execution of this changed recipe, the two ordinary unchanged default clients,
readiness, ownership and the full #690 conformance matrix remain unqualified.
