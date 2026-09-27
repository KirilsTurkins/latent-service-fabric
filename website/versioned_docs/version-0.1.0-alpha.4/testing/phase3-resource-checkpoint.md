# Resource campaign implementation checkpoint

This is a draft #239 handoff, not full ticket acceptance or a standalone resource
campaign PASS. Branch `feat/239-provider-web-resource-campaign` starts from the
requested parent `f75482ebd1a4c9da0faf648641cba68bce104837`. The requested startup
fix `bec5d8bf037d1f770e193636326a747070d2677c` is an ancestor through merge
`312454e01cd2335b55f5cf192a14599d31131fc5`. Its asset-fixture conflict preserves
the pre-merge boxed `configured_application` logic; that file has no net change
from the resource branch's pre-merge head. No shared SDK runner or Angular T1
implementation was edited by this worker. The post-merge checks below use
`13b21503040d59a7a5d06ac2e99bc10e64d64a56`. Parent owns inherited history,
exact-head CI, PR review and merge; this worker does not close issues or push
the parent's branch.

## Executed checks

- `python3 -m unittest tools.tests.test_phase3_resource -v`: 23 tests passed in
  the isolated Linux container at `13b21503`. The [retained log](phase3-resource-evidence/2026-09-19-python-09.log)
  includes a real owned-process measurement/reap regression; synthetic scheduler
  and evidence tests are not provider performance results. The new regression
  keeps uncertain gRPC exhaustion distinct from known platform nonacceptance.
- `python tools/validate_docs.py`: passed with no errors across 314 tracked
  documents, including this checkpoint and its evidence links.
- The real node and CLI built with `cargo build --locked -p latentd -p latent
  -j 3`, recorded in [build 04](phase3-resource-evidence/2026-09-19-build-04.json).
  Fresh maintained fixture export used the actual guest-build-02 HTTP/blob/callee
  capsules; [fixture log 04](phase3-resource-evidence/2026-09-19-fixtures-04.log)
  records the one passed export test. These are preparation results.
- `python3 tools/phase3_resource_rust.py --revision
  13b21503040d59a7a5d06ac2e99bc10e64d64a56 --output
  /workspace/target/phase3-resource-rust-run-02.json --report
  /workspace/target/phase3-resource-rust-06.json --host-condition
  shared-docker-desktop-host --host-condition resumed-after-engine-outage`:
  bounded externally by `timeout 1050`, one actual Cargo-discovered test passed,
  with 70 resource snapshots. The
  [run receipt](phase3-resource-evidence/2026-09-19-rust-run-02.json) binds the
  exact binary, Cargo profile, compiler output, source inventory and nonempty
  test listing to the [observations](phase3-resource-evidence/2026-09-19-rust-06.json).

Standalone smoke attempts remain unsuccessful. Their immutable reports and the
Docker outage observation remain in the [attempt ledger](phase3-resource-evidence/README.md).
The collector now fails incomplete requested density, preserves actual refusal
and cleanup observations, rejects stale signed-input windows, and refuses a
changed binary. No earlier failed attempt is reclassified by a later test pass.

## Post-merge standalone attempt

[Smoke 08](phase3-resource-evidence/2026-09-19-smoke-08.json) completed its
HTTP/blob workload, failure/cancellation, overload, two open-loop churn cycles,
recovery and unrouting in 44,278 ms. It retained 23 actual snapshots and 123
control-command records. **The campaign failed**: the requested dormant
populations were 4 and 16, but only 4 and 14 were admitted. Deployment
`dormant-014` received definite platform `resource-exhausted`; the CLI did not
expose the limiting owner. Component, package and publication counts are
independently 3, 3 and 3; total deployments were 7 and 17. No population was
lowered to turn this failure into a pass.

| Sampled phase | Samples | Processes / threads / listeners | Sockets / handles | RSS bytes |
| --- | --- | --- | --- | --- |
| Fixed | 3 | 1 / 8 / 1 | 3 / 34 | 58,458,112 |
| Dormant, actual 4 and 14 | 6 | 1 / 8 / 1 | 3 / 34 | 62,783,488–63,045,632 |
| Active held requests | 2 | 1 / 8 / 1 | 5–9 / 38–42 | 80,437,248–80,826,368 |
| Recovered | 6 | 1 / 8 / 1 | 3 / 36 | 80,904,192–81,379,328 |
| Unrouted | 3 | 1 / 7 / 1 | 3 / 36 | 81,510,400 |

The three additional warm snapshots are in the receipt. The dormant samples
observed two broker provider objects at both admitted densities, while broker
plans increased from 7 to 17 and their metadata charge from 68,672 to 153,312
bytes. Active samples observed one/two cells and queue depths zero/two; the
six recovery snapshots observed zero active cells, queued work and the required
activation-scoped provider counters. Two prepared-cache entries and 56,848
metadata bytes remained after unrouting. These are scoped sampled counters, not
global peak or allocator-retention measurements. Higher recovered RSS is not
hidden behind an exact-memory-return assertion.

The receipt's observed ownership-return and dormant process/thread/listener/
provider-object checks are true, but `requestedDormantPopulationsAdmitted` is
false, so the overall result remains failed. Node shutdown reported `clean:
true`; the node and external peer were actually reaped and temporary outputs
removed. The peer recorded 17 authorized requests, one controlled disconnect,
five held requests and five observed hold closures. Overload included one
gRPC `resource-exhausted` with an **unknown outcome**, not proof of a known
pre-admission node-queue rejection. No accepted write was replayed.

| Actual CLI latency sample | Cold, one observation (ns) | Warm, two-observation range (ns) |
| --- | --- | --- |
| HTTP | 1,662,224,217 | 22,957,015–28,718,776 |
| Blob | 3,114,458,306 | 38,552,225–44,108,215 |

This includes process creation, preparation, RPC/provider work and process reap,
not isolated network latency or a throughput claim. The shared host and small
sample populations preclude general performance conclusions.

The actual post-merge native executable identities are:

- Node: `sha256:1a7a3c11d3e9aa049dbbe31edcb9fbb08d061915377f3017aeb4932d13e623fa`,
  155,037,592 bytes.
- CLI: `sha256:afeefeb60a57d9eecf938cd56951e6c1633c6cb5fd4f2c1b5ba920a14ee02118`,
  61,111,504 bytes.

Build 04 records the dev profile, Rust 1.97.1 and explicit source inventory;
smoke 08 separately binds configuration, collectors and signed guest inputs.
These commands were executed, rather than being future reproduction promises:

```sh
LSF_GUEST_CAPSULES=/workspace/target/phase3-resource-guests-02 LSF_PHASE3_WORKFLOW_FIXTURE_ROOT=/workspace/target/phase3-resource-fixtures-04 timeout 900 cargo test --locked -p latentd --test phase3_workflow_fixture export_signed_provider_workflow_fixtures -- --exact --ignored --nocapture --test-threads=1
python3 tools/phase3_resource_campaign.py --record-build /workspace/target/phase3-resource-build-04.json --revision 13b21503040d59a7a5d06ac2e99bc10e64d64a56
timeout 280 python3 tools/phase3_resource_campaign.py --profile smoke --node /workspace/target/debug/latentd --cli /workspace/target/debug/latent --fixture-root /workspace/target/phase3-resource-fixtures-04 --build-identity /workspace/target/phase3-resource-build-04.json --output /workspace/target/phase3-resource-smoke-08.json --host-condition shared-docker-desktop-host --host-condition resumed-after-engine-outage
```

### Density refusal diagnosis

The same receipt observes policy read owners rising from 6 to 16 across the
actual dormant populations, and returning to zero after unrouting. Source
inspection identifies a candidate transient limit, **not a measured refusal
attribution**: [policy snapshots](../../crates/latent-policy/src/capability/store/authority.rs)
retain a read lease, [binding plans](../../crates/latent-capabilities/src/broker/plan.rs)
take snapshots, and the [catalog compiler](../../crates/latent-control-store/src/deployments/bindings/compile.rs)
compiles plans for the next catalog. The default
[read-owner bound](../../crates/latent-policy/src/capability/store/model.rs) is 32;
the topology's configured 36 includes four separate mutation-response owners.
Sixteen retained snapshots plus seventeen tentative snapshots would need 33
ordinary read owners. This is consistent with the observed refusal but requires
an instrumented transient-owner regression before declaring the root cause.
No runtime limit or requested density was changed, and the earlier startup
recovery fix is not assumed to solve this distinct density refusal.

## Measured small-test checkpoint

| Provider | Actual observations | Selected active ownership | Recovery observations |
| --- | --- | --- | --- |
| HTTP | 18 | One sampled guest Store, broker session and connection; success, disconnect and cancellation exercised | Eight snapshots with zero live Stores and broker sessions |
| Blob | 14 | Real retained writer/reader ownership and four result bytes; guest success/trap and cancelled retained result exercised | Six snapshots with zero live Stores and broker sessions |
| Secret | 24 | Running ceilings one and two; sampled maximum two running and one queued request; queued/active cancellation and denied reads exercised | Ten snapshots with zero live Stores and broker sessions |
| Child | 14 | One/two-cell configurations; sampled two live Stores and two sessions during real child work; overload, declared failure and cancellation exercised | Ten snapshots with zero live Stores and broker sessions |

These are sampled observations, not instantaneous global maxima. OS counters
cover the actual test process, including its in-process HTTP peer. HTTP/blob/
secret use their maintained current-thread fixture runtime; child calls use a
separate fixed two-worker local manager runtime. Do not compare these as a
single standalone node's dormant-density plateau. Renderer heaps, allocator
retained bytes and direct-fixture scheduler-cell leases remain explicitly null.

The recorded test executable is
`sha256:43c30a92e9a0cf8b1e2d4967d3023db900798b4a4c01edf3f8401924a64a0146`,
121,280,648 bytes, Cargo test profile with optimization level zero and debuginfo
zero. The post-merge 2,105-file, 13,453,869-byte explicit source inventory is
`sha256:ea659b26f2cbc679daa6b67cba745d290df1539a0f440ff071779e869be4bd5e`;
compiler implicit inputs are not hermetically attested. The ordinary workspace Rust test command
discovers this small regression; the expensive standalone campaign stays manual.

Earlier strict Clippy was attempted and failed in inherited `latent-manifest` and
`latent-wasmtime` library code before this test target. The original diagnostics
are retained; no unrelated library lint repairs or new post-merge strict-Clippy
PASS are claimed.

## Executable methods

The [methodology](phase3-resource-methodology.md) documents finite input and
process inventories, immutable open-loop arrival accounting, actual owner
snapshots, failure/cancellation recovery, byte-bound exclusive reports, binary
and source identity, and unknown-versus-zero semantics. Reproduction commands
live there rather than being described as executed results.

Container `lsf-phase3-239-resource` uses only its own target volume
`lsf-phase3-239-target`, with 3 CPUs, 6 GiB memory and a finite lifetime. Its
existing image is `lsf-phase3-qualified-tools:local`; the observed image digest
is `sha256:74d69233189f84d2f56332f5bb09902eb413a2c54768fb55b9d547ded1bf5311`.
This is a shared Docker Desktop host, resumed after the recorded engine outage,
not an isolated performance machine. No other agent's target volume was used.

## Still required

- A complete standalone provider campaign admitting every requested population;
  definitive density-refusal diagnosis, broader ceilings and longer bounded churn.
- Actual #236/#226 SSR/browser input identity and success/failure/cancellation,
  render preparation/cache costs and renderer heap measurements.
- Broader standalone secret/event/child-call campaign coverage beyond the small
  fixture tests, #270 token/resolver/redirect accounting, and #266
  shared-package/multiple-publication storage measurements.
- Retained-byte analysis distinguished from RSS, and separate cold/warm latency
  and overload interpretation. No universal Docker/Kubernetes performance claim.

Keep the pull request draft and every ticket acceptance item pending. Parent
review and CI must refer to the exact eventual head, not this intermediate
checkpoint's test results.
