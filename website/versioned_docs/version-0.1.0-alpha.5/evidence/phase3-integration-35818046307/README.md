# Current Phase 3 integration evidence

[CI run 35818046307](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35818046307)
passed for source `193d52c37635026de416feffd4a2dfd57d082451` in
[PR #537](https://github.com/KirilsTurkins/latent-service-fabric/pull/537).
Its actual PR checkout is `58965f399a116eb713dd4a5fc966f682167204f7`.
That checkout, the selected source and development squash
`532364d697b1b93f2b3187e0df367f878023e91a` have identical Git trees.
The [summary](summary.json) records both identities, artifact IDs/digests and
individual receipt hashes. The 21 original JSON receipts below retain their
exact downloaded bytes.

| Boundary | Current observed result | Retained evidence |
| --- | --- | --- |
| Six executable clients | Rust, TypeScript, Go, C, Java and .NET each pass all 18 assertions. Together they record 54 distinct activations, six operation receipts, 24 physically closed held requests and six clean node shutdowns. All use the same node, CLI and fixture identities. | [Matrix](sdk/matrix.json), [Rust](sdk/rust.json), [TypeScript](sdk/typescript.json), [Go](sdk/go.json), [C](sdk/c.json), [Java](sdk/java.json), [.NET](sdk/dotnet.json) |
| PR security matrix | 27 executed test entries in 13 groups; 57 bounded commands, source-clean input and removed temporary outputs. Its explicit profile exclusions remain in the receipt. | [Security](security-pr.json) |
| Provider and renderer integration | Both bounded lanes pass: 19 provider selections and eight renderer selections. | [Lane aggregate](lanes/receipt.json), [providers](lanes/provider.json), [renderer](lanes/renderer.json) |
| Browser boundary and public application | Chrome 152 checks DOM reuse, navigation, escaping, CSP, MIME and base-URL attacks. The application case additionally invokes the application component without management RPCs, ambient fetch credentials or cookie authentication. These receipts use controlled Node SSR and explicitly make no component-rendering claim. | [Build](browser/build-receipt.json), [reference boundary](browser/browser-receipt.json), [application boundary](browser/browser-application-receipt.json) |
| Actual Angular component on the protected node | Real Angular build and enforced `external-capsule-v1` admission with isolated AOT, staged rollout, deployment-CAS rollback, retained native cache across restart and clean shutdown. The receipt declares T1 and `reproducibility: not-checked`. | [Angular T1 workflow](operator/angular-t1-receipt.json) |
| Static/CSR publications | Two signed versions round-trip through exact OCI digests and real browser navigation. Deep-link reloads, lazy scripts, mounted generator redirects, missing-file 404s, cutover/rollback and revoked/foreign authority checks pass. Before, dormant and after snapshots show zero activation reservations and no granted execution-cell leases. | [Static-site workflow](operator/static-site-receipt.json) |
| Operator, publication, outage and security profiles | Delivery/rollback, independent publication authority, offline retained invocation and explicit protected-profile refusal scenarios pass. | [Operator](operator/operator-receipt.json), [publication](operator/publication-receipt.json), [offline](operator/offline-receipt.json), [security profile](operator/security-profile-receipt.json) |
| Bounded dormant-resource regression | The exact `phase2-dormant-32-r3` profile passes with 32 releases, 16 deployments and 32 invocations. This is a bounded regression observation, not a production-scale or throughput campaign. | [Resource receipt](operator/resource-receipt.json) |

The detailed Phase 3 resource campaigns retain their original sources and
measurements in the [gate review](../../phase-3-gate-review.md). This integration
does not relabel those measurements or replace their declared limits.

Native installed-bundle qualification and protected publication have separate
[release evidence](../../development/native-release-gate.md). SDK receipts here
explicitly set `installedBundleQualified:false`; the SDK matrix also leaves
browser qualification to the separate browser workflows. Human guide review,
the complete-site Pages deployment and the final Phase 3 decision are separate
requirements. These CI results do not manufacture review identities, qualify
T2 guest-process containment or authorize a production/hostile-multitenancy claim.
