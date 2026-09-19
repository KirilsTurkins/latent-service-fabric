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
| [Standalone smoke 02](2026-09-19-smoke-02.json) / [03](2026-09-19-smoke-03.json) | Actual deployment mutation 55 returned definite `resource-exhausted` after six samples | Failed attempts retained; the collector now records admission saturation and actual committed populations rather than assuming every requested deployment fits |
| [Python regressions 03](2026-09-19-python-03.log) | All 16 small tests passed against code checkpoint `7971a1e3` | Method/process regression result only; not provider measurement PASS |
| [Rust experiment 01](2026-09-19-rust-01-failed.log) | Child-call cancellation observation timed out | Failed unfinished test experiment; not a passed provider report |
| [Rust experiment 02](2026-09-19-rust-02-failed.log) | Pool observation returned actual `capability-busy` under two runtime workers | Failed unfinished test experiment; no unavailable counter was replaced by zero |

The outage receipt is actual `docker inspect` output projected to identity,
state, mounts and configured CPU/memory bounds before restarting this worker's
same container. The independent target volume survived. Existing other-agent
containers and volumes were not adopted or modified. A resumed campaign must
identify the host condition and create fresh measurement receipts.
