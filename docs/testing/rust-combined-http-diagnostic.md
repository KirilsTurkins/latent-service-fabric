# Fixed Rust HTTP/thread diagnostic

This is an opt-in `local-experimental-v1` host for one retained, byte-exact
Rust HTTP/ThreadPool component. It does not enable the normal Rust builder,
qualify arbitrary Rust dependencies, or establish completion of #689 or #743.
Ordinary binaries still refuse the component and the diagnostic profile.

## Reproduce the signed witness

The branch workflow `rust-combined-signed-witness.yml` checks out and records
its exact source commit, verifies ordinary inspector refusal and explicit
fixed-image inspection, and retrieves only the authenticated members of the
original compiler artifact. The original compiler run remains recorded as a
failure; the diagnostic does not rewrite that result as a successful build.
The artifact must still be retained by GitHub. An expired or changed artifact
is an input failure, not permission to substitute another component.

The controller builds with
`latentd/development-rust-http-combined,latent-packaging/development-rust-http-combined`,
packages and signs the retained component, and starts one explicitly selected
`rust-context40-combined-http-diagnostic-v1` node. It first omits the native
thread grant and requires a known terminal permission refusal, zero guest
consumption, and no peer contact. It then independently grants the four
capabilities and runs the ordinary two-pool HTTP programme.

The guest budget remains 5,000 ms, 16 MiB, 1,000,000,000 fuel and eight outbound
requests; the successful programme must consume exactly four requests.
Provider policy ceilings are unchanged. The diagnostic controller alone uses
a finite 120,000 ms invocation RPC wait to include cold proof/compilation and
terminal result delivery. This is not extra guest execution time: cold
preparation still consumes the original activation deadline. The diagnostic
build additionally optimizes `latent-component-threading` at level 3, alongside
the existing managed-guest compiler/parser optimizations, while preserving
host debug assertions and overflow checks. It still independently recomputes
the same source and final graph proof; no proof is cached outside its owned
preparation or skipped to satisfy the deadline. The overall
controller, process and peer lifetimes remain bounded, and there is no
invocation retry. An unknown RPC outcome fails even if later evidence appears.

The original HTTP response headers stay withheld until the independent
sibling has consumed its partial body, parsed its first JSON response, and
issued the next ordinary request. Physical guest owners and real provider work
must be observed while the original request is held. A pass also requires
exact results, zero active provider counters, retired physical guest owners,
no foreign peer contact, deployment removal and clean node shutdown.

## Read failures without treating them as passes

`FAILED.json` records the failing stage. The `controls` directory retains the
actual CLI result, including uncertain outcomes. `rust-thread-http-peer-refusal.json`
retains the bounded controlled-peer observation when the causal gate refuses;
`rust-thread-http-terminal.json` retains a completed invocation before its
causal-order assertions are evaluated. Neither file is a success receipt.
The retained peer data excludes credential values; do not add raw request
headers or credential files to the artifact.

The separate `rust-combined-host-diagnostic.yml` owner checks source proof,
fixed-byte refusal, actual engine compilation and node selection. Those
checks are not a substitute for the signed witness. Its process RSS sample
is an observation, not proof of an adversarial memory ceiling. The 96 MiB
verification-work reservation remains provisional and diagnostic-only.
