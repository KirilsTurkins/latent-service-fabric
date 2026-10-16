# Standard Go HTTP candidate

This compiler-owned candidate adapts pinned Go1.27.2 `Transport.RoundTrip` to
the declared `latent:http/streaming@0.3.0` interface. It is selected only with
the explicit v4 activation profile and a real streaming import. No application
RoundTripper, dialer, source rewrite, package registration or extra grant is
required. Original Go source files and captured dependencies remain unchanged;
the private overlay and SDK backend are captured compiler inputs. The original
complete Client implementation is authenticated and kept intact.

This is a draft compile candidate for [#692](https://github.com/KirilsTurkins/latent-service-fabric/issues/692).
The runtime parent, actual component build, signed provider cases, two unchanged
independent libraries and outside-checkout developer module remain required.
Source controls do not establish runtime qualification or close the ticket.

## Finite API contract

The candidate supports ordinary default Client calls, DefaultClient,
DefaultTransport, cloned DefaultTransport, and a concrete Transport with
DisableCompression true. It maps GET/HEAD/POST/PUT/PATCH/DELETE/OPTIONS, URL,
structured media type/idempotency key, bounded headers, upload length/body,
status and response headers. HTTP errors return a normal Response. Transport
failures preserve finite host categories; cancellation uses the original
subtask terminal fence. Request body Close runs on success or denial.

The first candidate accepts HTTP URLs only. HTTPS and negotiated TLS/protocol
state are unqualified; Response protocol/TLS fields remain unavailable instead
of inventing wire metadata. Direct or transitive raw net, TLS sockets, HTTP/2/3,
custom dialers, proxy use, wire tracing, custom Host, legacy Request.Cancel,
upload trailers and transfer encoding are explicitly unsupported. Configured
response-header timeout uses the calling request context and original timer
ownership. The maximum body is1MiB, header count32, header storage8KiB, and each
guest-owned read/upload chunk is at most16KiB. Positive buffer sizes may lower
that chunk bound. Unsupported values fail before dispatch.

The typed contract reserves wire compression/credential/framing headers. The
compiler sets DisableCompression true on the default Transport, a documented
difference from native Go's default. A concrete Transport requesting automatic
compression fails explicitly. Authorization, cookies and other reserved request
headers fail before contact. Content-Type and Idempotency-Key are structured
typed request fields. No source-level credential or raw-header exception is
introduced for any library.

The guest Transport owns no connection pool. Guest idle-pool bounds therefore
cover zero retained connections; CloseIdleConnections has no guest connection
to close. Host provider reuse, if any, belongs to its separately approved typed
HTTP profile and budget. A nonzero MaxConnsPerHost is rejected because a logical
request limiter is not proof of a concrete connection limit. HTTP-only requests
do not execute TLS-specific fields. Other protocol/custom connection state
remains outside this finite profile.

## Higher-level behavior and ownership

Original Client code owns redirects, cookies, authentication and request
repetition. Every attempt reaches the typed backend and must independently pass
current target/grant/framing policy. The glue adds no retry or reconnect, and
never invokes GetBody. An uncertain POST remains uncertain. The explicit public
custom RoundTripper path remains open. Registered Transport protocols delegate
to their ordinary handler; ErrSkipAltProtocol fails explicitly instead of
replaying a body or effect the handler may already have consumed.

Response reads preserve partial buffered reads and explicit EOF. A chunk's bytes
are copied before its resource is destroyed. Read and Close serialize ownership;
Close first cancels the original request child context, then waits for any
pending read's actual terminal fence before dropping its borrowed resource.
Guest buffers remain bounded while idle, cancelled or partially consumed.
Cancellation is not external mutation rollback or physical-owner proof. Root
drain, sibling progress, late wakeups and physical retirement must be established
by the signed runtime/provider gate under the unchanged original deadline.

## Maintained proof boundary

The four source controls authenticate all original Transport/RoundTrip/Client
bytes, reject drift and module-name injection before output, and retain original
sources. The ordinary fixture uses new http.Client, DefaultTransport.Clone,
concrete Transport, JSON domain parsing, POST, early Close, cancelled contexts
and a separate custom RoundTripper. The normal compiler gate is bounded to
900/600 seconds, retains exact SDK/source/recipe/overlay/component/tool identities,
and explicitly records compile-only with signedExecution not-run.
