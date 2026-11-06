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

The authenticated fixed graph uses both explicitly admitted child stacks and
engine-owned HTTP completion fibers. Both draw from the same finite Native-owner
ceiling and the same 16 MiB activation ledger. The controller explicitly selects
12 Native owners for this diagnostic; ordinary fixtures and defaults remain at
eight. Native counts include guest pool/TLS ownership as well as physical stacks:
the investigation observed nine simultaneous Native owners with four mapped
stacks. That observation motivates this finite operator selection, not a universal
bound or extra guest memory. The receipt records the selected count. Child admission still requires its
separate native grant and a distinct original Task; accepted child-start capacity
is not recycled on logical completion. Every actual mapping and its metadata
remain charged until physical drop, and cached child permits remain charged
until Store destruction. Other native-thread profiles keep refusing unadmitted
stack creation; a configuration name or package inspection cannot select this
combined path without the immutable final-graph proof.

The original HTTP response headers stay withheld until the independent
sibling has consumed its partial body, parsed its first JSON response, and
issued the next ordinary request. Physical guest owners and real provider work
must be observed while the original request is held. A pass also requires
exact results, zero active provider counters, retired physical guest owners,
no foreign peer contact, deployment removal and clean node shutdown.

## Concurrent cold HTTP connections

The HTTP invocation path uses `reserve_connection_serialized` for a call's first
connection reservation. If another accepted call is still dialing the same
provider client, the second call waits under its existing absolute deadline and
cancellation owner. It has no connection, socket, dial task, or extra request
charge during that wait. A successful preceding dial allows a separately charged
connection; a failed preceding dial retains backoff. Actual capacity exhaustion,
poisoned ownership and authority loss still fail closed. Only pre-dial admission
is reconsidered: no request, connection attempt, or protocol work is replayed.

The original immediate and bookkeeping-only admission APIs remain strict;
deferred and maintenance requests do not select this path. Regression controls
exercise two independent real sockets, one concurrent dial, capacity refusal,
original deadline, cancellation, abandoned waits, failed-dial backoff and poison.
The unchanged signed witness separately requires real sibling HTTP progress
while the first request's response remains withheld.

## Stack-boundary review

The combined selection does not change `mmap`, guard-page protection, `munmap`,
or failed-unmapping quarantine. The allocator's only change is the
feature-gated safe `combined` module. The worker implementation changes its
profile description, not its allocation or refund operations. The new selector
checks the prepared component's immutable proof before creating the context,
then passes the same activation budget and runtime ledger to both admission
paths. Child starts retain their distinct Task requirement and total-start bound;
worker mappings retain a live parent and prepay their original Native, memory,
and metadata charges. Refund still follows successful unmapping, and cached
child permits still require the Store-drop fence.

`tools/native_loader_boundary.py` records these reviewed source identities,
including the combined selector, without adding an unsafe allowance. Its mutation
controls reject removed or substituted proofs, substituted ledgers, expanded
limits, and added unsafe code. Native regressions separately execute proof
refusals, shared-limit admission, allocation rollback, duplicate child starts,
actual nested engine fibers, and physical retirement. The source tripwire is
not a replacement for these behavioral tests or the signed witness.

## Read failures without treating them as passes

`FAILED.json` records the failing stage. The `controls` directory retains the
actual CLI result, including uncertain outcomes. `rust-thread-http-peer-refusal.json`
retains the bounded controlled-peer observation when the causal gate refuses;
`rust-thread-http-terminal.json` retains a completed invocation before its
causal-order assertions are evaluated. `rust-thread-http-terminal-peer.json`
retains the final scoped peer observation even when no gate became ready. These
files are observations, not success receipts; recording cannot release gates,
retry invocation, extend its deadline, or replace the original failure.
The retained peer data excludes credential values; do not add raw request
headers or credential files to the artifact.

The separate `rust-combined-host-diagnostic.yml` owner checks source proof,
fixed-byte refusal, actual engine compilation and node selection. Those
checks are not a substitute for the signed witness. Its process RSS sample
is an observation, not proof of an adversarial memory ceiling. The 96 MiB
verification-work reservation remains provisional and diagnostic-only.
