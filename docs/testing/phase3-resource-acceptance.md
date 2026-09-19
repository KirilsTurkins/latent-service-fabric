# Bounded resource acceptance matrix for #239

This is the continuation of existing PR #376, not a new PR. Previous failed
receipts and checkpoint documents remain historical observations. Resource work
stays on `feat/239-provider-web-resource-campaign`; parent review owns exact-head
CI and merge. Qualified Angular T1 source `946f9b82` (including provider startup
base `bcd902cd`) is merged as `990ed134` without changing those implementations.
Three inherited browser documentation/descriptor conflicts retain the qualified
parent versions. No SDK runtime `Unavailable` fix is made here.

## Declared matrix before execution

The ticket specifies coverage, not 100000 deployments. These finite profiles
were reported before execution. One owned container is limited to 3 CPUs, 6 GiB
RAM with no extra swap, and 256 PIDs. Profiles run sequentially, not concurrently
with another resource build. Cargo uses `/workspace/target/phase3-239`, inside
the existing resource-only volume. The Angular target volume is mounted
**read-only** for its maintained build and optimized compiler. No container,
volume, failed receipt, previous binary or user directory is removed.

| Profile | Cells / queue | Dormant deployments | Policy read owners | Churn | Deadline |
| --- | --- | --- | --- | --- | --- |
| `smoke` v2 | 1 / 2 | 4, 16 plus 3 fixture deployments | 64 | 2 x 8 arrivals, 10 ms interval, 6 outstanding | 240 s |
| `campaign` v2 | 2 / 2 | 4, 16, 32 plus 3 fixture deployments | 96 | 8 x 24 arrivals, 5 ms interval, 8 outstanding | 900 s |
| `web-smoke` v1 | 1 / 2 | 2, 4 actual Angular deployments | No capability policy owner | 2 x 4 arrivals, 10 ms interval, 5 outstanding | 600 s |
| `web-campaign` v1 | 2 / 2 | 2, 4, 8 actual Angular deployments | No capability policy owner | 4 x 8 arrivals, 5 ms interval, 6 outstanding | 900 s |

Both web tiers use the existing protected `external-capsule-v1` profile and
256 MiB per-cell memory ceiling, a 300-second isolated preparation ceiling,
and five-second invocation budgets. Success, exception, explicit cancellation,
client disconnect, overload, recovery, shared ingress and unrouting are distinct
populations. An actual JS allocator heap counter is unavailable; OS RSS and
configured Wasm memory ceilings must not be mislabeled as that counter.

The v1 smoke's requested 16-deployment population is retained in v2, not lowered
to hide its failure. The unexecuted larger v1 profile's 64-deployment population
is deliberately replaced by a new, smaller 32-deployment v2 profile: old and
staged capability plans for 66 imported deployments would exceed the supported
128 ordinary policy read owners before observation headroom. No runtime maximum
is raised. Configuring catalog entries alone did not budget the separate policy
snapshot owner. The corrected runner preflights both generations and two
observation owners (38 required for smoke, 70 for campaign), and records the
actual configured ceilings. This is not proof that the old CLI exposed the
limiting owner. A focused real policy-store regression tests refusal at the 33rd
snapshot under limit 32 and admission/reclamation under limit 64.

## Previous container exit

Before creating the new runner, `docker inspect lsf-phase3-239-resource` reported
exit **137**, `OOMKilled: false`, no daemon error, start
`2026-09-19T16:58:05.456590369Z`, finish `2026-09-19T18:15:30.615022441Z`.
Its command was `sleep 28800`, and container logs were empty. A bounded Docker
event query returned no retained events. These observations do not identify who
sent a kill signal and do not prove an application OOM or a resource leak. The
old container remains untouched. The new `lsf-phase3-239-acceptance` container
uses the same owned resource volume without overwriting previous outputs.

The first new build shell failed before Cargo launch because a login shell
discarded the image's Cargo PATH. `phase3-239-fixture-build-01.log` is preserved;
a non-login shell is used for the distinct build 02. That failure is setup, not
product or acceptance evidence.

## Evidence and acceptance boundary

New receipts use `latent.phase3.resource-campaign.v2`, exact binary/source,
profile, configuration and signed-input identities, exclusive JSON/checksum
creation, and the existing bounded/reaped process harness. Storage snapshots
distinguish file count, logical bytes, unique inode bytes and allocated blocks;
they include retained audit data and do not promise filesystem block dedup.
Angular independently admits two packages/publications sharing one component.

PR #376 now explicitly targets `development`, not the former stacked SDK base.
The first new executions below identify source `4b94e524`; they are not evidence
for a later merge of SDK #366 or for the eventual development merge commit.
Any real `Unavailable` stops that profile and is retained for the parent's
SDK/runtime diagnosis, without replaying mutations or claiming PASS.

## Executed observations at `4b94e524`

All three attempts used the same real node SHA-256
`1724391b6cf80f21f2d8d6da5a0d317f5b67d602ada90bca47d7b70f83ecee6d`
and CLI SHA-256
`308d28776ed6d47911fa1091b276c3d5b9c12805531f0fb145e28739665d7889`.
Each attempt retains its own build, fresh signed export, matrix and measurement
receipt with original checksum sidecars. Times describe this shared Docker
Desktop host only.

| Profile / attempt | Actual observation | Disposition |
| --- | --- | --- |
| [Provider smoke v2 / 01](phase3-resource-evidence/2026-09-19-provider-smoke-v2-01.json) | 23 snapshots, all 4/16 added dormant deployments, two churn cycles, real HTTP/blob cold/warm/failure/cancel/recovery and clean shutdown in 32300 ms | Seven checkpoint checks passed; full ticket still pending |
| [Provider campaign v2 / 02](phase3-resource-evidence/2026-09-19-provider-campaign-v2-02.json) | 67 snapshots, all 4/16/32 added dormant deployments and eight 24-arrival cycles; final HTTP recovery succeeded but blob recovery returned known `guest-trap` in 44305 ms | Failed `resource-real-provider-output`; node and peer force-reaped, not graceful shutdown |
| [Web smoke v1 / 03](phase3-resource-evidence/2026-09-19-web-smoke-v1-03.json) | 10 snapshots, all 2/4 dormant actual Angular deployments; cold preparation returned gRPC `resource-exhausted` after 117167543 ns, before any render | Failed `resource-render-preparation-result`; unknown RPC outcome, no preparation/render PASS |

In provider smoke, dormant processes/threads/listeners plateaued at 1/8/1,
with 34 open descriptors and RSS 62783488 bytes. After churn, active ownership
returned to zero; six recovery samples retained 36 descriptors and RSS
81432576..81825792 bytes. These values distinguish warmed fixed resources from
dormant density, not an allocator leak proof. Cold HTTP/blob elapsed times were
1157651469/1819662791 ns; retained calls include all outcomes rather than only
successes. Three overload RPCs returned gRPC exhaustion with unknown outcomes,
not proof of known queue rejection. Shutdown was clean but reported **11 blob
stages**, distinct from zero active blob handles/work.

The larger provider failure is consistent with the finite retained-stage
contract: the maintained blob guest repeatedly writes the same four bytes,
duplicate seal closes its writer but leaves an inactive stage for explicit
privileged reclamation, and the standalone store defaults to 16 stages. No
standalone reclamation operation was found in the configured provider path.
The guest unwraps creation errors into traps. All blob arrivals in cycles 2..7
trapped, rather than demonstrating post-churn reusable write capacity. This
source-based diagnosis is not a directly exported stage count from the failed
node; that attempt has no graceful shutdown snapshot. Its last sample also
reports 372 dropped audit observations, an explicit evidence limitation.
Neither raising the production limit nor reducing the executed population is
claimed as a fix.

The first web runner overlapped `web prepare` with an inventory RPC while
`workers.control` allowed only one control job. Transport derives its control
job ceiling from that setting and rejects excess jobs. This explains a harness
self-contention risk consistent with the observed gRPC exhaustion; the generic
RPC error does not itself identify the limiting owner. A corrected observation
budget must be a new profile/receipt, never a relabeling of this failure.

No run above returned the parent's intermittent `Unavailable`. Web campaign,
successful web preparation/render churn, standalone event/secret/child coverage,
JS heap counters and OCI resolver/token/redirect campaigns remain gaps at this
checkpoint. The earlier real HTTP/blob/secret/child Rust fixture observations
are separate from standalone acceptance.

Historical results: [checkpoint](phase3-resource-checkpoint.md),
[attempt ledger](phase3-resource-evidence/README.md),
[methodology](phase3-resource-methodology.md).

## Running the matrix

`tools/phase3_resource_campaign.py --matrix` prints the complete finite matrix
without starting a process. `tools/run_phase3_resource_acceptance.py` builds and
selects the exact Cargo fixture executables, verifies their nonempty listings,
records the current native build, and exports fresh real-clock signed inputs
immediately before each profile. A failed profile stops the matrix. All reports,
including preparation failures, use new paths; no mutation is replayed.

```sh
export CARGO_TARGET_DIR=/workspace/target/phase3-239
export CARGO_BUILD_JOBS=3 CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0
python3 tools/run_phase3_resource_acceptance.py --revision FULL_SOURCE_COMMIT --output /workspace/target/resource-attempt-UNIQUE --guest-capsules /workspace/target/phase3-resource-guests-02 --angular-build /angular-target/phase3-angular-t1-build/actual-selected-01 --compiler /angular-target/phase3-226-release/release/latent-aot-compiler --host-condition shared-docker-desktop-host
```

`--profile smoke` selects only the first small provider tier; each invocation
still needs a fresh output directory. Ordinary CI runs the small Python and
automatically discovered Rust regressions. The real matrix requires the explicit
`workflow_dispatch` input `run_phase3_resources`, default false, independently of
the unchanged `run_catalog_scale` heavyweight gate. Manual CI creates its own
guest inputs, uses the job's actual Angular build and optimized compiler, and
uploads even failed JSON/checksum attempts. No hosted CI execution is claimed
by this integration change.
