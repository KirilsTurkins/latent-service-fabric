# Resource campaign implementation checkpoint

This is a draft #239 handoff, not ticket acceptance or a resource measurement
PASS. The code checkpoint is `7971a1e34be1ec84d4c5b92faed2379ed8afc215`, on
`feat/239-provider-web-resource-campaign`, based on the requested parent
`f75482ebd1a4c9da0faf648641cba68bce104837`. Review the resource-only change from
that base; the remote parent branch has not yet published this local parent
history. This worker does not merge, close issues or push the parent's branch.

## Executed checks

- `python3 -m unittest tools.tests.test_phase3_resource -v`: 16 tests passed in
  the isolated Linux container. The [retained log](phase3-resource-evidence/2026-09-19-python-03.log)
  includes a real owned-process measurement/reap regression; synthetic scheduler
  and evidence tests are not provider performance results.
- `python tools/validate_docs.py`: passed with no errors across 312 tracked
  documents, including this checkpoint and its evidence links.
- The real node and CLI built with `cargo build --locked -p latentd -p latent
  -j 3`; the maintained guest builder and ignored
  `phase3_workflow_fixture::export_signed_provider_workflow_fixtures` test
  produced real signed HTTP/blob/callee inputs. These are preparation results.

All three executed standalone smoke attempts failed. Their immutable reports
and the Docker outage observation remain in the [attempt ledger](phase3-resource-evidence/README.md).
The new admission-saturation handling still needs an actual complete campaign
run. Dedicated Rust resource tests are unfinished working-tree experiments;
their two failed runs do not qualify any provider, even where an earlier test
stage progressed. They are not included in the code checkpoint above.

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
- Secret, event and child-call campaign coverage, #270 token/resolver/redirect
  accounting, and #266 shared-package/multiple-publication storage measurements.
- Retained-byte analysis distinguished from RSS, and separate cold/warm latency
  and overload interpretation. No universal Docker/Kubernetes performance claim.

Keep the pull request draft and every ticket acceptance item pending. Parent
review and CI must refer to the exact eventual head, not this intermediate
checkpoint's test results.
