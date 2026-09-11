# Security test specification

The completed Phase 1 suite covers authenticated tenant scope, supported import
grants, context/log redaction, bounded wire/value inputs, resource ceilings and
trust-class admission. See the [conformance profile](../../docs/testing/phase-1-conformance.md)
and its owning suites. The broader target list below includes later-phase state,
signing/AOT, provider handles and descendant calls; those surfaces are unavailable
in the standalone Phase 1 runtime.

Required tests include cross-tenant state denial, forged capability handles, expired handles, forbidden imports, signature rejection, untrusted AOT rejection, secret redaction, oversized payload rejection, call-depth exhaustion, fan-out exhaustion, malformed wire frames, and trust-class placement enforcement.
