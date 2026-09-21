# Resource recovery qualification, 20 September 2026

Four bounded standalone profiles passed on source `d70d4e724728fc833ca4f29bfaf100e12b35cd44` after the blob staging reclamation fix in PR #453. Every requested dormant population was admitted; sampled processes, threads and listeners plateaued, active ownership returned, and each node shut down cleanly and was reaped. These observations are from the shared Docker Desktop host, not a dedicated performance machine.

| Profile | Samples | Result |
| --- | --- | --- |
| Provider smoke | 23 | All seven checks passed |
| Provider campaign | 72 | All seven checks passed |
| Actual Angular web smoke | 48 | All seven checks passed |
| Actual Angular web campaign | 59 | All seven checks passed |

Provider smoke completed all eight HTTP and eight blob churn arrivals successfully. The campaign retained 96 arrivals per provider: 56 successful blob operations and 43 successful HTTP operations. The remaining 40 blob and 53 HTTP arrivals were failed or unfinished outcomes, not throughput. No closed provider diagnostic codes were observed. Final post-churn provider recovery succeeded.

The provider matrix attempt 08 has status **failed** because its later web setup used an incorrect compiler path. Its two completed provider profiles remain individually passed. A new web-only matrix attempt 09 used the actual compiler and passed both web profiles. The original failed matrix is retained alongside the successful observations; no result was rewritten.

The raw receipts, their build identities and both matrix outcomes are linked below. JSON bytes are unchanged and each has a SHA-256 sidecar. Runtime binaries were built from the recorded source; later source-capture tooling and this documentation commit are not relabelled as measured runtime revisions.

- [2026-09-20-resource-stage-recovery-08-build.json](phase3-resource-evidence/2026-09-20-resource-stage-recovery-08-build.json): `passed`.
- [2026-09-20-resource-stage-recovery-08-campaign.json](phase3-resource-evidence/2026-09-20-resource-stage-recovery-08-campaign.json): `checkpoint-passed`, 72 samples.
- [2026-09-20-resource-stage-recovery-08-matrix.json](phase3-resource-evidence/2026-09-20-resource-stage-recovery-08-matrix.json): `failed`.
- [2026-09-20-resource-stage-recovery-08-smoke.json](phase3-resource-evidence/2026-09-20-resource-stage-recovery-08-smoke.json): `checkpoint-passed`, 23 samples.
- [2026-09-20-resource-web-recovery-09-build.json](phase3-resource-evidence/2026-09-20-resource-web-recovery-09-build.json): `passed`.
- [2026-09-20-resource-web-recovery-09-matrix.json](phase3-resource-evidence/2026-09-20-resource-web-recovery-09-matrix.json): `bounded-profiles-passed`.
- [2026-09-20-resource-web-recovery-09-web-campaign.json](phase3-resource-evidence/2026-09-20-resource-web-recovery-09-web-campaign.json): `checkpoint-passed`, 59 samples.
- [2026-09-20-resource-web-recovery-09-web-smoke.json](phase3-resource-evidence/2026-09-20-resource-web-recovery-09-web-smoke.json): `checkpoint-passed`, 48 samples.

## Remaining acceptance

#239 remains open for standalone secret/event/child-call campaigns, OCI token/resolver/redirect pool accounting, multiple resource ceilings and shared-storage deduplication measurements. JavaScript allocator heap bytes are not exported; unknown values remain unknown. Actual browser qualification belongs to #236, and cold/warm conclusions remain scoped to the recorded host and profiles. The four passing profiles do not certify the full Phase 3 gate.
