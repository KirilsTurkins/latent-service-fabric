# TypeScript compiler elimination and reached default callbacks

[Run 39696684411](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39696684411) built two ordinary TypeScript components at source `4109d63e3d31483a7579690477acdf845a80a0eb` and completed eight signed runtime calls. The outer run **failed** after those calls because its controller attempted to exclusively create the same progress file twice. The [retained observation](evidence/typescript-elimination-2026-10-22.json) preserves that failure and the eight independently verified results.

Both builds capture the same two-level npm dependency. Its ordinary default clock callback calls `Date.now()`. One constant application root edge changes from `false` to `true`; the dependency sources, profile, grants, WIT and limits stay identical. The normal esbuild contribution witness records zero callback bytes for the eliminated edge and 144 bytes for the reached edge. This establishes elimination of one exact application module, not absence of a clock API from the embedded JavaScript engine or arbitrary dependency compatibility.

| Call | Eliminated edge | Reached edge |
| --- | --- | --- |
| Catch, seed 7 | Alternate 42, no refusal | Native clock refusal caught, alternate 42 |
| Catch, seed 11 | Alternate 62, no refusal | Native clock refusal caught, alternate 62 |
| Uncaught, seed 13 | Deliberate post-guard guest trap | Uncaught guest trap; precise trap cause unknown |
| Catch, seed 19 | Fresh alternate 102, no refusal | Fresh alternate 102 after the trap, refusal caught |

All eight calls retired five physical owners and showed all 18 available provider counters zero. Both nodes shut down cleanly and were reaped; both observation peers received zero requests. Each variant completed its normal 20-command compiler/package build and signing. Whole-archive verification checked 281 member CRCs, 191 executed Git materials, 110 recipe rows and 63 source rows per build, all eight raw results and 88 retained command streams.

The eliminated component is 12,473,660 bytes with SHA-256 `6ae4b122d966295b8e581efc45b0f8d44651840e4a120d4a81672838a3d2d6c4`; the reached component is 12,479,642 bytes with SHA-256 `b42e26b701983fc7cbd3a6d51f8c9072937ff3af2ef27d24a6f94497a10f2262`.

Two controller lines are corrected: progress files now have distinct variant names, and final report generation uses the actual `sourceInputs` build field. A cheap control executes those exact source statements over the retained actual build records and validates both machine reports without repeating compilation or runtime calls. These reports are derived after the failed run, as recorded explicitly in the evidence. The original run did not emit them or reach its final source/products fence, and the whole qualifier is not claimed to have passed. The other 190 executed materials remain byte-exact.

Compiler identity records retain the original 4,431 installed files plus the normal 18,966-byte core-v2 adapter (4,432 selected files). Compiler payloads and generated adapter bytes were not uploaded; this unsigned observation is not a hermetic-build attestation. Native products preserve their historical three-product `f244` and two-product `f625` compilation provenance; no native host or JavaScript engine build was repeated.

The earlier [explicit fallback programme](typescript-explicit-fallback.md) retains its separate successful run. This finite reached/eliminated pair advances #679. Cross-language classification, initialization paths, complete profile/limit/lifecycle reporting and aggregate native memory ownership remain open; it does not close the ticket.
