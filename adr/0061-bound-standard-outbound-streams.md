# ADR-0061: Bound standard outbound streams beneath language runtimes

- Date: 2026-09-30
- Status: Proposed for architecture and security review; production installation
  remains disabled pending the review and qualification gates below.
- Decision owner: [#737](https://github.com/KirilsTurkins/latent-service-fabric/issues/737)
- Implementation owners: [provider #738](https://github.com/KirilsTurkins/latent-service-fabric/issues/738),
  [operators #739](https://github.com/KirilsTurkins/latent-service-fabric/issues/739),
  [conformance #740](https://github.com/KirilsTurkins/latent-service-fabric/issues/740).
- Baseline: `development` `0632964d`; the full source identity is retained by
  each executed receipt, rather than inferred from this abbreviation.

## Supersession and decision

For the finite [bounded standard outbound profile](../docs/runtime/outbound-stream-profile.md),
replace ADR-0059's adapter/gateway-first recommendation with an LSF-owned
standard-language runtime port. Ordinary dependencies use their normal socket
constructors and factories. Developers select a captured runtime profile and
explicit endpoint authority; they do not write a transport or install a gateway.
An optional adapter or typed gateway remains useful when deliberately selected.

This supersedes only that default recommendation and the implementation deferral
**for a profile after its review and implementation gates pass**. It does not
supersede ADR-0059's rejection of ambient sockets, protocol inference, hidden
reconnect/replay, cross-activation authenticated connection reuse or assumed
remote rollback. ADR-0005, ADR-0028 and ADR-0031 still apply. Typed HTTP
method/path/header grants authorize typed HTTP, never opaque TCP. Generated
requirements are descriptive inputs, never permission.

The initial identity is `latent:network/streams@0.1.0`, profile
`lsf-outbound-streams-v1`. Authoritative operation/state/error definitions and the
finite workload matrix live in the linked profile. The comparison WIT under
`research/standard-outbound/` remains uninstalled until provider work promotes
the exact reviewed bytes. Import renaming cannot implement socket semantics.

## TLS decision

The standard port exposes authorized TCP. A qualified language runtime owns
guest TLS, including direct TLS, certificate chain/hostname verification,
pinning, explicitly selected client certificates and STARTTLS. Entropy, trust
material, managed/native/TLS allocations and credential exposure must be captured
and charged by that runtime's profile. This is the combination that preserves
the library's observable TLS API. A guest TLS profile does not claim host-only
credentials: the capsule possesses any explicitly granted client key/secret.

The shared provider may also expose a separately selected `host-tls` transport.
That is direct TLS established before returning the connection, TLS 1.2/1.3,
explicit configured trust/hostname policy, no online AIA/OCSP, no client key
injection, no session resumption or 0-RTT. It cannot be chosen transparently for
a library that expects `crypto/tls`, `SSLSocket`, `SslStream`, custom pinning or
STARTTLS. Host TLS is an explicit feature, not evidence of guest TLS support.
TCP authority grants arbitrary bytes to the endpoint; neither the host nor a
catalogue can attest that guest bytes are TLS or infer a protocol permission.

Go's [versioned SMTP source](https://github.com/golang/go/blob/go1.26.1/src/net/smtp/smtp.go)
uses `net.Dial` in its ordinary `Dial` factory and wraps the connection in
`crypto/tls` for STARTTLS. This source observation motivates the TLS placement;
it is not qualification of LSF's selected Go 1.27.1 compiler or port. The finite
matrix requires the actual selected compiler graph in every receipt.

## Authority and ownership

The provider must use the sealed broker, original activation/descendant budget,
`IoRuntime`, `IoCall`, `IoTransfer` and existing cleanup/quarantine owners.
Destination/port/transport are an explicit distinct policy resource. Authority
is checked before DNS/contact and again at guarded dispatch/currentness fences.
Strict transactional execution denies immediate stream effects. There is no
conversion of HTTP grants, broad egress fallback, ambient proxy or guest-selected
DNS server. The current `latent-network::AddressPolicy` and bounded resolver are
the common address/SSRF implementation; a new private-range blacklist is rejected.

The Store table binds logical resources to its fresh generation and sealed
session. Accepted calls retain tenant/publication/provider generations and real
socket/buffer owners through cancellation. Poll readiness is a wake hint, not a
transfer or refund proof. #736 owns logical-thread suspension and final drain;
a waiting thread must not hold a Store borrow across external I/O. There are no
idle per-application connections, guest executors or authenticated sessions.

Possible writes remain uncertain on timeout, cancellation, failed reads and
close. A local successful write is transport acceptance, not remote protocol
commit. The provider never retries/reconnects. A library's additional attempts
are distinct authorized, charged operations; their behavior must be observed in
the selected middleware settings rather than certified by package name.

## Exact gates and partial delivery

1. Architecture and security review must explicitly accept this ADR's selected
   profile, TLS/secret placement, authority, resource bounds and unsupported
   operations. A merge of preparatory code alone is not that review.
2. #738 must deliver actual provider/ABI/broker/currentness/ownership semantics
   and focused real-component tests. Unknown imports/profiles and unavailable
   providers remain denied. The production default remains disabled.
3. #739 must deliver protected configuration, authenticated lifecycle/audit,
   rotation and usable node/toolkit operation. Schema acceptance is not readiness.
4. #740 must retain implementation-backed standard-I/O and adversarial receipts
   for each claimed language profile, actual kernel/native/guest measurements,
   outside-checkout and catalogue-absent controls. Unimplemented cells remain
   pending, not success-labelled skips. #694 consumes these receipts separately.

A design pass cannot close #738/#739/#740. A native protocol test cannot qualify
an emitted component. Missing guest TLS, standard-library/compiler hooks,
reentrant scheduling or half-close support must identify the minimal reproducer
and owning language/runtime issue. The common WASI comparison explicitly records
the `wasi:sockets@0.2.0` start/finish/poll versus canonical async boundary.

No release publication, general POSIX/JVM/Node/CLR emulation, universal protocol
compatibility, durable database redesign or new transactional state backend is
authorized. #696 remains closed; its original ADR-0059 research evidence and
checklists are immutable. New tests retain new exact-source identities and
limitations rather than rewriting those receipts.
