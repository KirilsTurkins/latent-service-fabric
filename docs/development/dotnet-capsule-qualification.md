# C# capsule qualification

This is developer execution evidence for #549, separate from the beginner
[C# authoring guide](../component-development/dotnet-authoring.md). It does not
authorize a release or replace human newcomer review #345. The complete
qualification is still pending: successful compiler diagnostics are not a
substitute for all SDK, signed-node and printed-guide stages.

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

## Retained attempts

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

## Required final evidence

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
cleanup and printed-guide stages remain unqualified. The exact source archive
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
five-second durable clock lease. The node and guide still need a complete rerun.

[Run 35928271057](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35928271057)
at `79ef782ab9f3440baa10123a3581ed727c875c87` passed the expanded actual
NativeAOT probe, all five standalone and nine SDK builds, seven ownership
checks and eight of ten SDK runtime tests. The secret success/typed-error
diagnostic and actual secret/streaming cases passed. Artifact `10780656604`
retains two admission failures: the nested caller declared its required
256 MiB ceiling, but the signing fixture still advertised a 128 MiB runtime.
The fixture now uses the same explicit nested-service ceiling as the node
composition; ordinary package profiles remain at 128 MiB. No production
delegation rule or authority is widened. The next run must execute both
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
The following successful fresh invocation must still pass.

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
The closed runtime still denies ambient entropy. These changes require a new
complete Linux run; they are not a claim that the failed run passed.

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
