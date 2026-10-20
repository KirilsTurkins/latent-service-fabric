# Optional Java public HTTP SPI qualification

This is separate from the ordinary no-injection/default-client campaign in
`java-http-phase-timing.md`. The maintained `http-request:6.0` JAR exposes its
public `HttpRequest.ConnectionFactory` and `setConnectionFactory` APIs. The
optional fixture implements that guest API and delegates to ordinary
`URL.openConnection()`; it neither calls a typed LSF transport nor installs a
provider. The exact public source is [the pinned 6.0 source](https://github.com/kevinsawicki/http-request/blob/http-request-6.0/lib/src/main/java/com/github/kevinsawicki/http/HttpRequest.java),
SHA-256 `5139810792a0f7cff2de9c4a7d2399ece3201e1d349595adaf3221af0b43a43a`.
The actual campaign consumes the unchanged original JAR through normal
resolve/review/capture and an offline build, with the same three-JAR closure as
the default-client fixture. Source API inspection is not component execution.

The separate programme has six signed calls: public-factory success; a fresh
invocation using the untouched library default; a denied alternate destination;
a forbidden credential-header attempt; the library's public reset-to-default
operation; and another fresh default invocation. It requires four primary HTTP
contacts, zero alternate contacts or mutations, bounded one-operation
consumption, full signed revision identity and zero physical owners after each
call. Two missing-authority controls must refuse before guest work. The factory
holds no connection or credential. Leaving its pure factory reference installed
in the first activation makes the following default call a concrete static-state
reset check. The original default clients and their sixteen-call qualification
remain unchanged.

Raw per-call, physical-owner, final shutdown, peer and binary identities are
written before a compact summary. Both node and peer must be clean and reaped.
Only the new authenticated nominal-packaging native tuple is accepted; the
historical77 tuple is not substituted. An existing source-checked compiler cache
may be reused; one new application component is still compiled normally. No
native Cargo/toolchain rebuild is part of this campaign.

**Current evidence:** focused source/controller controls pass. Actual compilation,
signing and the six SPI outcomes have not run. The separate default-false `java_http_spi` workflow selector is prepared, but no
SPI dispatch or PR has occurred. The native authority repair, compiler-owned
`SocketTimeoutException` type and original-entry coroutine liveness correction
are integrated in this branch. The selected native source is the independently
authenticated `f9192fb5785ca7bed8b33dbb869b3d775b72ab4b` tuple through the shared
strict reader; full current native and auxiliary equality remains mandatory.
Historical tuple helpers remain unchanged. The real IR and component results
remain pending; the default-client campaign owns its separate qualification.
It does not close #688 or #741 or replace the default-client proof.

## Same-node cross-tenant boundary

The maintained node now supports bounded independent HTTP installations, with
separate tenant/provider identities, credential stores, pools, configuration
digests and grants. The separate programme in `java-http-tenant-isolation.md`
owns its actual same-node positive and negative evidence. This optional-SPI
programme deliberately reports no cross-tenant qualification and does not
substitute a missing-provider refusal or two independent nodes for that proof.
Neither HTTP aliases nor shared credentials are introduced here.
