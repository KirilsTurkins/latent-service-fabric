# Fixed Rust HTTP/thread diagnostic

This is an opt-in `local-experimental-v1` host for one retained, byte-exact
Rust HTTP/ThreadPool component. The selected image is the separate
`rust_catalogue/combined-corrected-v1` set, not the historical failed image.
It does not enable the normal Rust builder,
qualify arbitrary Rust dependencies, or establish completion of #689 or #743.
Ordinary binaries still refuse the component and the diagnostic profile.

## Reproduce the signed witness

The branch workflow `rust-combined-signed-witness.yml` checks out and records
its exact source commit, verifies ordinary inspector refusal and explicit
fixed-image inspection, and retrieves only the authenticated members of the
corrected compiler artifact. `origin.json` binds its run, compiler job, source
commit/tree, recipe, capture, raw core, composition and framed component.
Compiler job `128393351609` in run `42369110799` successfully compiled the
corrected fixture, callback-safe pump and completed-EOF retirement from commit
`1d81c35ca6b206bafba113b6214de09bc6781bdb`. Both that job and its workflow
passed. Its 251 recipe inputs match the recorded source. Packaging checks the
original successful compile/composition commands and exact public surface; it
does not recompile the application or rewrite its compiler receipt.

The pinned archive is 67,919,611 bytes with SHA-256
`ba5b77a22012f22f503839470858383c6847783b7b04abd3614bf680d8c92210`.
Its 209 members passed independent CRC and whole-archive digest inspection.
The maintained retriever obtains only nine fixed, size- and hash-pinned members
and records that its archive digest check uses official metadata, not a claim
that the retriever downloaded the entire archive again. Expired or changed
artifacts fail; no other compiler run, attempt, graph or source is substituted.

The raw core is 999,654 bytes (SHA-256
`25ecfa4024c125f3c8829216c8c5211097d9f27a8ae86e8385ecfb6526ebfcca`).
The final graph is 1,306,998 bytes (SHA-256
`71e0d0bd5cd4be0578eff4ad0ee02dc0d40f3146bc5e373193f3cbc9b8d3fcef`),
and its frame is 1,654,366 bytes (SHA-256
`ab7c8e29be5745ff29fa5788ab13f3cc2bdde87da5033e41e9f804dcb3d83032`).
These identities grant no authority: the host still independently reconstructs
the transformed core against the unchanged original object catalogue and
checks the entire final graph before admitting its execution context.

The historical catalogue and failed compiler event `41926247914` are unchanged.
The active selector rejects the historical framed image; its accepted set is
replaced, not widened. Earlier callback, Golem-read and three-request deadline
failures remain failed observations. In particular, compiler run `42364782237`
had a successful compiler job but a failed ancillary source-check job; its
signed observation `42366341977` reached three requests before deadline.
Neither is relabelled by the separately compiled EOF-retirement correction.

A successful compiler, source verifier or native regression is not signed
execution qualification. The separately observed [signed result](#observed-signed-result)
passed the requirements below on its recorded source; each changed host still
requires its own maintained witness.

The controller builds with
`latentd/development-rust-http-combined,latent-packaging/development-rust-http-combined`,
packages and signs the corrected retained component, and starts one explicitly selected
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
build selects host optimization level 1 for cold preparation and keeps
`latent-component-threading` at level 3, alongside the existing managed-guest
compiler/parser optimizations. Host debug assertions and overflow checks remain
enabled. This is a diagnostic build choice, not a change to ordinary profiles,
Wasmtime guest optimization, or any preparation/activation deadline. The native
origin receipt records both host and verifier optimization levels. The host
still independently recomputes
the same source and final graph proof; no proof is cached outside its owned
preparation or skipped to satisfy the deadline. The overall
controller, process and peer lifetimes remain bounded, and there is no
invocation retry. An unknown RPC outcome fails even if later evidence appears.

The authenticated fixed graph uses both explicitly admitted child stacks and
engine-owned HTTP completion fibers. The combined controller explicitly sets
`nativeOwners` to ten: eight retained PAL/stack owners and capacity for two
concurrent HTTP completion fibers. This is a change to this diagnostic's host
capacity, not a successful qualification under the earlier eight-owner ceiling.
The ordinary HTTP fixture remains at eight; no ordinary default is changed.
The witness records the selected runtime limits alongside the configuration
identity. The [recorded signed run](#observed-signed-result) passed with this explicit
provisioning; it is not a general or certified minimum-owner bound.

All actual owners still share the same runtime Native ceiling and 16 MiB
activation ledger. Child admission still requires its separate native grant
and a distinct original Task; accepted child-start capacity is not recycled
on logical completion. Every actual mapping and its metadata remain charged
until physical drop, and cached child permits remain charged until Store
destruction. Other native-thread profiles keep refusing unadmitted stack
creation; a configuration name or package inspection cannot select this
combined path without the immutable final-graph proof.

HTTP invocation connection setup may wait behind the same client's one active
dial. This waits before allocating a socket or attempting protocol work, using
the already accepted request's original deadline, cancellation, authority, and
running-request ownership. The dial slot releases after setup, not after the
first response, so withheld response headers do not serialize independent
requests. Capacity exhaustion, backoff, poisoned ownership, and revocation still
refuse; an attempted dial or HTTP request is never replayed. Other callers of
the ordinary connection-admission API retain their immediate active-dial
refusal. The regression controls live in
`crates/latent-capabilities/src/broker/pools/client/admission/http_tests.rs`.

The original HTTP response headers stay withheld until the independent
sibling has consumed its partial body, parsed its first JSON response, and
issued the next ordinary request. Physical guest owners and real provider work
must be observed while the original request is held. A pass also requires
exact results, zero active provider counters, retired physical guest owners,
no foreign peer contact, deployment removal and clean node shutdown.

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
causal-order assertions are evaluated. Neither file is a success receipt.
The retained peer data excludes credential values; do not add raw request
headers or credential files to the artifact.

The separate `rust-combined-host-diagnostic.yml` owner checks source proof,
fixed-byte refusal, actual engine compilation and node selection. Those
checks are not a substitute for the signed witness. Its process RSS sample
is an observation, not proof of an adversarial memory ceiling. The 96 MiB
verification-work reservation remains provisional and diagnostic-only.


## Observed signed result

The maintained [signed workflow run 42371909980](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/42371909980)
passed on published source `a8dea35261e951f7bd3076f9129bd57aa3bc82ca`.
Both the outer programme and node witness report `passed` and
`actualSignedSiblingProgress: true`. This is separate from the earlier
same-tree preparation run `42371647596` and its local test commit.

The granted invocation returned the exact Waki/Golem result and consumed four
outbound requests, 1,161,924 fuel, 12,564,711 peak memory bytes and 57,957
microseconds of activation time. Those are observations, not new thresholds.
The original 5,000 ms, 16 MiB and one-billion-fuel guest limits remain unchanged.
The sibling's first JSON response completed before its second JSON request,
while the original response headers were still withheld. The native-grant
negative control returned a known permission refusal with zero guest fuel,
memory and outbound work; its cold preparation time was still accounted.

The controlled peer recorded four accepted requests, all connections closed
and no foreign contact. The final witness checked guest physical retirement,
zero active provider work, deployment removal and reaped clean node shutdown.
The selected host still used eight Tasks and the diagnostic-only ten Native
owners described above. This is not an eight-Native-owner qualification.

The retained [artifact 13574646336](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/42371909980/artifacts/13574646336)
is 1,943,808 bytes, with SHA-256
`ff6408af14052e6c4c07485b59b66d48a93e4e9673b6e33a2e0b4a47b2bb510f`;
all 162 ZIP members passed CRC inspection. Its original records are
`rust-combined-signed/witness.json` and
`rust-combined-signed/node/witness.json`. Artifact retention is finite, and
these historical identities do not turn a later missing artifact into a pass.

Normal builder support, arbitrary dependency support, full #689/#743
qualification and a universal physical verification-memory bound remain
explicitly unqualified. General CI and a future head's signed execution are
separate gates; this observation does not certify untested source.
