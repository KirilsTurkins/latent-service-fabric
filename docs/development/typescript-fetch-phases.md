# Explicit TypeScript Fetch phase-contract candidate

The compiler can select `lsf-fetch-phase-buffered-v2` when the existing
`spidermonkey-activation-promises-clocks-imports-v1` runtime and the explicit
`latent:http/phase-timing@0.4.0` import are both declared. Package names do not
select it, application metadata cannot install/override the backend, and this
selection supplies no provider or destination grant. The legacy0.3 contract
continues to select `lsf-fetch-buffered-v1` with its original call arities.

Ordinary global fetch/Request/Response/Headers calls remain the application path.
Fetch has no independent connect/read-timeout option: the phase adapter passes
None for these operation timers and retains the original caller/root deadline
and AbortSignal behavior. This does not reinterpret an HTTP method/path grant
as stream authority, install a clock/secret or add retries.

The phase response can expose the actual bounded reason-phrase bytes as Latin1
statusText, including an observed empty phrase and exact whitespace/obs-text.
Unavailable metadata and the legacy contract retain the explicit unsupported
getter; no conventional phrase is manufactured from the numeric status. The
512-byte bound and prohibited control bytes are checked before presentation.
Response clones retain the original value/descriptor. All outstanding canonical
operations still settle before the original chunk/body/upload destructors run.
Nested typed HTTP uncertainty and a dispatched read-timeout flag remain visible
on the TypeError cause/uncertain fields without replaying the operation.

Four source/Node controls and all24 existing Fetch adapter controls pass. These
exercise exact/empty/unavailable/malformed reasons, old/new call arities, clone
behavior, ownership, nested uncertain errors and compiler selection. No signed
V7 component, provider, production enablement or whole #691/#745 completion is
claimed. That actual qualification depends on #1184's maintained phase contract
and separately authenticated native products. The existing engine and compiler
splicer identities must still validate; this is not a replacement engine.
