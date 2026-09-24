# C# capsule qualification

This is developer execution evidence for #549, separate from the beginner
[C# authoring guide](../component-development/dotnet-authoring.md). It does not
authorize a release or replace human newcomer review #345. The complete finite
qualification and its clean-source repeat passed at the sources recorded below.
Final delivery still requires the integrated development base and all exact-head
PR gates to pass.

## Supported experiment

The compiler host is Linux x86-64 with .NET SDK 10.0.100, Componentize.NET SDK
and WitBindgen 0.8.0-preview00011, NativeAOT LLVM 10.0.0-rc.1.26306.1,
WASI SDK 29.0, wit-bindgen 0.62.0 and wasm-tools 1.254.0. The maintained project
enables trimming, invariant globalization, single-threaded execution and no
application dependencies or MSBuild overrides. The six NuGet packages are
locked by exact version and verified content hash. Signed NuGet content is
verified with the pinned SDK's package reader, not a raw signed-ZIP digest.

The independent source capture includes handwritten C#, authoritative WIT,
vendored SDK, generator and runtime inputs. Compiler, runtime, reference-pack,
NuGet and WASI input inventories are compared before and after each build.
Generated bindings are regenerated independently and compared with the actual
NativeAOT compiler's bindings. Build observations deliberately remain
operator-asserted, non-hermetic, dependency-incomplete and not reproducibility
claims. Production package validation compares the compiled contract with WIT.

The closed runtime retains only the explicitly declared monotonic-clock import
needed by GC. It grants no ambient files, sockets, wall time or entropy. Each
activation owns its managed heap and task objects; dormant deployments have no
CLR process, OS thread, listener, event loop, execution cell or guest heap.
The supported guest ceiling is 128 MiB, one billion fuel and 120 seconds for a
cold invocation. Deliberately multi-operation SDK tests use ten billion fuel.
These are finite experiment bounds, not throughput or production sizing claims.

## Successful finite qualification

[Run 35934374519](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35934374519)
repeated the complete qualification successfully at
`f8fff6bb1f0e854e6caff3a577848bd87a12a883`. Artifact `10782987086` contains all ten
SDK cases, 27 signed-node invocations, 24 resource observations, the 5/9/17 dormant
populations and all six printed Bash steps. The node and HTTP peer shut down
cleanly, all three held HTTP operations closed and no unexpected requests occurred.
Independent Git comparison verified 2,341 captured inputs, including exactly the
tracked SDK sources: zero generated build or Python-cache outputs were included.
The source and execution-tool inventories remained unchanged before and after
qualification. The runtime digest is
`sha256:5e68470fa3a4985748fe90586981b8c2a88c126a59d8f799328327cdffa1bf15`
(2,181 files, 13,680,816 bytes), and the qualification marker digest is
`sha256:ac9f38c9d50e03533639125b568352e12c495c5234278b21212f6ff486b46eb0`.
The separate immutable archive matched all 4,084 expected Git blobs and modes,
SHA-256 `1f9b9dd15268c62bd0a6536be4dc87c9c5178566252c717876401922b586b03f`.

The same head's broader CI run `35934375368` separately failed the unchanged
small-WAT concurrent local-service acceptance case in the Phase 3 security matrix.
The existing wrapper retained only `command-exit`, not the assertion details;
that gate is not claimed green and its cause is not inferred from the successful
.NET qualification. Final integrated CI must pass it with bounded failure
diagnostics available.

The later integrated head `0c08d3f175f8cb58546208abe7f797cd27d6b61b`
failed [run 35938546333](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35938546333)
at the printed guide's final `deployment delete`. Artifact `10783703577`
retains the complete attempt. All ten SDK cases and the separate signed-node
workload passed: 27 invocations, 24 samples, the 5/9/17 dormant populations and
clean node/HTTP-peer teardown. The guide also built, published and deployed its
component and returned both expected greeting answers. Its deletion returned
public `resource-exhausted`, with `requestDispatched: true` and
`outcomeKnown: true`; no deletion was retried. The retained catalog still
contains the deployment at generation 2. The exit trap stopped the guide's node
cleanly, but that is not successful deployment cleanup or guide qualification.

No delete attempt appears in the seven retained audit records. The last two
records are the valid invocation's monotonic-clock grant/outcome observations,
immediately before the rejected cleanup. The guide configures eight audit queue
operations, which derive a 32 KiB byte allowance; each observation and a new
control reservation occupy 16 KiB of that allowance until physically released.
This supports audit-byte pressure as an explanation, but the private rejection
reason was not retained and is not claimed proven. The source archive matches
all 4,102 selected Git blobs and modes, SHA-256
`37b335092e4d1aac855669e92c7594c98f07cd3ca7128d123b908ae6cb70fed8`.
The failed attempt remains a failed gate regardless of earlier successful runs.

The guide now makes bounded read-only observations of audit ownership before
issuing its one deletion. Existing queued-byte, durable staging and recovery
state are exposed through matching server/CLI counters; missing, malformed,
closed or recovery-pending observations fail closed. The observation has a
five-second deadline, at most 32 reads and finite process/output cleanup bounds.
It neither reserves future capacity nor changes journal quotas, policy, leases
or deletion checks. Local tests cover these boundaries; the deterministic
two-observation/32 KiB journal regression and full guide still require Linux CI
at the new source. This correction is not a retroactive pass for the failed run.

The following first-success measurements remain tied to their original source,
not to the later integration head.

[Run 35932426366](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35932426366)
passed at `57fbc36690d9ccad65b6a18d2c49a4188e1ff061`. Artifact `10782416468`
retains five standalone builds, nine actual SDK builds, seven ownership checks,
all ten admitted SDK cases (78.33 seconds), 27 signed-node invocation receipts,
24 resource observations, 123 recorded control calls and all six printed Bash
steps (22.29 seconds). Typed results, secret alias zeroization and closed owners,
allowed/denied HTTP, trap, fuel/memory exhaustion, deadline, cancellation,
disconnect, fresh subsequent state and final deployment deletion passed.
The node and HTTP peer were reaped cleanly; all three held HTTP operations closed,
with no unexpected requests or remaining activation/provider/compiler owners.

The runtime source identity is
`sha256:f6ae16771985517c7a3acecb542f2ad98b9b9683f8663c6d3b466a87b20c6c2a`
(2,180 files, 13,671,845 bytes). Independent Git-blob comparison verified 2,340
runtime/SDK/WIT/schema/helper/guide inputs. The immutable source archive separately
matched all 4,083 expected files and executable modes (SHA-256
`f30b75bf8eaaf18a6cb6d7516334e6b8b275861cb4712e0b00615734879a4406`).
The qualification marker digest is
`sha256:41b2b076737de5a88d3dab2e1102f8102504df8d0f35c3f71ba69b3be6be6c0b`;
the source and tool inventories remained unchanged through node and guide execution.

The first receipt's SDK inventory also records 74 generated probe `bin`/`obj`
and Python-cache outputs (26,009,700 bytes). These are explicitly not Git source
inputs. The workflow now builds that diagnostic probe in its own temporary
directory and disables Python bytecode writes, so the final SDK source inventory
must match the reviewed tree exactly without an output exception.

Node startup measured 55.17 ms. Word-count and shipping cold requests took
2,927.95 and 2,914.49 ms; their warm repeats took 23.78 and 23.87 ms.
The first recorded greeting was already warm after the explicit runtime-grant
denial check and is not a cold-compilation measurement. Ordinary activations
peaked at 54,067,200 charged guest-memory bytes. The memory-exhaustion case
reached 121,765,888 bytes within the 128 MiB ceiling and the following fresh
invocation succeeded. The fuel-exhaustion receipt charged exactly one billion.

| Observation | Processes / threads / listeners | Node RSS bytes | Active cells / cache entries |
| --- | --- | --- | --- |
| Empty node | 1 / 8 / 1 | 56,139,776 | 0 / 0 |
| 5 dormant deployments | 1 / 7 / 1 | 67,682,304 | 0 / 0 |
| 9 dormant deployments | 1 / 7 / 1 | 67,686,400 | 0 / 0 |
| 17 dormant deployments | 1 / 7 / 1 | 67,686,400 | 0 / 0 |
| Held HTTP activation | 1 / 8 / 1 | 176,046,080 | 1 / 2 |
| After cancellation | 1 / 8 / 1 | 125,153,280 | 0 / 2 |
| After all deployment deletion | 1 / 7 / 1 | 125,169,664 | 0 / 2 |

Each dormant population has three settled samples, zero application-owned
resources and no active activation, quota or execution-cell ownership. Shared
compiled images remain bounded at two entries and one preparation; they are not
per-deployment heaps. RSS is a non-atomic process observation, not an allocator
release guarantee, and deleting deployments does not promise that RSS becomes
the initial baseline. Clean shutdown joined the fixed compiler/cleanup workers.

Standalone captured builds took 15.88–16.27 seconds including source inventories,
binding checks and packaging. The larger 5,050,538-byte diagnostic component
compiled in 13.79 seconds with maximum compiler RSS of 305,296 KiB; its separate
cold-backend probe prepared in 35.99 seconds. That diagnostic is distinct from
the managed node's cold/warm observations above. None is a throughput, 100k-scale
or arbitrary-.NET-application qualification.

## Retained earlier attempts

[Run 35919449058](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35919449058)
at `7a69352177fee84c2edf1d976fcd0e3523797aab` passed the initial actual-compiler
and clock/fresh-heap diagnostics, but its standalone builder incorrectly
compared raw signed archive bytes with NuGet's normalized content hash. The
locked content was not changed; verification now uses the signature-aware
reader supplied by the exact .NET SDK.

[Run 35921141813](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35921141813)
at `1e56de8cb573c81e057df839b42845bccc455dca` passed both NativeAOT backend
diagnostics and built the standalone greeting from its captured source. The
probe compiler took 6.57 seconds with 188,212 KiB maximum compiler RSS. Its
2,288,059-byte component prepared cold in 13.36 seconds; observed echo/wide
activations peaked at 54,067,200 guest linear-memory bytes. Those measurements
describe this probe and runner, not whole-node RSS or arbitrary C# applications.

That run failed closed during package inspection at the conservative component
reference-work limit. A bounded native diagnosis measured 1,304,239 conservative
reference visits but only 11,921 actual binary/type visits, 2,488 functions and
293,022 operators in the 2,292,496-byte greeting. Whole-instance alias summaries
account for the difference. Reference expansion now has an independent finite
2,097,152 ceiling; actual type/allocation work remains capped at 262,144 and
depth remains capped at 64. All 71 packaging unit tests and inspection of the
retained actual greeting pass locally. Linux qualification must still validate
the final source; this local inspection is not node execution evidence.

## Earlier SDK and node failures

[Run 35929987442](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35929987442)
at `c844116196341fdb373f3bcbca6a61499ed189a8` passed all ten admitted SDK
cases in 97.14 seconds, including the actual compiled secret alias-zeroization,
preserved-copy, repeated-disposal and use-after-close assertions. The nested
service returned successfully cold in 7.538 seconds and warm in about 16 ms.
Each caller/callee activation peaked at 54,067,200 charged guest-memory bytes;
the parent receipt includes 108,134,400 aggregate bytes. These are this runner's
observations, not throughput or whole-process RSS guarantees.

The enforced node reached dormant populations of 5 and 9 with one process,
seven threads, one listener and no active activation/cell ownership. Applying
`dormant-09` then failed closed with `signature-stale-proof`: the isolated demo
signer's 60-second proof age contradicted its 30-minute signed experiment.
Artifact `10780739918` preserves that failed run; the 17-deployment, invocation,
cleanup and printed-guide stages were not qualified by that attempt. The exact source archive
independently matched all 4,082 expected Git blobs (archive SHA-256
`da8aa0ff351fcb26809ecb699d7f7c3967f43f639f61674836b77d191c08dde4`).
The broad Rust gate also caught a shared test-module dependency, now corrected
by passing the explicit admission-memory ceiling from its caller. Its failed
CI is not treated as passing delivery evidence.

The isolated demo signer now aligns both proof-age ceilings with its existing
1,800-second signature lifetime. Real cryptographic regressions check positive
proofs at 61, 900 and 1,799 seconds, exact rejection at 1,800, and independent
enforcement of a shorter publisher or builder proof age. This does not change
production policy defaults, revocation/currentness enforcement or the finite
five-second durable clock lease. The successful full run above includes this
correction through the node and printed-guide stages.

[Rust regression run 35932426453](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35932426453)
at `57fbc36690d9ccad65b6a18d2c49a4188e1ff061` reached dormant populations
5, 9 and 17 and passed all four greeting invocations. The first word-count
invocation then failed closed with `admission-authority-busy`, a known outcome
before execution with zero fuel, memory and effects. Artifact `10782136500`
retains this attempt. The authority intentionally rejects currentness checks
while its fence is held; the qualification does not retry that request or relax
the fence. A new isolated final-head run must pass the complete regression.

[Run 35928271057](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35928271057)
at `79ef782ab9f3440baa10123a3581ed727c875c87` passed the expanded actual
NativeAOT probe, all five standalone and nine SDK builds, seven ownership
checks and eight of ten SDK runtime tests. The secret success/typed-error
diagnostic and actual secret/streaming cases passed. Artifact `10780656604`
retains two admission failures: the nested caller declared its required
256 MiB ceiling, but the signing fixture still advertised a 128 MiB runtime.
The fixture now uses the same explicit nested-service ceiling as the node
composition; ordinary package profiles remain at 128 MiB. No production
delegation rule or authority is widened. The successful full run above includes
the nested service and complete signed-node/printed-guide stages.

[Run 35926712630](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35926712630)
at `2a2e131d1a51971cfc24eb792fea5323240114f1` executed the actual full-width
and aggregate value cases successfully. Its declared-error probe returned the
correct typed error, but the test used a success-only assertion. Artifact
`10779557766` retains that harness failure. The assertion now checks the error
category and exact payload separately. A local diagnostic of that unchanged
compiled component also traced member lookup through `String.GetHashCode`
to the closed runtime's ambient-entropy denial. Reflection lookup is therefore
an explicit negative test, separate from supported library/task/GC checks.
The successful full run above also passes the following fresh invocations.

[Run 35922933562](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35922933562)
at `2dc9ed406cfb0975024b4454e749677d3d4b6f55` built all five standalone and
nine SDK components, passed six owner checks and seven of ten admitted SDK
cases. Artifact `10778646686` retains the failures. The streaming example
did not handle its expected typed denial; the nested service caller's 128 MiB
reservation could not fund the callee under the node's half-remaining-memory
delegation rule. Each NativeAOT activation measured about 54 MiB. Only that
nested caller now explicitly reserves 256 MiB; the callee and standalone
templates stay at 128 MiB, and production delegation is unchanged.

An actual retained secret component reproduced the third failure under the
native diagnostic. Its full backtrace identifies unsupported
`CryptographicOperations.ZeroMemory`; the later ambient-randomness trap came
from exception reporting, not the secret provider. Local owned bytes now use
non-elidable volatile zero stores with an additional alias-observation test.
The compiled SDK diagnostic checks success/disposal and all four typed errors.
The closed runtime still denies ambient entropy. The successful full Linux run
above covers these changes; the failed attempt remains a failure.

`tools/qualify_dotnet_capsules.py` must retain five standalone builds, nine
actual SDK builds, seven explicit disposable-owner/zeroization checks and all ten
admitted provider/ownership cases. The compiled probe also checks full-width
signed/unsigned values, UTF-8/NUL strings, options, nested record lists, declared
errors, rooted WIT exports after trimming, dynamic-code flags,
activation-local tasks and GC collection. A separate negative member-lookup
probe verifies that unsupported runtime reflection traps without ambient
hash-seed entropy, followed by fresh successful invocations. Compilation alone does not pass those
execution checks.

The signed real-node workflow must cover the three tutorials, allowed/denied
HTTP, errors, cancellation/disconnect, deadlines, trap/fuel/memory exhaustion,
fresh subsequent state and cleanup. Resource receipts must include startup,
active ownership, bounded shared caches and dormant populations of 5, 9 and 17.
The six printed Bash guide steps must execute unchanged. Each failed attempt
retains `QUALIFICATION-FAILED.json`; only the final `qualification.json` with
`status: passed`, source-bound receipts and exact-head PR CI approve delivery.

After installing the guide's pinned prerequisites, use a fresh directory:

```sh
python3 tools/qualify_dotnet_capsules.py --tools "$LSF_DOTNET_TOOLS" \
  --output "$(mktemp -d)/dotnet-authoring"
```

Final PR/issue evidence must identify the reviewed source and successful run.
This does not qualify 100k deployment scale, transactional state, clusters or
runtime release publication. Those gates and #345 remain separate.
