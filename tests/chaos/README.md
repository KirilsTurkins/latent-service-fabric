# Chaos test specification

This is the cross-phase fault-injection target. Phase 1's delivered catalog
recovery, cancellation, response ambiguity, containment and shutdown coverage is
mapped in the [completion report](../../docs/phase-1-completion.md). State backends,
external providers, distributed route watches and AOT distribution below require
their later-phase implementations.

Inject node termination, execution-host termination, state-backend disconnects, provider timeouts, route-watch interruption, partial artifact downloads, AOT cache corruption, response loss after commit, and response loss after provider completion.
