# Security test specification

The completed Phase 1 suite covers authenticated tenant scope, supported import
grants, context/log redaction, bounded wire/value inputs, resource ceilings and
trust-class admission. See the [conformance profile](../../docs/testing/phase-1-conformance.md)
and its owning suites. Phase 2 adds signature/provenance/SBOM rejection, current
policy and revocation fences, digest-verified raw cache and authenticated native
reuse, isolated compiler checks, scoped audit and rollout controls. The
[Phase 2 gate](../../docs/phase-2-completion.md) maps those executed boundaries.
The broader target list below also includes later-phase state, provider handles
and descendant calls, which remain unimplemented.

Required tests include cross-tenant state denial, forged capability handles, expired handles, forbidden imports, signature rejection, untrusted AOT rejection, secret redaction, oversized payload rejection, call-depth exhaustion, fan-out exhaustion, malformed wire frames, and trust-class placement enforcement.
