# Resource campaign implementation checkpoint

This is a draft #239 handoff, not full ticket acceptance or a standalone resource
campaign PASS. The initial code checkpoint is `7971a1e34be1ec84d4c5b92faed2379ed8afc215`, on
`feat/239-provider-web-resource-campaign`, based on the requested parent
`f75482ebd1a4c9da0faf648641cba68bce104837`. Review the resource-only change from
that base; the remote parent branch has not yet published this local parent
history. This worker does not merge, close issues or push the parent's branch.

## Executed checks

- `python3 -m unittest tools.tests.test_phase3_resource -v`: 22 tests passed in
  the isolated Linux container at `c1ca87b9`. The [retained log](phase3-resource-evidence/2026-09-19-python-08.log)
  includes a real owned-process measurement/reap regression; synthetic scheduler
  and evidence tests are not provider performance results.
- `python tools/validate_docs.py`: passed with no errors across 312 tracked
  documents, including this checkpoint and its evidence links.
- The real node and CLI built with `cargo build --locked -p latentd -p latent
  -j 3`; the maintained guest builder and ignored
  `phase3_workflow_fixture::export_signed_provider_workflow_fixtures` test
  produced real signed HTTP/blob/callee inputs. These are preparation results.
- `python3 tools/phase3_resource_rust.py --revision
  983624be7daada4b5b00d363e1fe39e6dbabfb74 --output
  /workspace/target/phase3-resource-rust-run-01.json --report
  /workspace/target/phase3-resource-rust-05.json --host-condition
  shared-docker-desktop-host --host-condition resumed-after-engine-outage`:
  one actual Cargo-discovered test passed, with 70 resource snapshots. The
  [run receipt](phase3-resource-evidence/2026-09-19-rust-run-01.json) binds the
  exact binary, Cargo profile, compiler output, source inventory and nonempty
  test listing to the [observations](phase3-resource-evidence/2026-09-19-rust-05.json).

Standalone smoke attempts remain unsuccessful. Their immutable reports and the
Docker outage observation remain in the [attempt ledger](phase3-resource-evidence/README.md).
The collector now fails incomplete requested density, preserves actual refusal
and cleanup observations, rejects stale signed-input windows, and refuses a
changed binary. No earlier failed attempt is reclassified by a later test pass.

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
zero. Its 2,103-file explicit source inventory is recorded, but compiler implicit
inputs are not hermetically attested. The ordinary workspace Rust test command
discovers this small regression; the expensive standalone campaign stays manual.

Strict Clippy was attempted and failed in inherited `latent-manifest` and
`latent-wasmtime` library code before this test target. The original diagnostics
are retained; no unrelated library lint repairs or strict-Clippy PASS are claimed.

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

- A complete measured provider checkpoint with actual active and recovered
  owners; broader configured ceilings and longer bounded churn.
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
