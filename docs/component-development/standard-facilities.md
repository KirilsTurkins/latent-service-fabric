# Six-language standard facilities

These are finite supported API mappings beneath ordinary application and
dependency code. Source profiles select compatibility code; WIT declarations
do not install providers or grant authority. Select the maintained runtime
profile, capture/review its normal dependencies, then supply the existing
operator bindings, grants and budgets. No application logger, resource callback
or replacement entropy source is required for the paths below.

| Language | Standard logging | Clock reads | Approved entropy |
| --- | --- | --- | --- |
| Rust | Explicit owned stdio profile: `print!`, `eprint!`, stdout/stderr `Write`; closed owned stdio returns `Unsupported`. [Contract and original source](../../sdk/rust-standard-runtime/README.md#standard-stdio-profile). | Owned `std::time::Instant` and `SystemTime` preserve monotonic nanoseconds versus wall milliseconds. [Source and qualification](../../sdk/rust-standard-runtime/README.md). | Explicit [standard entropy profile](rust-standard-entropy.md): standard hash seeds, exact captured `getrandom`0.3.4 and `rand_core`0.9.3 `OsRng`. Stable Rust has no supported `std::random` promise here. |
| C | [stdio profile](c-standard-logging.md): ordinary stdout/stderr `printf`, `fprintf` and writes, with bounded UTF8 and concrete errno/error results. | [Facilities profile](c-standard-facilities.md): `clock_gettime`/`clock_getres` for the supported monotonic and realtime IDs; unsupported IDs fail explicitly. | Same explicit profile: `getentropy` and its bounded underlying random import; no ambient WASI fallback. |
| TypeScript | [Console profile](typescript-standard-console.md): `log`, `info`, `debug`, `warn`, `error` with bounded primitive formatting; unsupported methods/formatting fail. | [Clock profile](typescript-standard-clocks.md): current `Date` wall time and `performance` monotonic observations. Explicit constructor arguments, parse and UTC retain their deterministic semantics. | [Entropy profile](typescript-standard-entropy.md): ordinary `Math.random` draws from the approved u64 source using its high53bits. App calls without the declaration fail explicitly; compiler bootstrap is separate. |
| Go | [Standard logging](go-standard-logging.md): `fmt`, stdout/stderr, `syscall.Write` on descriptors1/2 and the default `log` package. | [Maintained runtime](go-authoring.md): ordinary wall/monotonic `time` reads through the declared runtime interfaces. Timers and scheduling have separate runtime requirements. | [Standard entropy](go-standard-entropy.md): ordinary `crypto/rand` APIs and the maintained WASI syscall path. No Reader replacement or app callback is required. |
| Java | [PrintStream profile](java-standard-logging.md): ordinary `System.out`/`System.err`, encoding and `checkError` semantics. | Captured [int64 TeaVM mapping](../../sdk/java-guest/tools/teavm_platform.py): `System.currentTimeMillis` wall milliseconds and `System.nanoTime` activation-local monotonic nanoseconds. | [SecureRandom profile](java-standard-entropy.md): explicit approved bytes; supported numeric methods retain their exact accounting. Caller seed/reseed is unsupported. This is not an approval of every `Random`/`Math.random` implementation. |
| .NET | [Console profile](dotnet-standard-console.md): ordinary BCL Console through the selected authenticated logging adapter. | `Stopwatch` uses the admitted monotonic primary; explicit WALL plus actual emitted wall imports selects the [separate wall facet](../../tools/toolchain-smoke/examples/dotnet_wall_clock_runtime.rs) for `DateTime.UtcNow`. [Runtime selection](../../tools/dotnet_guest/runtime.py) grants nothing implicitly. | [Secure RNG profile](dotnet-standard-entropy.md): restored pinned BCL `RandomNumberGenerator` methods use the approved source. The separately declared noncrypto hash-seed path remains distinct. |

The [resource API matrix](packaged-resources.md) describes Rust included data,
C compiled data, TypeScript assets, Go embedded resources, Java classpath and
.NET assembly streams. Their immutable bytes and names remain distinct from
the [closed scratch boundary](java-closed-filesystem.md). Neither mapping
provides a general filesystem or durable state.

All log records retain host-derived activation/tenant identity and the host's
configured redaction and drop-versus-strict policy. A guest cannot claim a new
identity field. This does not promise automatic removal of arbitrary secrets
from application message text. Bridges document their bounded formatting,
encoding and error behavior; infallible standard APIs may throw/panic or expose
their normal error flag. There is no hidden uncharged log worker. Local flush
can acknowledge only the documented local/canonical acceptance boundary,
never remote delivery; in particular BCL `Console.Out.Flush` alone has no new
canonical remote-flush guarantee.

Runtime-support authority remains separate from application effects. A clock
read is not a timer grant. Missing declarations, bindings, grants, failed
providers and exhausted budgets retain their concrete outcomes. Shared strict
telemetry behavior does not expand transactional permissions. No clock or
entropy value is silently synthesized as a successful app observation. The
TypeScript app realm starts after compiler bootstrap; it does not inherit
snapshot-time entropy, tenant credentials or a frozen default current time.

Maintained builders include their selected runtime, automatic patch and
compiler inputs in [captured provenance](application-dependencies.md).
[Compatibility reports](library-compatibility.md) retain final component/WIT
inspection, source/recipe/patch identities and separate actual invocation
outcomes. They do not grant authority, infer the cause of a generic trap, certify
an unobserved API or replace signing/admission. Historical observations retain
their original component, compiled-source and native-product identities.

The individual guides link finite signed observations and failed predecessors.
They are not a current-head build of every profile or the required coupled
six-language programme. Concurrent resource/log callbacks, root cancellation,
pending flush, late completion and fresh cross-tenant state remain explicit
work under #681/#736. The new [Java resource conformance](java-resource-conformance.md)
programme is still pending actual execution; its source controls are not a pass.
