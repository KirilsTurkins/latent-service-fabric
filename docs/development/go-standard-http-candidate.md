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
upload trailers and transfer encoding are explicitly unsupported.
Client and request-context timeouts retain their original deadline ownership.
Nonzero ResponseHeaderTimeout, MaxResponseHeaderBytes, ReadBufferSize and
WriteBufferSize fail before dispatch: this typed ABI does not expose their
distinct wire phases, wire header size or physical socket buffers. A timeout
around the whole typed Finish would incorrectly include DNS/connect time.
The maximum body is1MiB, header count32, header storage8KiB, and each
guest-owned read/upload chunk is at most16KiB. These guest chunk bounds do not
claim to implement the native wire-buffer fields. Unsupported values fail before dispatch.

The typed contract reserves wire compression/credential/framing headers. The
compiler sets DisableCompression true on the default Transport and replaces its
exact pinned built-in socket DialContext initializer with nil to select the
typed backend. These are documented differences from native Go's default;
application-supplied dialers still fail before invocation. A concrete Transport requesting automatic
compression fails explicitly. Authorization, cookies and other reserved request
headers fail before contact. Content-Type and Idempotency-Key are structured
typed request fields. No source-level credential or raw-header exception is
introduced for any library.

The guest Transport owns no connection pool. Guest idle-pool bounds therefore
cover zero retained connections; CloseIdleConnections has no guest connection
to close. Host provider reuse, if any, belongs to its separately approved typed
HTTP profile and budget. A nonzero MaxConnsPerHost is rejected because a logical
request limiter is not proof of a concrete connection limit. DisableKeepAlives
or Request.Close true is rejected
before dispatch because host reuse is not controlled by that guest field.
Invalid negative request lengths and positive lengths without a body fail
before upload creation instead of being replaced with a different length.
HTTP-only requests do not execute TLS-specific fields. Other protocol/custom connection state
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

The five source controls authenticate all original Transport/RoundTrip/Client
bytes, reject drift and module-name injection before output, and retain original
sources. The ordinary fixture uses new http.Client, DefaultTransport.Clone,
concrete Transport, JSON domain parsing, POST, early Close, cancelled contexts
and a separate custom RoundTripper. The normal compiler gate is bounded to
900/600 seconds, retains exact SDK/source/recipe/overlay/component/tool identities,
and explicitly records compile-only with signedExecution not-run.

The first actual hosted compiler run passed both the context-aware typed fixture
and this ordinary net/http fixture. It then failed the existing parent timer GC
case before reaching module-initializer and ordinary authoring qualification.
Those observations are compile-only; they do not establish HTTP execution or
qualify the pending scheduler parents. The unchanged timer failure remains in
[run 38835607597](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/38835607597).

The separate `qualify_go_standard_http.py` gate now captures the exact fixture
through normal project creation and packaging, reuses only the five immutable
products from successful ordinary Go authoring qualification, demo-signs the
observed package, and deploys it on the normal enforced node. The fixture reads
the bounded HTTP body before ordinary guest JSON parsing, so transport truncation
and size failures cannot be hidden by an early JSON syntax error. A static
counter rejects reuse of a previous activation's state. The early-close case
uses ordinary ReadFull for four bytes instead of assuming one Read fills them.

Twenty-nine cases cover domain JSON, HTTP error status, truncation, oversize,
malformed JSON, forbidden headers, early Close, pending header/body cancellation,
POST bytes, uncertain mutation, target denial, pre-cancelled contexts, sibling
cancellation, concrete Transport, DefaultTransport.Clone, a separate custom
RoundTripper, custom-dialer denial without invocation, physical nonreuse and
negative-header-limit and inconsistent-body-length denial, and fresh state.
Wire-header deadline/limit and socket-buffer options also fail before contact.
Every activation checks actual provider counters,
cleanup slots and topology. The controlled peer must report exactly 15 primary
contacts, one committed mutation and no secondary contact. These observations
are distinct from allocator/native/kernel upper-bound qualification.

Compilation retains its normal 900-second enclosing build and 600-second
command limits. The new gate bounds the node/peer to 300 seconds under a
1200-second total deadline. It runs after the existing ordinary authoring gate
and retains every previous command and the original 45-minute workflow limit.
Source controls reject changed vendored SDK/native products before execution,
and authenticate the default backend initializer without admitting custom dialers.
This signed gate has been added and has not yet executed. HTTPS, published
default-client consumers, the wider matrix and complete #692 acceptance remain
required; no full-ticket result follows from this candidate.
