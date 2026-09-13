# Phase 2 bounded gate evidence

Collected September 13, 2026 (Europe/Berlin). These are finite functional and
resource checks, not a performance comparison or a production availability SLO.
The [completion review](../../../docs/phase-2-completion.md) maps the milestone
requirements and limitations. [attempts.json](attempts.json) preserves failed,
unavailable and superseded attempts; a later passing run does not reclassify them.

## Retained runs

| Receipt | Population and outcome |
| --- | --- |
| [Operator](operator-receipt.json) | PASS: two signed test packages through a real authenticated TLS registry, separate caller/node storage, 114 CLI commands and 18 successful Invokes; exact canary, promotion, rollback, restart and revocation records. |
| [Offline](offline-receipt.json) | PASS: 24 CLI commands, two successful Invokes and one revoked-release denial. Stopping only the registry blocks a fresh pull while eligible retained execution succeeds. |
| [Native currentness](native-currentness-receipt.json) | Three PASS cases: real isolated compilation/loading followed by proof-age expiry, policy expiry or publisher revocation. Old readiness, final start and cache reopen cannot revive permission. |
| [Resource](resource-receipt.json) | PASS: fixed `phase2-dormant-32-r1`, 32 releases, 16 deployments, two warmed portable images, 32 Invokes, 133 controls, 12 OS samples and actual clean shutdown/reap. |
| [Wiki publication](wiki-publication.json) | 26 pages, four assets and 147 links; actual committed bytes of all 30 managed files verified against the published source. This publication describes delivered features with gate #158 still pending. |

The operator receipt retains both actual clean stopped records. Its earlier
attempt failed at CLI command 58 with generic `Unavailable`; no complete canary
result was accepted from that attempt. The exact internal cause remains
unclassified. The separate passing attempt used the same maintained collector,
production binaries, workload and limits, with fresh signed fixtures. There was
no retry of a failed Invoke or adjustment to the canary denominator or threshold.

## Resource observations

The local host was Linux x86_64 on WSL2 kernel
`6.6.87.2-microsoft-standard-WSL2`, with Python 3.13.5 and Rust 1.97.1 debug builds.
This is not a bare-metal result. The predefined profile took 8.739 seconds,
including identity processing, work and shutdown; that duration is not a latency
benchmark. Every phase retained seven threads/tasks, 18 descriptors, three
sockets, one TCP listener and zero descendants. Only two of the 32 releases were
prepared; the other 30 had no execution resources.

| Phase (three samples each) | Median RSS bytes | Median RSS MiB |
| --- | ---: | ---: |
| Warm baseline | 63,832,064 | 60.875 |
| Dormant cohort | 64,618,496 | 61.625 |
| Execution reclaimed | 66,060,288 | 63.000 |
| Deployments removed | 66,060,288 | 63.000 |

RSS grew by 0.750 MiB with the dormant cohort and by 2.125 MiB by final route removal.
Authoritative release metadata, audit history and two prepared images remain
intentionally retained. The receipt proves the declared transient counters reach
zero and owners join/reap; it does not claim that RSS returns to baseline, that
32 native images were compiled, or that any arbitrary infrastructure size fits.

## Identity and reproduction

Local production CLI/node binaries were built at
`32f9d3f03e2def6548afc4dd9f445bf819b1aa93`. The receipts bind their exact bytes,
Cargo.lock, configuration, collector/profile sources and test fixture identities.
The native receipt additionally binds the actual test/exporter/compiler binaries
and changed test sources. Source-to-binary associations are build-owner records;
these JSON files are not independent hermetic build attestations. Later merge
revisions do not replace the recorded measured revisions.

The operator/offline/resource/native fixtures explicitly use synthetic signed
test observations. Separately, [observed-echo-receipt.json](observed-echo-receipt.json)
binds all ten actual [observed echo inputs](observed-echo/observation.json) from
[CI run 34723362373](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/34723362373).
That CI's OCI TLS integration passed using these captured build/provenance/SBOM
inputs. The complete retained input set is 57,695 bytes, including its small
component, so replay does not depend on an expiring artifact download. The
observation declares two-build byte equality, lockfile-only dependency
completeness, operator-asserted repository identity and `hermetic:false`; none of
those qualifications are upgraded here.

Run the offline resource validator without launching anything:

```sh
python3 tools/phase2_gate_resource.py --validate benchmarks/phase2/2026-09-13/resource-receipt.json
```

Fresh executions use the maintained [resource profile](../../../docs/testing/phase-2-resource-profile.md),
[offline/native instructions](../../../docs/testing/phase-2-offline-validation.md)
and [operator walkthrough](../../../docs/development/standalone-quickstart.md).
Generate fresh signed fixtures rather than extending old proof ages. The actual
observed input can also be supplied to `tools/run_oci_registry_tests.py` through
its `--provenance-input` option with an owned TLS fixture. These commands produce
new observations; they do not recreate the old machine state or signing keys.

Only compact receipts, source identities, the tiny observed-build input set and
checksums belong here. Raw logs, compiler caches, private keys, credentials,
temporary worktrees and heavy load reports are excluded. Phase 0/1 measurements
keep their historical identities and [retention rules](../../../docs/testing/benchmark-retention.md).
