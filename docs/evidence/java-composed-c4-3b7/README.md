# Executed signed Java composition, context and canary qualification

The scoped campaign passed with four independently compiled Java components,
ephemeral approved signing policies, enforced package admission and an actual
loopback HTTP node. The earlier complete build attempt remains **failed** in
`original-fresh-guests-failed.json`; its canary window closed before the first
sample after a 4.96-second cold target inspection. The successful campaign
reused those unchanged signed component bytes in a fresh disposable node and
used the maintained qualifier's finite 15-second observation window. It did not
replay an uncertain management write against the earlier node.

| Owner | Exact source |
| --- | --- |
| Four real Java/TeaVM C/WASI builds | `c4e8c6c0fe31565ee67db8f699c727bcfdcfa4e9` |
| Five original native runtime and packaging executables | `66f2a031a32f268604a340204a4e7fd0270af3b7` |
| Successful HTTP/context/canary qualifier | `3b7d579e2a856896c6c3947e11045692dec2ec47` |

The native executables were reused and hash-verified; they were not rebuilt from
the newer Java or qualifier commit. The Rust application, crate, Cargo and
`.cargo` sources have no difference between the native and Java build commits.
Only `tools/java_http_composition/qualify.py` changed between the Java build and
successful HTTP campaign. `summary.json` contains the original executable,
component, source and SDK binding digests. Every copied receipt and build input
is verified by `raw-manifest.json` or `build-manifest.json`. Retained WIT,
contracts, descriptors, compiler recipes, source inventories and original
`BUILD-COMPLETE.json` files are under `builds/`.

The maintained entry point remains
[the composed Java qualifier](../../../tools/qualify_java_http_composition.py)
and the commands in [its execution guide](../../testing/java-http-composition.md).
It uses the real Java compiler, authoritative Rust signing/canonicalization
owners, ordinary supply-chain verifier, operator CLI and activation journal.
The fixture contains no production signing material or provider account.

| Requirement | Executed evidence |
| --- | --- |
| #708: same typed Java operation under standalone and actual HTTP ingress | `standalone.json` and `actual-http-campaign-passed.json.composed`; the same signed domain publication is selected explicitly. |
| #708: reproduce the former global allocation failure | `former-profile.json`: Preparation/SignatureAllocationLimit, fixed 512 + lifting allowance 2097152 × multiplier 76 = 159384064, bound 67108864, exact profile digest retained. Public invocation remains redacted. |
| #708: finite service/web selection and safe/over-limit values | Actual current target preparation reports service 128 KiB/16 MiB and buffered web 2 MiB/64 MiB. The qualifier executes wide/nested records, full-width u64, UTF-8/NUL, strings and lists; over-limit/malformed requests reject and subsequent normal requests pass. Uncalled exports participate in preparation. |
| #708: owners survive cancellation and routing changes | Actual cancellation retires the parent and Service child before a fresh HTTP request. Canary promotion retains two live cells and identical CPU/memory quota; explicit cancellation then releases all physical owners. |
| #708: maintained client, canary, stale targets, drain and rollback | The generated client executes eight requests and preserves full-width values. Sixteen actual canary samples are attributed to two distinct publications; candidate 10/10 succeeds with no failures or unattributed samples. A stale trigger returns 503. Original promote/rollback operation receipts and a fresh successful route are retained. |
| #711: intentional one-export architecture and real type reuse | Independent typed domain and generated `latent:web/application@0.1.0` adapter compile/sign/admit/execute. The domain's resource-free shared types import appears in `preparation.typeImports`; its clocks remain callable imports and no type provider/grant is added. |
| #711: explicit public selection and stale generation | `generation-cases/generation-cases.json` retains private administration/publishing/provider-event, duplicate route/client, wrong contract, invalid deadline and stale source/type-width rejections. Actual private/unselected paths return 404, declared errors 422, Java exceptions 500, and fresh invocation succeeds. |
| #712: actual identity and remaining grants | Authorized activation roots/tree records actual Trigger/Administrator parents and host-derived Service children whose caller service is the adapter. Exact narrowed CPU, memory, wall-time, child-call and deadline observations are retained, including absent/present/expired deadline and reduced-parent cases. |
| #712: context and authority boundaries | Wrong child-principal clock grants produce actual Binding/GrantDenied; spoofed headers and supplied lineage confer no authority. The separately signed ordinary context-import component rejects before guest work, then fresh composition succeeds. Five metadata values below the CLI's 32 KiB aggregate bound pass; nine values above it reject before dispatch. This does not claim a host 1 MiB context overflow. Trusted source/actor observations remain unavailable to this ordinary guest. |
| #716: actual read-only target resolution and coherent binding | Actual `route target` RPC observes both independently built targets, complete preparation identities and provider/policy pins. Another tenant receives no private candidates; invoke-only authority cannot inspect. Retained old policy plans report stale after revocation/restore until a new explicit deployment operation and pinned trigger update. Canary inspection reports two candidates with no implicit selection and a deterministic selection only with supported routing input. |
| #717: independent exact-source policies and negative admission | `paired-trust.json` retains distinct builder identities/keys, three equivalent input permutations, nine real verifier negatives, stale grants and six admission cases, including local corrupt artifact rejection. Exact per-source builder requirements are preserved. The former raw-order construction is rejected. Successful and denied management outcomes are recovered with their original operation IDs. |

The runtime's existing codec/type-work and authenticated native-cache restart
tests remain separate evidence owners. In particular,
`buffered_web_profile_change_after_restart_cannot_reuse_a_stale_native_image`
checks the stale native image against changed profile identity; this campaign
does not claim that its Java guests were loaded from authenticated AOT cache.
The WIT minimizations and generated binding checks are maintained in the Java
SDK tests and `wit-composition/` fixtures, separately from actual guest execution.

All earlier failed attempts remain retained, including the source-36 and
source-66 scoped paired-trust reports and the original C4 failed aggregate.
The historical private alpha.4 reporting application was unavailable and was
not executed. This report qualifies the synthetic stateless composition scope.
Delivered native frontend checks against standalone and provisioned nodes are
the separate #710 qualification owner; they have not been inferred from these
receipts. Actual Java transactions, HTTP result recovery and crash/dispatch
scenarios remain the separate #718 Phase 4 qualification scope.
