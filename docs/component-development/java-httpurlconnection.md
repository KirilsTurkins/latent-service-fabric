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

This is an implementation candidate. Native Java ownership controls passed;
the actual TeaVM-emitted component, signed provider runs and unchanged published
client libraries have **not** qualified this profile. Issue #688 remains open.
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
than returning invented empty metadata. Repeated raw header values and binary
response bytes are preserved. EOF is returned only after the provider verifies
EOF and trailers. A failed or truncated read remains a failure.

Each upload/body/chunk uses the generated owned WIT resource. Stream close,
disconnect and errors release guest ownership without claiming physical retirement;
the original installed provider retains charges through actual cleanup or
quarantine. No thread, pool, application connection or mutable guest state is
retained outside the invocation. Concurrent Java thread/executor semantics require
the separately qualified #736/#741 profile; this source slice makes no such claim.

## Concrete remaining implementation

HTTPS currently fails before provider contact because the standard HTTPS type,
certificate/pinning and socket-factory boundary is unqualified. Provider TLS
alone cannot substitute those Java API semantics. Separate nonzero connect/read
timeouts, conditional date requests, interactive authentication, explicit chunk
framing, the wire HTTP version/reason phrase and indexed status-line/header views
remain unsupported. Automatic redirect status handling fails without another
dispatch; explicit `setInstanceFollowRedirects(false)` exposes the response.
These failures are blockers for those features, not success-labelled conformance
skips. There is no implicit proxy, socket fallback, retry, reconnect or credential
forwarding.

The source-bound signed `http-client-profile.json` asset records exact adapter,
recipe, source and component identities and a pending qualification state. It is
not execution evidence or authority. Remaining work includes pinned TeaVM ABI
checks for inherited JDK members, HTTPS and redirect semantics, distinct timeout
phases, two unchanged independent default clients and an outside-checkout private
JAR, the shared real-provider adversarial matrix, native/guest cost measurements
and fresh cross-tenant cleanup. Existing direct Java SDK regressions remain in CI.
