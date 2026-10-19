# Ordinary Go entropy qualification

The maintained default `go-component-async-v1` already authenticates the pinned
Go 1.27.2 runtime/syscall source and routes `random_get` to the explicitly
declared `latent:random/random@0.1.0` provider. It fills each requested buffer
from bounded `u64-value` calls. Missing authority cannot fall back to a clock,
fixed seed or ambient WASI source. No provider or grant is installed by adding
a package. This page describes a new qualification campaign; it is not yet a
signed execution result.

The campaign leaves the backend and compiler unchanged and captures an outside
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
5000-millisecond ceiling. A fixed nine-by-4096-byte syscall programme must
terminate at the original operation/byte/wall ceiling; if every request succeeds,
it returns a distinct value and fails the required terminal assertion. A
generic public guest trap alone does not classify its private cause.

The same current normal qualification supplies five exact native products and
four unchanged companion builds. The helper verifies actual source-inventory
bytes against the receipt and current source, as well as every selected product
and companion component. It signs the five-project set and retains all original
27 node outcomes. Eight standard API/resource/fresh-state calls and three
terminal/fresh pairs (policy exhaustion, explicit panic and original fuel
exhaustion), plus the two denials, require 43 outcomes in total. Every added
completed call has the existing physical-owner sample; node shutdown must be
clean and reaped. No random payload is exported in a receipt.

The Go workflow appends source controls and this single greeting build/campaign
after normal captured-library qualification. Existing commands, the 45-minute
job limit, invocation budgets and runtime selection remain unchanged. Actual
component results are pending. Concurrent Reader use, cancellation callbacks,
fresh cross-tenant execution, strict transactional facility behavior and the
remaining six-language resource/clock/entropy matrix remain separate #681/#736
requirements. This adds no scratch or filesystem support.
