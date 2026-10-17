# C standard stdio logging profile

The explicit `c-standard-stdio-v1` compiler profile routes ordinary dependency
`printf`, `fprintf`, `puts` and supported stdout/stderr writes through
`latent:log/log@0.1.0`. It uses the pinned C libc and compiler beneath unchanged
dependency code. It adds no filesystem or ambient WASI host.

**Qualification: signed-node qualification for this finite profile.** The
[corrected hosted programme](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/38931008953/job/117074690334)
passed all 41 expected invocation outcomes at source
`760b47fb0d7aeb9c273c66b7d17bef762dbad980`. Its exact component and retirement
observations are recorded below. This slice does
not complete [facilities #681](https://github.com/KirilsTurkins/latent-service-fabric/issues/681)
or [C runtime #744](https://github.com/KirilsTurkins/latent-service-fabric/issues/744).

The [first actual attempt](../testing/evidence/c-standard-logging-failed-2026-10-16.json)
passed the clock/entropy programme and stdio C compilation, then found an
unresolved `fd_close` during component assembly. Failed assembly retains the
bounded original core for import inspection.

The [follow-up run](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/38845078653/job/116793655937)
rejected the `--wrap` argument in Zig's driver before compiling the stdio guest.
An actual pinned-compiler probe then showed that the accepted single-hyphen
form did not route the calls: the complete fixture still failed component
encoding on `fd_close`. The selected profile now uses a closed four-function
core adapter. It forwards the descriptor calls to explicit exports of the
existing bounded implementation in the same main module. It owns no memory,
resource or host grant. Default and clock/entropy profiles do not use it.

The current `Compiler.compile` implementation compiled the captured outside
library and complete logging fixture, encoded and validated the component with
the pinned tools, and rejected ambient WASI in its public surface. The SDK and
captured dependency remained byte-identical throughout. This is a compiler
source control; it did not execute Wasm or qualify namespace containment or
signed runtime behavior. See the [closed-adapter evidence](../testing/evidence/c-standard-logging-closed-adapter-2026-10-16.json).
The subsequent signed execution is recorded separately below.

The next [signed-node attempt](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/38860192883/job/116840734073)
compiled, validated and signed the logging component. Its first missing-grant
call was correctly rejected before guest admission with zero fuel, memory and
log-byte consumption. The fixture had incorrectly expected an initializer to
execute without that grant. The corrected programme requires the original
pre-admission denial, then checks the ordinary initializer after explicit
authorization. That fixture correction preserves the adapter and admission
rules. The
[retained admission receipt](../testing/evidence/c-standard-logging-admission-failed-2026-10-16.json)
records the component identity, actual rejection and source-control boundary.

The corrected hosted programme at the exact source above passed all 14 stdio
invocations alongside the 27 existing authoring and recovery cases. Both
ungranted calls were rejected before guest execution; the granted initializer
and all eleven edge probes passed. The signed logging component was
`sha256:ae20ca5ac59f2f1c525c5216490921b52433e7cb63bbb36fcd01b0068b8d33ff`.
All 59 retained helper identities matched that source's Git blobs. The public
workflow recorded clean node shutdown, a reaped process and all controlled peer
holds closed. These observations qualify the explicit signed source fixture;
publisher authentication and release publication remain separate boundaries.

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
| Scatter/gather writes | At most 16 vectors and 4096 combined adapter bytes per call; all memory ranges and complete UTF-8 are checked before host dispatch. The host accepts at most 256 message bytes, so a 257–4096-byte message returns `EINVAL`. Empty writes make no host call. |
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
missing-grant invocation must be rejected before guest execution. After an
explicit operator grant, a separate invocation must observe the initializer's
accepted ordinary write. The ordinary `printf` entry likewise requires authority.
Eleven additional actual component probes cover descriptor,
UTF-8, vector, size, memory, empty-write, budget, seek and stderr behavior;
subsequent fresh invocations and normal node shutdown remain mandatory. The
fixture explicitly selects a 16-KiB log budget while preserving its existing
fuel, memory and deadline limits. The existing complete C authoring controls
run alongside it, using the same frozen default native products.

Writable files, stdin, scratch storage, process environment, locale emulation,
binary stdio, concurrent libc calls, pthreads and async log helpers remain
outside this finite profile. Unknown final imports still fail component
validation. See the [C authoring guide](c-authoring.md).
