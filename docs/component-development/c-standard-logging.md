# C standard stdio logging profile

The explicit `c-standard-stdio-v1` compiler profile routes ordinary dependency
`printf`, `fprintf`, `puts` and supported stdout/stderr writes through
`latent:log/log@0.1.0`. It uses the pinned C libc and compiler beneath unchanged
dependency code. It adds no filesystem or ambient WASI host.

**Qualification: implemented candidate, unqualified.** Source capture, profile
and generated binding checks supplement the required signed component run.
The C standard-facilities CI job retains the actual logging qualification;
runtime compatibility requires a passing exact-source receipt. This slice does
not complete [facilities #681](https://github.com/KirilsTurkins/latent-service-fabric/issues/681)
or [C runtime #744](https://github.com/KirilsTurkins/latent-service-fabric/issues/744).

The [first actual attempt](../testing/evidence/c-standard-logging-failed-2026-10-16.json)
passed the clock/entropy programme and stdio C compilation, then found an
unresolved `fd_close` during component assembly. The selected profile now uses
explicit linker wrappers for its four reviewed public libc and raw descriptor
operations. Failed assembly retains the bounded original core for import
inspection. Fresh native compilation and signed stdio execution remain pending.

The [follow-up run](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/38845078653/job/116793655937)
rejected the `--wrap` argument in Zig's driver before compiling the stdio guest.
The candidate now passes the single-hyphen `-Wl,-wrap,<symbol>` form for those
same eight symbols. The clock/entropy programme passed before that failure;
the corrected stdio build and signed calls still require a fresh run.

Set `runtimeProfile` to `c-standard-stdio-v1` in `capsule-project.json` and in any
captured dependency selection. Resolve and review the new lock, then use the
normal build, signing and admission workflow. The operator must separately
authorize the log capability and provide a finite `logBytes` budget. Neither
the profile nor the derived WIT installs a grant. Existing closed projects and
the separate [clock/entropy profile](c-standard-facilities.md) retain their
previous contracts.

| API boundary | Finite semantics |
| --- | --- |
| stdout / descriptor 1 | One accepted UTF-8 record per underlying write, level `info`. |
| stderr / descriptor 2 | Same ownership, level `error`. |
| Formatting and buffering | The actual libc formats values. An SDK-owned reactor initializer at priority 101 selects unbuffered stdout/stderr before ordinary default-priority dependency initializers, so successful ordinary writes do not depend on application shutdown glue. |
| Scatter/gather writes | At most 16 vectors and 4096 combined bytes per call; all memory ranges and complete UTF-8 are checked before host dispatch. Empty writes make no host call. |
| Encoding | UTF-8 may cross vector boundaries. Invalid, incomplete, overlong, surrogate or out-of-range sequences return `EILSEQ`; this is a textual log sink rather than a binary byte stream. |
| Budget / invalid input | Host budget exhaustion returns `EAGAIN`; oversized vectors or host invalid-field errors return `EINVAL`. The original activation log ledger remains authoritative. |
| Unavailable / denied / rejected log | Return `EIO` with no success-labelled byte count. The existing log WIT exposes `unavailable` rather than a separate permission error; the port does not invent a more precise errno. |
| Descriptor queries | Only stdout/stderr have a non-inheritable write right. They report unknown file type and no terminal/seek/filesystem semantics. Other descriptors return `EBADF`. |
| Seek / close | stdout/stderr return `ENOTSUP`, other descriptors `EBADF`. No successful seek or close is fabricated. |

Successful writes mean the current host log sink accepted the record. They do
not acknowledge external export, durable delivery or a remote flush. The port
adds no replay, background worker, pending message queue or private log buffer.
Host-derived correlation, field restrictions, encoded-byte charging and sink
ownership remain in the existing host implementation. Arbitrary dependency
messages remain untrusted application content; callers must not put credentials
into them. A failure does not transfer an error string or a borrowed guest
buffer beyond its generated call.

The compiler captures the SDK adapter as part of the unchanged SDK lock,
derives a separate WIT world containing only the log import, and binds generated
application bindings, final contracts and runtime identity to the selected
profile. Tampering with the adapter or borrowing the clock profile invalidates
the build. The reactor initializer runs in guest activation memory, not on the
build host. No logging handle survives activation retirement.

The contributor fixture captures an independently named outside-project C
library, removes its original files and compiles from verified captured bytes.
Its default-priority initializer also calls ordinary `printf`; a separate
missing-grant invocation must observe its native failure, rather than buffered
success. Its ordinary `printf` path must fail without authority and work after explicit
operator policy. Eleven additional actual component probes cover descriptor,
UTF-8, vector, size, memory, empty-write, budget, seek and stderr behavior;
subsequent fresh invocations and normal node shutdown remain mandatory. The
fixture explicitly selects a 16-KiB log budget while preserving its existing
fuel, memory and deadline limits. The existing complete C authoring controls
run alongside it, using the same frozen default native products.

Writable files, stdin, scratch storage, process environment, locale emulation,
binary stdio, concurrent libc calls, pthreads and async log helpers remain
outside this finite profile. Unknown final imports still fail component
validation. See the [C authoring guide](c-authoring.md).
