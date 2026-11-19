# SDK milestone Daybreak integration

This review tracks implementation work for [SDK milestone #10](https://github.com/KirilsTurkins/latent-service-fabric/milestone/10). The integration branch is `handoff/sdk-daybreak-20261119-review`, reviewed in [#2183](https://github.com/KirilsTurkins/latent-service-fabric/pull/2183). It contains implementation changes, not only preserved-source references. It is still incomplete and does not close the milestone or its tickets.

## Integrated implementation

| Reference | Integration | Remaining qualification |
| --- | --- | --- |
| #745: [paused TypeScript socket receive](https://github.com/KirilsTurkins/latent-service-fabric/compare/43e13c89aa098197e8d3f5a8c3e36e21a2233923...025c9e7464a7a7b5670e8f2110019917e3d9baa5) | `27d8552` retains one bounded receive window until resume or explicit destruction, preserves data-before-EOF ordering and original borrow acknowledgements, and keeps the newer end-callback implementation. | Pinned frontend, signed guest and installed-provider qualification on the integration head. |
| #736, #742: [lazy Go owner backing](https://github.com/KirilsTurkins/latent-service-fabric/compare/43e13c89aa098197e8d3f5a8c3e36e21a2233923...dad93d7cef371fce956cb60ac8bfb3588a686195) | `72886ae` prepays exact replacement storage while the old backing remains charged, rechecks admission after allocation and retains the default-off first-owner observer. | Current-head host tests and signed Go qualification. The earlier narrow signed first-owner result is not full Go or current-head evidence. |
| [#2161](https://github.com/KirilsTurkins/latent-service-fabric/pull/2161): native stack physical custody | `404c05e` combines the strong-only context handle with lazy owner storage. Original metadata charges survive actual backing deallocation, including last-clone and concurrent drops. | Pinned Rust execution of the isolated allocator and combined-profile controls. |
| [#2151](https://github.com/KirilsTurkins/latent-service-fabric/pull/2151): cached Java executor handoff | `6e251b0` carries real idle-worker handoff and its ownership controls. Integration-only [#2186](https://github.com/KirilsTurkins/latent-service-fabric/pull/2186) targeted this branch, not development. | Pinned JDK 25, actual Activation/private-ledger controls and signed Java component qualification. |
| [#2156](https://github.com/KirilsTurkins/latent-service-fabric/pull/2156): Java receipt model counts | The production correction already merged through [#2055](https://github.com/KirilsTurkins/latent-service-fabric/pull/2055) remains intact: 205 model bodies and 28 generated callbacks. `444f1a0` adds the remaining stale-count rejection cases. | These counts identify a reviewed compiler model; mocked receipt tests are not component execution evidence. |

## Continuous allocator controls

`444f1a0` registers `tools/runtime_owner_storage_witness.rs` as an isolated, harness-free Cargo test with a source-bound CI suite contract. The test calls the actual owner-storage implementation and observes exact allocation, deallocation and allocation refusal without sharing the libtest allocator.

```sh
cargo test --locked -p latent-wasmtime --test runtime_owner_storage_witness
```

The `Native stack physical custody` workflow enables the stack allocator witness separately from the incompatible Go overlap allocator. It also compiles and executes the authenticated combined-profile tests. Neither feature selects a production guest profile or increases resource grants.

```sh
cargo test --locked -p latent-wasmtime --lib \
  --features development-stack-custody-witness,development-rust-http-combined \
  native_stacks::tests:: -- --test-threads=1 --show-output
```

## Local validation recorded on November 19, 2026

The Java cached-factory reference control passed both on JDK 21 and against the actual SDK port source with its private host ledger. All ten cached-handoff owner modes and three replacement-worker modes passed. The two focused Python wiring modules passed 35 tests; Java model-integrity controls passed 56 tests. These results do not substitute JDK 21 for the pinned JDK 25 qualification or prove signed component execution.

The TypeScript socket module ran 31 tests: 27 passed, two pinned-frontend controls were skipped, and two could not execute because the retained source archive omitted the TypeScript SDK files. The paused-receive regression itself passed. The two focused CI inventory tests passed after registering the new allocator target; broader repository-contract tests require the complete checkout.

The local environment had no Rust or .NET compiler, and the connected build machine was offline. Rust execution and full integrated qualification therefore remain CI gates. No green CI result is claimed by this document.

## Unintegrated correctness blockers

[#744's C checkpoint prototype](https://github.com/KirilsTurkins/latent-service-fabric/compare/7551eeefee1a38c8cf66e5eaa4b91f78ca926759...32f91fe901b5923ddd5846e8509ecba7ce475436) remains unselected and is not imported into this integration. Its accepted body is call-free and read-only; it refuses the real pthread loop. Linked call effects, recursive and aliased lock ownership, non-suspendable SDK scopes, lazy no-concurrency behavior and real-engine sibling progress remain required before selecting it.

[#2163](https://github.com/KirilsTurkins/latent-service-fabric/pull/2163) is not integrated. Its pending `ManualResetEventSlim` wait produces `AsyncLocal` context-change notifications absent from the CLR reference. The helper's default execution-context dispatch cannot be accepted as ordinary event-wait semantics. The mismatch and the canceled qualification remain blockers; neither the reference assertion nor production selection has been weakened.

Separate work remains recorded in [#690](https://github.com/KirilsTurkins/latent-service-fabric/issues/690), [#745](https://github.com/KirilsTurkins/latent-service-fabric/issues/745) and the [milestone epic](https://github.com/KirilsTurkins/latent-service-fabric/issues/677). Integration of the changes above does not complete those broader requirements.
