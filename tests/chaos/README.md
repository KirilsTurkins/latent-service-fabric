# Chaos test specification

This is the cross-phase fault-injection target. Phase 1's delivered catalog
recovery, cancellation, response ambiguity, containment and shutdown coverage is
mapped in the [completion report](../../docs/phase-1-completion.md). Phase 2 adds
failed registry transfer, corrupted raw/native cache recovery, trust invalidation,
durability cutpoints, rollout/revoke concurrency and bounded compiler cleanup;
see its [completion map](../../docs/phase-2-completion.md). State backends,
external providers, distributed route watches and distributed AOT delivery still
require later implementations. Local authenticated native reuse does not establish
a distributed native-code service.

Inject node termination, execution-host termination, state-backend disconnects, provider timeouts, route-watch interruption, partial artifact downloads, AOT cache corruption, response loss after commit, and response loss after provider completion.
