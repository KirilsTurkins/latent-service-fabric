# Ordinary Go entropy qualification

The maintained default `go-component-async-v1` already authenticates the pinned
Go 1.27.2 runtime/syscall source and routes `random_get` to the explicitly
declared `latent:random/random@0.1.0` provider. It fills each requested buffer
from bounded `u64-value` calls. Missing authority cannot fall back to a clock,
fixed seed or ambient WASI source. No provider or grant is installed by adding
a package. The finite ordinary API campaign has actual signed execution evidence
from source `e97d44ddc7`, as recorded below; broader concurrency is not qualified.

The campaign preserves the compiler and routes fixed-size host results through
the existing canonical-lowering owner wrapper. It captures an outside
ordinary module plus a transitive `go:embed` resource module. Normal
add/lock/resolve/exact-review selects both modules, then their original source
directories are physically removed before isolated offline compilation. There
is no catalogue registration, custom `rand.Reader`, callback or application LSF
API. Compiler observations must contain the real standard `crypto/rand` and
`syscall` packages and the selected transitive embedded file.

| Ordinary API | Required observation |
| --- | --- |
| `crypto/rand.Read` | Exact requested fill lengths of 1 and 257 bytes; empty input returns zero without a manufactured payload. |
| Default `crypto/rand.Reader` | `io.ReadFull` fills 32 bytes without replacing the standard Reader. |
| `crypto/rand.Text` | The pinned source's 26-character RFC 4648 base32 shape. Random text is checked in the guest and never retained. |
| WASI `syscall.RandomGet` | The same runtime port handles a 4096-byte buffer and empty input. It creates no socket/filesystem authority. |

The actual Go 1.27.2
[crypto/rand contract](https://github.com/golang/go/blob/go1.27.2/src/crypto/rand/rand.go)
uses `random_get` on WASI and treats a failing secure source as fatal. The
maintained runtime likewise terminates on a provider error instead of allowing
Go's runtime seed fallback. This campaign makes no claim of catchable entropy
exhaustion or FIPS certification. It checks the selected approved provider path,
not the statistical quality of sampled output.

Two admission controls omit only the random grant while keeping both clock
grants, then restore the exact original three grants. They must reject before
guest execution with known outcome, zero fuel/memory/effects and a reaped CLI.
No extra provider binding or policy is added. The existing runtime policy keeps
4096 operations, an 8-byte request descriptor, 32768 output bytes and its
5000-millisecond ceiling. A fixed seventeen-by-4096-byte syscall programme must
terminate at the original 65536-byte provider activation ceiling; if every request succeeds,
it returns a distinct value and fails the required terminal assertion. A
generic public guest trap alone does not classify its private cause.

The normal campaign consumes five exact current native products and four
unchanged companion builds. The independent retained lane instead authenticates
explicitly historical CLI/compiler/companion products and builds only the current
host; it never relabels that historical normal receipt. Both bind every selected
product and companion component before signing the five-project set and require all original
27 node outcomes. Eight standard API/resource/fresh-state calls and three
terminal/fresh pairs (policy exhaustion, explicit panic and original fuel
exhaustion), plus the two denials, require 43 outcomes in total. Every added
completed call has the existing physical-owner sample; node shutdown must be
clean and reaped. No random payload is exported in a receipt.

The Go workflow appends source controls and this single greeting build/campaign
after normal captured-library qualification. Existing commands, the 45-minute
job limit, invocation budgets and runtime selection remain unchanged. Actual
component results for the retained lane passed. Concurrent Reader use, cancellation callbacks,
fresh cross-tenant execution, strict transactional facility behavior and the
remaining six-language resource/clock/entropy matrix remain separate #681/#736
requirements. This adds no scratch or filesystem support.

The first exact-source hosted run (`39295191090`, source `42a2dadf`) passed
baseline and one-byte `crypto/rand.Read`, then the 257-byte read trapped with
zero outbound effects. A later unchanged-component replay (`39305716659`,
source `ba248929`) still failed after an experimental greeting-only input-policy
increase. Those runs are failures, not entropy qualification. The input-policy
hypothesis was incorrect: its eight-byte restriction applies separately to each
call; it is not an aggregate activation budget. The current campaign retains
the original policy unchanged.

The fixed `u64-value` host path formerly retained every completed broker call
until Store drop, exhausting the original sixteen-call session bound during a
257-byte fill. It now returns the existing `Completion` wrapper around only the
nonallocating generated scalar result. This keeps the original `ProviderCall`
alive through canonical lowering and releases it on actual completion or failed
lowering. Variable-length byte results retain their existing Store-owned buffer
and call lifetime. No capacity, grant, provider or activation budget is raised.
Native controls require 33 sequential draws in two fresh activations, invalid
lowering destinations and provider failure followed by a fresh successful
activation, while retaining the original sixteen-call behavior for lists.

The manual `replay-entropy-authority` lane and its fixed original `72fe32bc`
component remain historical diagnostic tooling. They authenticate the original
normal 27-call receipt, native products, companion bytes and package layers,
then freshly package/sign the same component. That component contains the old
nine-buffer terminal probe and cannot qualify the current seventeen-buffer
provider-exhaustion case. Current host and guest changes require fresh owning
native and signed execution; the current results below supply that finite proof.
Neither historical receipt is rewritten or promoted to a current-source qualification.


The first scalar-owner repair run at source `79ba084b95` did not reach the
entropy or native scalar steps: its signed CPU cancellation fixture timed out
waiting for a live provider call, after all nine signed CPU sibling/recursive
iterations passed. Compiler checkpoints yield through the canonical dispatcher
without a pending host call. The repaired fixture observes the same original
invocation, Store, host state, component instance and cancellation probe, with
no timer wait, under the unchanged five-second watchdog. All cancellation,
original-deadline, fresh-activation and uninstrumented negative checks remain.

The explicit `qualify-entropy-retained` manual selection runs that exact CPU
case, all fifteen native random controls, and entropy independently. The entropy
lane builds only the current ordinary `latentd`, verifies an authenticated
historical normal CLI/five component set without rewriting its receipt, runs a
new normal 27-call programme against the current host, then captures and builds
only the current entropy greeting offline and requires all 43 outcomes. Its
receipt distinguishes historical compiler/CLI source, current native host
source and the fresh component source. Pending jobs establish no acceptance.
The original complete 45-minute workflow remains mandatory and unchanged.

## Retained signed observation

[Run39320463437 / job118292873857](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39320463437/job/118292873857)
passed normal27 and fresh entropy43. The
[compact source-bound observation](../testing/evidence/go-standard-entropy-signed-2026-10-19.json)
binds [artifact12220651992](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39320463437/artifacts/12220651992),
source `e97d44ddc744c9bd738d9b3b7a7d8b7234133e36`, the original42a compiler/CLI,
the fresh 184,227,152-byte debug0 host and the 2,878,057-byte offline component
`a5f366344a7b3074da60cb93bfb9ad2f7d837914e41f1f41dc3998766693cbc9`.
The outside library/transitive resource originals were removed before compilation.
All70 outcomes were known/processes reaped; topology samples24/38 and provider-idle
observations6/19 passed, both nodes shut down clean/reaped and peer holds closed.
The two missing-RANDOM denials used zero guest fuel/memory/effects. All eight API
cases and three terminal/fresh pairs passed. The budget fixture's public error
is `guest-trap`; no private cause or new typed error is inferred from that code.
The original provider/activation limits and per-call policy remain unchanged.

[Run39315822073](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39315822073)
separately passed all fifteen native random ownership/lowering/error controls and
the complete signed CPU checkpoint case. A subsequent replay setup failed because
its sanitized environment omitted debug0 and produced a binary over the existing
512 MiB bound. The repaired helper restores the normal explicit profile and checks
the actual emitted profile without increasing that bound; the passing result above
supersedes that setup failure only for this finite lane. No repeat CPU/native15 or
statistical/FIPS, concurrent-reader or six-language completion is claimed.
