# TypeScript runtime issue 745: current acceptance checkpoint

Remote issue 745 was refreshed on 2026-10-08; its body is unchanged since
2026-09-30. It is open. The current private source is
`7b69ba1fd8fa2dd6e82d5964399a7e0c946a28ba`, tree
`66d303e482ab508e9973c4551ee583778fe7f213`. No push, PR, merge, issue closure,
release support, or signed runtime qualification is claimed.

The source-owned engine now contains the unchanged pinned native text codecs
required by generated string bindings. The prior real service caller failed
Wizer with `TextDecoder is not a constructor`; that failure remains retained.
The fresh complete engine and five maintained compiler/Wizer builds passed
with matching current SDK and native-engine source identities. All artifacts
are retained on the host, and all owned compiler/container processes stopped.

| Acceptance requirement | Current implementation and genuine proof | Remaining qualification |
| --- | --- | --- |
| Actual async exports/imports, unresolved root Promise, thenables, errors and final WIT values | Intrinsic Promise hooks, genuine job queue, source-owned P3 splicer and readiness; full type graphs preserved. Actual complete engine and real service interface compile/Wizer passed. Earlier 44 intrinsic controls remain separately attributed. | Signed root suspension, rejection/thenable/final results, actual service host suspension and sibling witness. |
| Bounded jobs/event turns, ordering and run-to-completion | Native pre-admission and queue hooks; one readiness set for timers/imports; no background worker or callback inside host import. Source controls passed. | Real signed ordering/reentrancy and synchronous CPU/fuel/deadline containment. No worker-context support claim. |
| Timer subset and AbortSignal behavior | Timeout/clear, finite fixed-rate coalescing interval/clear, checked timeout conversion, original Abort/Event lifecycle and deferred safe retirement. Original 15-case guest compiled/Wizer passed. | Actual timers, recurrence/clear, root deadline, Abort races, callback exception and timer storm/exhaustion under unchanged ceilings. |
| Root settlement versus accepted work and drain | Root lifecycle, accepted timer/import drain, unhandled rejection and opaque pending-work denials; actual GC before retirement checkpoints. | Signed root/callback/unhandled/opaque failures and accepted-work drain; managed-idle and cleanup observations. Store destruction cannot be successful completion. |
| Jobs/reactions/captures/results/heap/native accounting and late completion | Original activation broker registrations before allocations; actual weak-GC collection and out-of-GC acknowledgements; asynchronous cancel retains stable canonical buffers/handle through terminal drop and typed lifting. | Real budget conservation, memory/fuel/owner exhaustion, cancellation/trap/late-wake cleanup, physical owners/cells/quotas idle, guest/native costs. |
| Named package-independent automatic source profile | Explicit source-bound profile; engine and splicer envelopes cross-bound; globals installed before application modules; missing/malformed inputs fail. No public-splicer fallback. | Actual signed ordinary library qualification before support promotion; final coherent source integration/review. |
| Standard stream/DNS/socket/TLS scope | Remains unsupported pending approved networking semantics; no ambient fallback or grant widening introduced. | Networking work is conditional scope and has no completion claim here. Promise/timer slice may land independently, as the issue permits. |
| Snapshot isolation and fresh state | Runtime effects/pending work denied at snapshot; selected scoped clocks are lazy per fresh Store. Actual source-owned Wizer ran; no process/network/grant was added to guest. | Signed snapshot effect denials and fresh cross-tenant activation state; cancellation and dormant ownership evidence. |
| Builder, provenance, diagnostics and toolkit | Maintained compiler/CLI/profile hooks; exact selected core/envelope/splicer inventory materials after immutable rechecks; automatic matching candidate toolkit input bundle. 265 authentic-Git Linux controls, zero skips; coverage 88/269/141; three current 64/72 MiB capacity controls passed. Actual managed pack/unpack/profile selection passed. | Normal CLI contracts/package/sign using actual ordinary default products; actual assembled toolkit qualification and final current synchronous/direct-SDK regression gate. Raw compiler output is not a completed package. |
| Unmodified published npm code and shared qualification inputs | Four original published archives reverified, native lock reviewed, conditions `[]`, lifecycle scripts never run. Five unchanged ordinary branches compiled/Wizer passed without library patches, injected LSF transport or manual pumping. | Five actual signed npm executions, reference differences, cost/cleanup evidence and source-bound handoff to 694/740. These downstream tickets do not block 745 closure. |

The complete source/native/compiler evidence index is
`typescript745-codec-matched-compiler-delivery-20261008-r2.json`, SHA-256
`d8eb7283f1f4063a752152d79b87fa15b9d94219b3d8b677cdc191aecf280d47`.
The executable command plan for the next gates is
`typescript745-normal-signed-next-gates-20261008-r1.json`, SHA-256
`7dca205d7ea03eada7f0d9a4d72f31d6f99a924e7714e976daa7068d259d47b5`.

The next external prerequisite is the owner's actual ordinary-default
five-product native tuple for source `120ceab09a2c4a96d4e13ce8a5b3363983b06999`.
Its prepared producer is `c684-current120-default-native-20261008-r1/run.py`;
no completed tuple receipt exists at this checkpoint. Root/networking owns
that producer. Historical 66/e7 products, development-test products and foreign
workloads were not adopted. A different native source must be attributed
explicitly; final matching integrated-source qualification is still required.

Issue 745 is not closure eligible. Every missing required runtime case remains
pending, rather than a passing skip or a source-only qualification claim.
