# Resource campaign attempt ledger

This directory retains immutable machine observations for #239. It does not
declare full Phase 3 or ticket completion.

| Attempt | Observation | Disposition |
| --- | --- | --- |
| Initial Docker access | Engine pipe unavailable before creation of the owned container | Host unavailable; no resource measurement attempted |
| Initial guest build | Maintained builder rejected missing `wit-bindgen` | Failed setup; pinned repository installer used before a new attempt |
| Guest build 02 | Maintained builder and signed `phase3_workflow_fixture` export completed | Input preparation only, not resource PASS |
| [Container outage](2026-09-19-container-outage.json) | Docker reports exit 255, `OOMKilled: false`, finished `2026-09-19T16:56:07.924178783Z` | Interrupted container lifetime; not graceful cleanup; no application-failure cause inferred |
| [Standalone smoke 01](2026-09-19-smoke-01.json) | Real node rejected configuration before sampling | Failed, zero samples; corrected the harness to use two shared bindings instead of exceeding the existing 16-binding bound |
| [Standalone smoke 02](2026-09-19-smoke-02.json) / [03](2026-09-19-smoke-03.json) | Actual deployment mutation 55 returned definite `resource-exhausted` after six samples | Failed attempts retained; a refusal is not proof of a capacity ceiling. Incomplete requested populations fail the campaign; parent #344 reconciliation work remains separate |
| [Python regressions 03](2026-09-19-python-03.log) | All 16 small tests passed against code checkpoint `7971a1e3` | Method/process regression result only; not provider measurement PASS |
| [Rust experiment 01](2026-09-19-rust-01-failed.log) | Child-call cancellation observation timed out | Failed unfinished test experiment; not a passed provider report |
| [Rust experiment 02](2026-09-19-rust-02-failed.log) | Pool observation returned actual `capability-busy` under two runtime workers | Failed unfinished test experiment; no unavailable counter was replaced by zero |
| [Rust experiment 03](2026-09-19-rust-03-failed.log) | Direct blob write returned actual `BudgetExhausted` under two workers | Failed experiment retained; direct providers now follow their maintained current-thread fixture runtime, separately from the two-worker child manager |
| [Rust checkpoint 04](2026-09-19-rust-04.json) | One actual test passed and wrote 70 snapshots | Preliminary small-fixture observations, not standalone/SSR or full-ticket PASS |
| [Cargo-bound Rust run 01](2026-09-19-rust-run-01.json) / [observations 05](2026-09-19-rust-05.json) | Exact Cargo artifact and nonempty listing, one passed test, 70 validated snapshots at source `983624be` | Real small HTTP/blob/secret/child ownership checkpoint only; full ticket pending |
| [Standalone smoke 04](2026-09-19-smoke-04.json) | First package publication returned `permission-denied`, after three fixed samples | Failed, not the earlier admission refusal. Retained input signature/provenance expired at Unix second `1789837726`; native build 02 began at `1789839233` |
| [Standalone smoke 05](2026-09-19-smoke-05.json) | Binary identity changed after fresh maintained fixture export | Failed before sampling. Rebuild and record a new identity; never relabel or silently accept the changed executable |
| [Standalone smoke 06](2026-09-19-smoke-06.json) | Twelve actual snapshots; cold/warm HTTP and blob worked, peer disconnect returned guest error `11`; invalid blob handle returned `10`, not the harness's expected `11` | Failed harness expectation retained. Actual added dormant populations were 4 and 14 (requested 16 refused); this is not a capacity proof. Node and peer were force-reaped, not graceful shutdown, and temporary outputs were removed |
| [Python regressions 08](2026-09-19-python-08.log) | All 22 tests passed | Includes density-refusal, failed-call retention, exact Cargo artifact, nonempty observations and signed-window regressions; not standalone resource PASS |
| [Strict Clippy 01](2026-09-19-clippy-01-failed.log) / [02](2026-09-19-clippy-02-failed.log) | Inherited library warnings denied before the new target | Failed validation retained; unrelated library code left unchanged |

The outage receipt is actual `docker inspect` output projected to identity,
state, mounts and configured CPU/memory bounds before restarting this worker's
same container. The independent target volume survived. Existing other-agent
containers and volumes were not adopted or modified. A resumed campaign must
identify the host condition and create fresh measurement receipts.
