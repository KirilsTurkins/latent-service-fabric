<!-- LSF-WIKI-MANAGED -->
# Language SDKs

Rust, Go, TypeScript, Java, .NET and C provide **interface-only** client and guest models. They ship no network transports, serializers, retries or automatic cancellation forwarding. Executable fake-client fixtures establish interface expressiveness; actual server/wire evidence is separate.

Requests preserve optional activation/root/parent IDs. Absence requests server assignment; present-empty identity is invalid. Lineage is correlation, not authority. Parent without root is rejected by Phase 1.

All six clients express status/cancel by known activation ID. Cancel preserves `accepted`, `already-terminal` and `not-found` separately from transport errors. Dropping a local task/context/signal/wait is not acknowledged server cancellation. After a lost response, retain identity and inspect status without automatically reinvoking; status can be evicted or lost at restart.

C borrows inputs and callback response values for documented lifetimes. Async implementations copy retained inputs and complete operations exactly once. The opaque local invocation handle is not an activation ID. Current identity/cancel changes affect C ABI and some language construction shapes; rebuild consumers. No stable alpha ABI is promised.

`tools/validate_sdks.sh` runs Go, TypeScript, Java, .NET and C fixtures; Rust uses `cargo test -p latent-sdk`. Use pinned prerequisites and validation tiers.

Authority: [SDK contracts and compatibility](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/sdk/README.md). See [Contracts and APIs](Contracts-and-APIs) for declaration versus runtime support.
