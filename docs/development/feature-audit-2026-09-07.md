# Feature audit — September 7, 2026

The audit reviewed `development` at `d5a7692`, the Phase 1 milestone and every
open issue/PR, with the closed foundation tickets used to check delivered scope.
The repository's integration branch is `development`; there is no `dev` branch.
Corrections are on `chore/feature-audit-2026-09-07` in
[PR #69](https://github.com/KirilsTurkins/latent-service-fabric/pull/69).

Phase 1 foundations are implemented and have executable regression coverage.
The complete standalone release-to-invocation product remains unfinished.
Passing the checks below does not close the Phase 1 gate or the outstanding
correctness issues found by this audit.

## Feature inventory

| Feature group | Current implementation and validation boundary | Remaining owner |
| --- | --- | --- |
| Build and contracts | Locked Rust workspace, generated WIT/Protobuf bindings, seven JSON Schemas, descriptor checks, cross-language SDK compilation, deterministic test utilities. | #2 and #36 closed; SDK parity follow-up #65. |
| Declarative manifests | Bounded JSON decoding, exact numeric handling, duplicate-key/depth/collection limits, canonical encoding and stateless Phase 1 validation in `latent-manifest`. | #3 closed. |
| Release storage | `DirectoryArtifactRepository`: exclusive ownership, component digest verification, bounded indexes/pages/recovery, local publication, retry and restart. No guest preparation during catalog operations. | #4 closed; durability/integrity follow-ups #66 and #68. |
| Deployment and routing | `DirectoryDeploymentRepository`: atomic persisted deployment state, immutable generations, tenant/namespace checks, deterministic revisions/weighting, pinned snapshots and recovery. | #5 closed; management repository prerequisite #67. |
| Budgets and cancellation | Effective monotonic deadlines, budget intersection, concurrent consumption/reservations, terminal reconciliation and cancellation registries in core/node/executor. | #6 closed; full runtime integration remains #9–#11. |
| Admission and scheduling | Phase 0 fixed generic cell pool with bounded FIFO acquisition, cancellation, affine leases, return/quarantine and race tests. General admission and fair scheduling are interfaces/pending work. | #7 and #8. |
| Wasmtime and capabilities | Real Phase 0 echo/containment backend, fresh stores, fixed engine/cache topology, fuel/deadline/trap/memory containment, context/log imports. Generic dispatch and hardened clock/context/log are pending. | #9 and #10. |
| Activation orchestration | Phase 0 runner and new budget/cancellation primitives have unit/integration tests. Production orchestration, retained status and cleanup composition are pending. | #11. |
| Invocation and management RPC | Generated messages, clients/server wrappers and conversion helpers exist. Merged code does not provide the standalone service implementations/listeners. | #12, #37, and #14. |
| Telemetry and operations | Phase 0 measurement/collector infrastructure exists. Shared Phase 1 telemetry, inventory, health, draining and operational lifecycle are pending. | #13 and #14. |
| Operator CLI and SDKs | `latent` and `latent-control` are placeholders. SDKs define compiling interfaces; they do not implement transports. `latentd phase0-spike` remains the executable demonstration. | #15 and SDK contract follow-up #65. |
| Conformance and evidence | Maintained Rust/Python regression tests and real-component fixtures accompany retained Phase 0 evidence. The full Phase 1 CLI/node conformance gate is pending. | #16. |
| Later phases | OCI/signing, general policy/capability providers, ingress/triggers, blobs, state/effects, commits, workflows, cluster routing and remote invocation remain architectural seams/research. | Roadmap Phases 2 onward; Angular hosting remains Phase 3 #44. |

The [roadmap](../roadmap.md), [API map](../api-surface.md) and
[validation baseline](../../VALIDATION.md) now distinguish these implementations
from planned contracts.

## Minor corrections

- Normalize a submitted capsule manifest before comparing immutable publication
  retries. A valid reversed import order previously published once but failed
  an identical retry, including recovery from an uncertain directory sync. A
  tiny regression covers ordinary duplicates, sync-failure retry and reopen.
- Seek directly to the artifact-list cursor instead of repeatedly traversing
  every earlier digest. Existing entry/byte-boundary pagination tests remain.
- Move the durable 100,000-release CI step behind manual `workflow_dispatch`
  input `run_catalog_scale`, default `false`. Ordinary catalog/supervisor checks
  remain automatic.
- Make copied collector-runner test fixtures model native kernel identity
  consistently on WSL/container hosts. Real collectors retain their native-host
  restrictions; fake workload tools fail on unexpected execution, and tests
  exercise WSL/container rejection explicitly.
- Refresh stale feature descriptions, schema count, crate summaries and test
  documentation. Remove the validator warning that treated any implemented
  binary as a scaffold violation, retaining rejection of implementation
  placeholder tokens. Use the existing `area:contracts` label in the
  architecture issue template.

## GitHub findings and disposition

| Finding | Disposition |
| --- | --- |
| SDK calls cannot provide the ID needed to cancel/inspect their own unfinished invocation; C cancellation lacks transport-error separation. | [#65](https://github.com/KirilsTurkins/latent-service-fabric/issues/65), Phase 1, priority P1, size M. |
| New artifact roots do not synchronize the parent chain that makes acknowledged releases reachable after a crash. | [#66](https://github.com/KirilsTurkins/latent-service-fabric/issues/66), Phase 1, priority P1, size M. Source-level durability finding; no power-loss experiment performed. |
| Deployment RPC generation preconditions/receipts and tenant pagination cannot be implemented atomically through the current repository port. | [#67](https://github.com/KirilsTurkins/latent-service-fabric/issues/67), Phase 1, priority P1, size L; extracted repository prerequisite of #37. |
| A valid-JSON one-byte mutation changes persisted release metadata without changing its digest or causing reopen/fetch rejection. | [#68](https://github.com/KirilsTurkins/latent-service-fabric/issues/68), Phase 1, priority P1, size M. Confirmed with one tiny production-API artifact in 0.04 seconds. |
| Weighted routing integration lacks an explicit key-source decision. | Clarified #11: define derivation/default/retry semantics and small deterministic resolution tests. A new wire field is unnecessary unless caller-controlled affinity is intended. |
| Budget-wrapper normal-return finalization is insufficient for dropped/panicking futures. | Recorded against the existing cleanup scope of #11; no duplicate implementation ticket. |
| Epic #1 marks open management ticket #37 complete. | Corrected its checkbox and the completed Phase 0 handoff; added #65–#68 as completion dependencies. #16 and #37 reference their new prerequisites. |
| PR #52 implements an older alternative for already-completed #5. | Closed as superseded by merged #64; its branch is retained. |
| PRs #53 and #54 remain open. | Retained for #13/#12. At review, #53 conflicts with `development`; #54 is mergeable but blocked. Neither is counted as delivered functionality. |

New issues use the repository's existing area/size/priority labels and the
**Phase 1 — Single-Node Stateless Fabric** milestone. General SDK transports,
signed supply chains and other later-phase features were not added as Phase 1
requirements.

## Validation evidence

Validation used the existing pinned Linux toolchain container on Docker/WSL,
with a copied checkout and an isolated target directory. Windows compilation
was also attempted: catalog directory synchronization fails with access denied,
and the full shell/archive suite requires Linux tools. Those results are not a
Windows support claim; Linux is the documented persistence/reference platform.

| Check | Result |
| --- | --- |
| Formatting and whitespace | `cargo fmt --all --check` and `git diff --check` pass. |
| Ordinary Linux workspace tests | 214 passed; no failures. Command below excludes the 100,000-entry index unit and large metadata memory probe in addition to the default ignored tests. |
| Workspace Clippy | Passes with existing warnings; this audit does not claim a warning-free workspace. |
| Exact SDK toolchains and surfaces | `tools/validate_sdks.sh` passes for Go, TypeScript, Java, .NET and Zig/C; Rust SDK is included in workspace tests. |
| Repository/contracts Python suite | All 186 tests pass; repository and foundation validators and Phase 1 descriptor validation pass. |
| Collector fixture correction | 60 focused Python tests pass, including every previously failing Linux/WSL fixture. |
| Real Component Model contracts | `tools/validate_contracts.sh` passes: WIT/Buf/generated bindings, byte-identical echo rebuilds, three echo/backend checks and four real containment checks. |
| Executable outcome/recovery matrix | The explicitly selected `latentd` Phase 0 end-to-end test passes with the generated fixtures, covering success, failures and same-runtime recovery. |
| Workflow syntax | Actionlint 1.7.12 accepts the updated CI workflow. |

The lightweight workspace command was:

```bash
cargo test --workspace --all-targets --all-features --locked -- \
  --skip one_hundred_thousand_index_adoptions_are_bounded \
  --skip large_release_metadata_has_a_bounded_compilation_working_set
```

The 100,000-release publication/reopen acceptance probe, 100,000-activation
soaks, native calibration/profiling and full Phase 0 authorization gate were
not run. Reading and validating retained archives does not generate replacement
benchmark evidence. The existing successful `development` CI run
[34051729068](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/34051729068)
is historical context, not evidence that this audit reran its heavy job.
