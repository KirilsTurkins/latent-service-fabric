# Independent Java pair: retained signing and admission evidence

The [summary](summary.json) records the paired signing, admission and direct versus
composed execution subcampaign from actual source
`36a10fc7cee5318d8ceb18efd31864c028c4452f`. Its seven original receipts are copied
byte for byte and bound by SHA-256 and size. The
[overall receipt](QUALIFICATION-FAILED.json) remains **failed** at the HTTP context
assertion, `java-context-http-outcome`. This evidence does not qualify the complete
Java HTTP/context/cancellation/canary pipeline.

The independently compiled domain and generated adapter have distinct component,
package, source snapshot, compiler observation, builder identity and builder key
identities. Their [build receipts](builds/domain/BUILD-COMPLETE.json) and
[adapter receipt](builds/adapter/BUILD-COMPLETE.json) report actual TeaVM C, WASI
and Component Model outputs. The [paired trust receipt](paired-trust/paired-trust.json)
retains authoritative Rust canonical bytes/digests, three equivalent input
permutations, eight verifier rejections and two actual expired admission grants.
Each grant first passed its currentness checkpoint; after its two-second TTL,
the original grant failed with `state-conflict` / `signature-stale-proof` and its
fenced action was never entered. These retained receipts create no authority.

Four invalid-evidence publications reached the enforced node, were rejected,
and recovered their original persisted zero-generation operation. The altered
component was rejected by the real package validator before dispatch. All five
negative catalogs stayed empty. The former raw-input ordering mistake retains
both the wrong supplied digest and the authoritative builder digest, without
changing approved trust to make the invalid policy pass.

The [standalone receipt](standalone/workflow.json) records successful signed
publication, deployment and typed invocation. The [HTTP receipt](http/workflow.json)
records the original deployed pair and current preparation profiles, direct
versus composed value comparison, HTTP 200, and eight generated-client checks,
including full-width values and a fresh call after rejection. The later context
failure and subsequent fixture correction remain separate observations.

All keys and policies belong to disposable short-lived demo trust. No private
signing keys, production credentials or production approval are included. This
record has expired and cannot authorize publication or execution. Reproduce
with new approved test identities through the
[maintained paired recipe](../../operations/paired-capsule-signing.md); preserve
each original failed attempt. The subsequently added revoked-builder-identity
case requires its own newer actual receipt and is not retroactively added here.
