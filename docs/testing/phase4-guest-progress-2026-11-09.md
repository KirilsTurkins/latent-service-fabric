# Phase 4 guest evidence in progress

This is a progress map for the six **guest components**, separate from the six
external clients. It is not the completion matrix for #389 or #403. The linked
receipts describe their captured source, compiler/build observations, component,
publication, provider profile and local evidence custody. They use disposable
test trust and real local JetStream; they do not establish production trust,
installed distribution, hosted CI, or current development qualification.

| Guest | Local signed-node transaction evidence | Separate immediate HTTP denial |
| --- | --- | --- |
| Rust | [Commit and acknowledgement](evidence/rust-transaction-jetstream-local-2026-11-09.json); [rejection, stale edit, lost response and replay](evidence/rust-transaction-rejection-recovery-local-2026-11-09.json) | [Typed denial after staging](evidence/rust-transaction-http-denial-local-2026-11-09.json) |
| C | [Commit, rejection, stale edit, lost response and replay](evidence/c-transaction-jetstream-local-2026-11-09.json) | [Typed denial after staging](evidence/c-typescript-transaction-http-denial-local-2026-11-09.json) |
| TypeScript | [Commit, rejection, stale edit, lost response and replay](evidence/typescript-transaction-jetstream-local-2026-11-09.json) | [Typed denial after staging](evidence/c-typescript-transaction-http-denial-local-2026-11-09.json) |
| Go | [Commit, rejection, stale edit, lost response and replay](evidence/go-transaction-jetstream-local-2026-11-09.json) | [Typed denial after staging](evidence/go-dotnet-transaction-http-denial-local-2026-11-09.json) |
| Java | [Commit, rejection, original replay, lost response and controlled restart](evidence/java-event-local-observation-e23-2026-11-08.json) | Follow the separate [Java qualification record](java-transaction-qualification.md); do not infer this case from the event receipt. |
| .NET | [Commit, rejection, stale edit, lost response and replay](evidence/dotnet-transaction-jetstream-local-2026-11-09.json) | [Typed denial after staging](evidence/go-dotnet-transaction-http-denial-local-2026-11-09.json) |

The Rust, C, TypeScript, Go and .NET cases used a normal local node built from a
combined source snapshot containing unmerged changes. Each denial variant stages
state and an intent before requiring the typed HTTP permission-denied result; the
corresponding receipt records the empty state/outbox and listener observation.
Go used separate clock and entropy authority, and .NET used separate monotonic
clock authority. The Java receipt identifies a different compiler and native
source pair and an experimental fixture signer; its separate limitations apply.

The common event/replay cases did **not** count guest executions and cannot
prove that recovery avoided a second execution. The [Rust fuel observation](evidence/rust-transaction-fuel-recovery-local-2026-11-09.json)
and [result-boundary observation](evidence/rust-transaction-result-boundary-local-2026-11-09.json)
are narrower than full fuel, memory and output-limit qualification. Per-language
cancellation, crash windows, forged or closed handles, paging and boundary values,
fresh invocation after applicable failures, complete authority and physical
ownership coverage, and maintained CI/distribution qualification remain open.
The C denial variant initially failed by falling through into its scan handler;
the linked receipt records the corrected fresh run rather than concealing it.
