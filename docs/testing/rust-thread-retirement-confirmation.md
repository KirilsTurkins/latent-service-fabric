# Hosted confirmation of the root-retirement component

The normal signed five-call campaign now passes for the exact component and
explicit Rust40 profile below. This supersedes the pending execution boundary
in the [catalogue integration checkpoint](rust-thread-retirement-catalogue.md).
It is not universal Rust executor support, completion of #743/#689, or proof
that the current development merge is qualified.

## Exact matching compiler and native source

Both producers completed successfully at
`cddfb5d016a6311ed0db4673e490dc9caad917dd`, tree
`920ea987da840a6e0a7da4847ee49ae21912d2a1`, with event `push` and attempt 1.
Neither event is relabeled as the historical `workflow_dispatch` origin.

Compiler [41229829427](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41229829427),
job `124621548583`, passed all 34 native controls (10 TLS, 11 wait, 8 sync,
5 executor-root), the emitted result/dispatch controls and all 76 native library
controls. It built the selected sysroot and unchanged application, independently
derived the native core, invoked the real encoder and passed normal-component
proof. Its artifact `13053132953` is 53,111,750 bytes with 131 CRC-verified
members and SHA-256
`615b09e081095cf3af2da98d321ec6948a9b2b92f5366ac6f75bfdb824eb6ada`.

The real encoded component exactly matches the source-projected candidate:
250,281 bytes, SHA-256
`0d66c4828a608e9ec0048205ac6f38539e417f62dbdaeb6b7bdc245aa1c073c8`.
The independently derived core is
`e976d80b529cdc91e5a6f2255d4aeb8db6412a690b039578c75a7dbd76363c22`.
Framing the exact original core yields the 511,729-byte component
`c3135d063fae81a2dc651d4f102b2bcdd53eacf197406104aad4e3b405dfe97c`.
All 239 compiler source entries were reconciled with the earlier independently
Git-verified capture and the exact reviewed changed blobs. Application source,
Cargo manifest/lock and public WIT remain byte-identical to the earlier e3
compiler observation. The complete source/CAS archive retains its exact
7,262-member, 103,848,865-byte expanded shape.

Native [41229829377](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41229829377),
job `124621549313`, passed the original 44 groups/200 named controls and all
91 stages. Artifact `13053891150` is 74,660,568 bytes with 191 CRC-verified
members and SHA-256
`0067b7d3963e1d0843331c934e187276043c143d81879c4291d79cb4008a44a6`.
The strict original reader schema, both receipts, all 182 log hashes and all
five native product hashes were independently checked. The unchanged producer
list/result parsers independently confirm all 200 named passes, none ignored.
The signed consumer also rechecked the 3,795-file native source closure and
151 auxiliary material identities against immutable Git before execution.

## Exact signed five-call result

[Run 41231421695](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41231421695),
job `124626251648`, event `push`, attempt 1, completed successfully at consumer
head `eb5bfd4786f46131394f814e77eef4412d26e5dc`. It uses the ordinary native
node, not #1373's diagnostic node. Artifact `13053847936` is 674,622 ZIP bytes,
154 CRC-verified members, SHA-256
`a09fe2fba877f149c156bce8abf30f54e0e2774baaab98fe3731f04101eaeaff`.
Both programme and node receipts report `passed`.

| Call | Exact expected result | Fuel | Peak reported bytes | Wall microseconds |
| --- | --- | ---: | ---: | ---: |
| pools-cold | `ok: ordinary-default-pools:42` | 361,953 | 7,795,220 | 1,383,289 |
| pools-hot | `ok: ordinary-default-pools:42` | 361,953 | 7,795,206 | 41,811 |
| declared-error | `err: Please enter a name.` | 2,861 | 3,444,587 | 2,437 |
| after-error | `ok: Hello, Ada!` | 3,754 | 3,444,579 | 2,490 |
| pools-after-error | `ok: ordinary-default-pools:42` | 361,953 | 7,795,334 | 43,815 |

The declared-error exit code 3 is the required passing negative case, not a
workflow failure. These are one run's observations, not controlled performance
benchmarks. All calls resolve the same signed revision and original component.
Every consumption record has zero outbound requests, state/blob reads and
writes, log bytes, effects and child calls. The original 32 MiB/five-second
limits and eight Native owners were not increased.

Every call retains a separate retirement receipt: all eighteen required
provider-active counters are zero; active/quarantined cells, queue depth and
quota reservations are zero; all eight activation-scoped topology entries are
zero; and resident service processes, threads and listeners are zero. The node
itself remains an ordinary node-fixed process with eight observed threads,
not a claimed zero-thread host. The same checks pass after deployment deletion.
The node reports clean shutdown and is reaped; the observation peer is closed
and reaped with zero requests. The complete programme uses 27 CLI calls.

The [retained evidence index](evidence/rust-default-threadpool-signed-2026-10-31.json)
binds every invocation and retirement member's actual hash, the complete ZIP,
producer/consumer identities, expected results, measured consumption and shared
zero-owner observations. Its shared evidence is byte-value-equivalent across
all five selected summaries; each original full receipt retains its own hash.
No historical failure has been rewritten or relabeled as this success.

## Consumer selection and remaining boundary

The consumer freezes the successful compiler/native tuples and their exact
`push` events. Complete previous e3 tuples and earlier failed observations stay
historical. The catalogue origin manifest remains the historical source-projection
receipt; this later hosted confirmation does not rewrite what its generator ran.

Both readers reject a wrong workflow event before archive access. The existing
three replay/policy test names and all prior pair-tampering, framing, limit and
capability refusals remain, and passed in the real hosted signed job. The local
native-reader import used an explicit hash-checked producer-source port because
that review checkout was partial; hosted execution did the actual Git/API checks.

The result establishes this finite ordinary default ThreadPool campaign,
including cold/hot progress, declared error and subsequent recovery with the
required retirement witnesses. The original reports deliberately keep
`full743Qualified`, `checkpointQualified` and `privateGraphRuntimeQualified`
false. Wider synchronization/TLS/panic, checkpoint fairness, exhaustion,
networking, cancellation and cross-tenant criteria are not inferred from five
calls. Development merge conflicts and general PR CI/integration still require
separate work. This does not enable the profile in the normal shipping builder
or close either owning issue.
