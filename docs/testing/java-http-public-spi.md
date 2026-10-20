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
signing and the six SPI outcomes have not run. This branch has no workflow or PR
yet and requires the independent nominal-native authenticator before dispatch.
It does not close #688 or #741 or replace the default-client proof.

## Same-node cross-tenant boundary

The maintained node currently accepts one `httpStreaming` installation. Binding
validation requires the installation's tenant and provider service, and scalar
aliases explicitly exclude HTTP. Each provider credential is separately bound
to its tenant, provider ID and origin. Therefore this programme makes no
same-node cross-tenant HTTP claim. A second tenant's missing-provider refusal
would prove a denial boundary, not a successful isolated second guest; two
separate nodes would also not prove same-node isolation.

The next production slice needs explicitly bounded additional HTTP installations
with independent registrations, credential scopes and configuration digests,
preserving the original fourteen-descriptor/global-pool ceilings and all grants.
No HTTP alias or shared credential exception is introduced here. Actual
cross-tenant success, secret isolation, late completion and retirement must run
after that implementation with separately authenticated native products.
