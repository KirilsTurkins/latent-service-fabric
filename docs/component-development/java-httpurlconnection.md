# Java standard URLConnection source profile

The opt-in source profile `lsf.java.httpurlconnection.streaming.v1` supplies a
capability-backed implementation underneath the maintained TeaVM URL parser.
Select it with `"httpClient": {"profile": "lsf.java.httpurlconnection.streaming.v1"}`
in `capsule-project.json` and declare `latent:http/streaming@0.3.0` in the selected
WIT world. Operators still install the provider and exact HTTP grants separately.
The project continues to use ordinary `URL.openConnection()` and
`HttpURLConnection` calls, including calls inside captured JARs. It supplies no
LSF transport or executor. The compiler replaces the default browser HTTP handler
at its standard runtime boundary; it preserves URL parsing and application/JAR
identities. User-supplied URL handlers remain optional guest extensions.

This is an implementation candidate. Native Java ownership controls and a
[finite signed ordinary-API provider gate](../testing/java-standard-http.md)
passed, including actual TeaVM component execution, HTTP errors, denied targets,
body failures/early close, uncertain POST and physical retirement. One unchanged
published default client also passes that finite provider matrix. The later
[two-published-client campaign](../testing/java-published-http.md) passed all
26 cases using unchanged `http-request:6.0` and DavidWebb with its transitive
JSON parser. The [private-JAR campaign](../testing/java-private-http.md) passed
its separate 26-case captured-source gate. Those source-bound results leave the
complete profile unqualified.
Issue #688 remains open.
It is independent of the listener-free Java HttpServer profile. Selecting both
profiles merges their SDK compiler provider lists without replacing either list.

## Implemented source boundary

The current handler accepts HTTP URLs, exposes GET, HEAD, POST, PUT, DELETE and
OPTIONS, keeps raw query bytes, and omits a URL fragment from the request target.
GET changes to POST when an unconnected connection opens its configured output
stream, matching that selected standard operation. TRACE is unsupported.
Request and response bodies are bounded to 262144 bytes each, transferred in
chunks of at most 4096 bytes. Fixed request lengths are verified before completion;
overruns and underruns terminate the operation. Request metadata is bounded and
ambiguous duplicate field casing is rejected. Content-Type is mapped to the typed
media field. Protected framing, credentials and destination policy remain owned
by the installed HTTP provider.

HTTP 4xx/5xx stay responses: their code and error stream remain available.
Provider failures are catchable `HttpFailure` IOExceptions with a closed `code()`;
`uncertain` retains uncertainty and grants no retry. Failure freezes the operation:
another getter does not open or finish another request. The header methods that
cannot declare IOException wrap the same error in `UncheckedIOException` rather
than returning invented empty metadata. Response field names are grouped without
regard to case under their first observed spelling. Repeated values retain wire
order, and a named getter returns the last value. The response map and value lists
are immutable copies. Focused host JDK controls cover mixed and interleaved casing,
media metadata, retained copies and owner release; signed component evidence for
this header correction remains separate. Binary response bytes are preserved.
EOF is returned only after the provider verifies
EOF and trailers. A failed or truncated read remains a failure.

The compiler adds the missing standard declarations for the long fixed-length
request overload, `usingProxy`, `getContentLengthLong` and `getHeaderFieldLong`
to the maintained class model. The getters use actual response metadata and
full-width parsing, retaining transport failures and the standard malformed-value
default. The finite long request path delegates to the existing bounded upload;
it does not truncate a requested length. An unchanged outside caller's bytecode
retains its standard method references. These transformations passed an actual
TeaVM 0.15 class-model check using the compiler JARs' recorded SHA-256 identities;
the ordinary and published-client components now exercise that boundary.

`URL.openConnection(Proxy.NO_PROXY)` selects the same default handler. The
compiler supplies the standard direct marker and the missing overload beneath
captured bytecode. Shared standard type identities let a library's optional
proxy branch link without requiring the application to replace its factory.
The finite profile rejects explicit proxies and socket-address resolution with
concrete errors before DNS or contact. It supplies no socket or proxy transport.
These standard API substitutions do not inspect dependency coordinates.

The profile also supplies the canonical abstract `javax.net.ssl.HttpsURLConnection`
type for ordinary libraries' optional HTTPS type checks. It remains distinct from
the final plain-HTTP `Connection`: an HTTP connection never passes that test.
Construction and the supplied hostname-verifier/socket-factory setters are
catchably unsupported (`java-https-standard-type-not-qualified`); null setter
arguments retain their standard `IllegalArgumentException`. No verifier, socket
factory, certificate, TLS connection or successful placeholder is created.
The ordinary HTTPS URL factory retains its original pre-dispatch refusal.
This finite type surface is not a qualified HTTPS implementation.

Each upload/body/chunk uses the generated owned WIT resource. Stream close,
disconnect and errors release guest ownership without claiming physical retirement;
the original installed provider retains charges through actual cleanup or
quarantine. No thread, pool, application connection or mutable guest state is
retained outside the invocation. Concurrent Java thread/executor semantics require
the separately qualified #736/#741 profile; this source slice makes no such claim.

## Selected phase profile and optional public SPI

The separate [explicit phase profile](../testing/java-http-phase-timing.md)
adds bounded actual connect/read deadlines and actual response-reason bytes
without changing the legacy profile described above. Its source-specific
sixteen-call result includes default DavidWebb use and retains the root
cancellation/deadline distinction. This does not qualify every Java HTTP API.

The [optional public guest SPI](../testing/java-http-public-spi.md) uses the
unchanged `http-request:6.0` connection-factory extension. Six signed cases and
two authority denials verify delegation through ordinary `URL.openConnection`,
reserved-header/destination refusal and fresh default-state retirement. The
extension requires no maintainer registration and supplies no host authority.
Its historical compiler/native attribution and current-source limits are
recorded separately from the default-client programme.

## API, feature and runtime matrix

These are implementation profiles and finite evidence scopes. The package
versions used by a particular test live in its separate receipt and never select
API eligibility or require a catalogue entry.

| API/feature | Selected implementation and runtime | Evidence and boundary |
| --- | --- | --- |
| Ordinary `URL.openConnection` / `HttpURLConnection` | `lsf.java.httpurlconnection.streaming.v1`, typed HTTP 0.3 | [Ordinary/published/private provider cases](../testing/java-standard-http.md); HTTP only, bounded bodies, explicit unsupported members as above. |
| Nonzero connect/read setters and response reason | `lsf.java.httpurlconnection.phase-timing.v1`, typed HTTP 0.4 / host V7, `teavm-activation-fibers-io-v1` | [Sixteen signed cases and two denials](../testing/java-http-phase-timing.md); root deadlines/cancellation remain distinct. |
| Pending HTTP with runnable Java work | `teavm-activation-fibers-io-v1` | [Finite sibling/timer/lifecycle evidence](../testing/java-http-fiber-lifecycle.md); this is not every executor or cross-tenant case. |
| Optional guest factory | Same selected HTTP/runtime profile | [Six signed SPI cases and two denials](../testing/java-http-public-spi.md); separate from required defaults, no privileged provider. |
| `Class` / `ClassLoader` resource lookup, wall and monotonic reads | Captured immutable resource port and explicitly declared clock interfaces | [Ordinary resource/clock conformance](java-resource-conformance.md); no ambient filesystem or clock authority. |
| `System.out` / `System.err` and `SecureRandom` | Compiler-owned bounded logging and entropy ports | [Logging](java-standard-logging.md) / [entropy](java-standard-entropy.md); declarations, grants, limits and technical failures remain explicit. |
| Runtime/automatic patch and diagnostics tooling | Normal source/recipe/component reports, exact compiler-owned transformations | [Compatibility reports](library-compatibility.md), [captured Java authoring](java-authoring.md); report success is not API execution or an authority grant. |

The HTTP port composes these ordinary standard facilities through the normal
compiler, captured WIT and grants; it does not replace them with HTTP-specific
resource, logging, clock or entropy callbacks. Every dated result keeps its
original runtime/compiler/patch/component identities. Fresh current-source
qualification and the outstanding full lifecycle/tenant matrix remain separate.

## Concrete remaining implementation

HTTPS currently fails before provider contact because the standard HTTPS type,
certificate/pinning and socket-factory boundary is unqualified. Provider TLS
alone cannot substitute those Java API semantics. In the legacy profile, nonzero connect/read
timeouts remain unsupported; the explicit phase profile linked above provides
its separately qualified finite path. Conditional date requests, interactive
authentication, explicit chunk
framing, the wire HTTP version and indexed status-line/header views remain
unsupported. The typed provider does not export a reason phrase; the optional
`getResponseMessage()` returns `null` after completing the normal response,
without inventing text or suppressing an operation error. Automatic redirect status handling fails without another
dispatch; explicit `setInstanceFollowRedirects(false)` exposes the response.
These failures are blockers for those features, not success-labelled conformance
skips. There is no implicit proxy, socket fallback, retry, reconnect or credential
forwarding.

The source-bound signed `http-client-profile.json` asset records exact adapter,
recipe, source and component identities and a pending qualification state. It is
not execution evidence or authority. Remaining work includes pinned TeaVM ABI
checks for inherited JDK members, HTTPS and redirect semantics, additional timeout/API cases beyond the explicit phase programme,
remaining pending/sibling/cancellation behavior, native/guest cost measurements
and fresh cross-tenant cleanup. The two published clients and outside-checkout
private JAR have passed the finite shared real-provider matrix linked above;
their receipts do not qualify the remaining surfaces. Existing direct Java SDK
regressions remain in CI.
