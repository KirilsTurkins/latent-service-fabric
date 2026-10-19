# Go standard logging

The maintained Go compiler supplies `go-standard-logging-v1` when the application's
WIT world explicitly imports `latent:log/log@0.1.0`. Ordinary application and
captured dependency code can keep `fmt.Fprint`, `fmt.Fprintf`, `fmt.Fprintln`,
`os.Stdout.Write`, `os.Stderr.Write`, `syscall.Write(1/2, ...)` and the standard
`log` package's default stderr writer. No application logger callback is required.
The default project still has no log import, grant or log-byte budget.

The compiler verifies the original pinned `syscall.Write` source and installs a
bounded writer before linked application initialization. The generated WIT
binding retains canonical result lifting and allocation ownership. Automatic
source transformations, the captured SDK bridge, application graph and component
identities are retained in normal build provenance. The original closed WASI
adapter and all other descriptors remain unchanged.

| Operation | Mapping and result |
| --- | --- |
| stdout writes | Typed log `info`, exact UTF8 bytes |
| stderr/default logger writes | Typed log `error`, exact UTF8 bytes |
| Empty write | Returns zero bytes and no error without dispatch |
| Write over 4096 bytes | Zero bytes, `EINVAL`, before copying or dispatch |
| Malformed or split UTF8 in one write | Zero bytes, `EILSEQ`; no replacement or retained partial character |
| Host message/field rejection | Zero bytes, `EINVAL`; the host's existing 256-byte message ceiling remains |
| Log budget exhausted | Zero bytes, `EAGAIN` |
| Unavailable sink or rejected delivery | Zero bytes, `EIO`; a false host result is never acknowledged as written |
| Successful write | Original byte count only after the typed host result accepts it |

Formatting stays with the standard library. Formatted allocations remain guest
memory, subject to the invocation's original memory and fuel limits. No line
buffer, worker, background flush, descriptor allocation, retry or implicit
capability grant is introduced. Host correlation, redaction, log-byte accounting
and policy remain authoritative; the guest supplies no identity fields.
`os.File` retains its usual wrapping of syscall errors. `log.Output` exposes
writer errors; `log.Print` has the standard Go API's lack of an error return.
Runtime panic/throw printing and built-in `print`/`println` are outside this
profile; their closed WASI denial is not replaced by a success stub.

Declare the WIT import through ordinary project configuration, select a matching
operator log binding and policy, and allocate an explicit `logBytes` budget.
Logging during an application initializer uses the same admitted component's
authority. No initializer output, mutable state or request identity is frozen in
a shared build snapshot. Strict transaction rules remain enforced by the host.

The additive programme in [the owning Go workflow](../../.github/workflows/go-guest.yml)
captures an outside local module, explicitly reviews its lock, removes its
original source, and builds from the isolated captured graph. It reuses that
run's unchanged five native tools and four companion builds. The exact-source
normal qualification must already pass its complete node programme. The logging
sidecampaign keeps word-count dormant, replays greeting/shipping and the original
recovery/HTTP cases, and uses fourteen exact-service provider bindings within the
unchanged sixteen-binding node ceiling. Full word-count execution remains in the
mandatory normal qualification. It requires a
missing-log-grant denial before guest execution, ordinary initializer/stdout/
stderr/default-logger results, encoding/size/budget errors, a terminal trap and
a successful fresh invocation, with original owner-idle and shutdown fences.
Native reference results supplement this signed gate. Source tests and a native
reference alone do not establish component qualification.

The campaign's signed result remains pending until its exact-source hosted job
passes. Async/buffered logger drain, the full six-language facility matrix and
cross-tenant concurrent qualification remain open under issues #681 and #742.
This profile does not qualify general filesystem or POSIX descriptor APIs.
