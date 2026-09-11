# Integration test specification

The completed Phase 1 [conformance profile](../../docs/testing/phase-1-conformance.md)
and owning crate/application tests cover release admission, route compilation,
deployment switching, generic invocation, supported activation capabilities,
cancellation, restart and shutdown. See the
[completion report](../../docs/phase-1-completion.md) for the acceptance map.

Later-phase integration requirements include transactional state commit, outbox
persistence, effect dispatch, node route watching, and exact-release remote
invocation. Their architectural contracts are not running Phase 1 services.
