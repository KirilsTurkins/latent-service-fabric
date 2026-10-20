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

**Current evidence:** [run 39494971018 / job 118877563609](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39494971018/job/118877563609)
at `e1c33adb2414a8371026d479600e08d48b6df88a` passed the real pinned IR
controls, normal Java component build, package assembly, signing and both
zero-work authority denials. Its first public-factory invocation succeeded with
`1:spi:200:7:1`, 11,094,755 fuel and one outbound request. The workflow then failed
in the qualifier reader: CLI `cpuFuel` is a decimal u64 string, while
`outboundRequests` is an integer u32. The old reader wrongly required strings for
both. The strict field-specific correction preserves all original outcomes and
rejects booleans, altered types, overflow and duplicate outbound charges.
All six SPI cases are still required; one actual success does not qualify them.

Artifact `12296844781` (2,003,357 bytes, SHA256
`cc7bc2b4aa07072943925f3a8aea098f338f9c3b44724a2f97fdad8e33bea9c4`)
retains the original component and assembled package. All 105 members passed CRC
and SHA checks. The separately selected fixed-artifact replay authenticates all
55 build members, original package/layer preimages, all 199 captured SDK and 73
compiler recipe files, and 110 campaign materials against exact Git source.
Only the reviewed SPI result reader differs. The 6,410,239-byte component digest
is `07012456a9e874e13f639dfff7f93fc5823cfebffb79a35585548e663d12da25`.
No new guest or native compilation is needed to correct that reader.

The diagnostic selector `java_http_spi_prepared` defaults to false and requires
explicit `java_http_spi=true` as well. It preserves the entire original normal
workflow and full SPI job when absent/false. Only the explicit replay selection
fresh-signs this original component and executes the same six cases plus two
authority denials and four contacts. Before/after build, source and native checks
remain mandatory. Its hosted result is pending. The independently authenticated
native source remains `f9192fb5785ca7bed8b33dbb869b3d775b72ab4b`; the shared strict
reader and full current native/auxiliary equality are unchanged. No historical
failure, default-client result or cross-tenant result is relabelled as SPI proof.
Neither #688 nor #741 closes.

## Same-node cross-tenant boundary

The maintained node now supports bounded independent HTTP installations, with
separate tenant/provider identities, credential stores, pools, configuration
digests and grants. The separate programme in `java-http-tenant-isolation.md`
owns its actual same-node positive and negative evidence. This optional-SPI
programme deliberately reports no cross-tenant qualification and does not
substitute a missing-provider refusal or two independent nodes for that proof.
Neither HTTP aliases nor shared credentials are introduced here.

The optional consumer uses the same exact profile/component identity fence as
the default phase programme, under the existing 64 MiB Java component producer
bound. Its owned public component/package and bounded WIT diagnostics are
retained for source-bound reader repairs. These source controls are not signed
SPI qualification; the six real calls and two authority denials remain pending.

The optional manual entry is also available through the existing Java authoring
workflow, because development-only focused workflow names cannot be dispatched
from the default branch. Its selector defaults to false; only an explicit SPI
dispatch skips normal baseline jobs. Removing the selector, exact two exclusions
and copied job restores the entire old workflow. Both entries use the same
programme, authority, component operator ceiling and budgets; neither runs
automatically as a substitute for default-client qualification.

The separate SPI campaign inherits the same explicit 64 MiB node component-input
profile and 64 MiB operator input profile as the phase campaign. Its public
receipt projects the actual node selection separately. Guest execution, provider,
cell and cache budgets remain unchanged. SPI execution remains pending; this
source update does not transfer any default-client or tenant result.
