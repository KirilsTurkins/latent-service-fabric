# Hosted confirmation of the root-retirement component

This supersedes the pending compiler/encoder observations in the
[catalogue integration checkpoint](rust-thread-retirement-catalogue.md).
It does not itself establish a successful signed ThreadPool result, physical
retirement or completion of #743/#689. Those remain separate execution gates.

## Exact matching source

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
five native product hashes were independently checked. Source receipts describe
3,795 native files and 151 auxiliary material identities; the signed consumer
must still recheck these against immutable Git before using the products.

## Signed consumer selection

The consumer now freezes these actual compiler/native tuples and their exact
`push` events. The complete preceding e3 tuples and earlier failed observations
remain historical, including their original event and member hashes. The
catalogue origin manifest remains the historical source-projection receipt;
this later confirmation does not rewrite what its earlier generator executed.

Both readers reject a wrong workflow event before archive access. The existing
three consumer test names and all previous pair-tampering, framing, policy,
limit and capability refusals remain. Their source controls passed locally;
the local native-reader import used an explicit, hash-checked producer-source
port because this review checkout is partial. Hosted acquisition performs the
actual Git and API checks and is the required execution path.

The unchanged signed five-call programme selects the normal native node, not
#1373's diagnostic node. It retains the 32 MiB/five-second/eight-Native-owner
limits, expected outputs, zero-effects checks and per-call physical retirement
witnesses. No test is skipped, and no earlier failed signed result becomes a
pass merely because these producer jobs succeeded. The PR remains draft until
actual signed results and integration requirements are satisfied.
