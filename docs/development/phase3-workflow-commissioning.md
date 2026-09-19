# Phase 3 workflow commissioning

## Purpose and exact boundary

Promote reviewed integration source `20bb208345b0787bfef2ec970b1223b2d8e15632`
to the repository's existing default `release` branch so its native release
and maintained-security coordinators become available. This is workflow
commissioning for an experimental qualification release, not the Phase 3
completion gate and not a declaration that all development tickets have closed.

The current workspace version is `0.1.0-alpha.4-rc.1`. The historical
`0.1.0-alpha.3` release remains source-only and its tag must not move. No tag,
binary release or public installation identity is created by this documentation
commit or by merging the coordinator promotion itself.

## Native qualification sequence

1. Merge this promotion only after its exact-head maintained CI and security
   checks pass and review blockers are resolved.
2. Select an independently reviewed, CI-passing commit whose committed version
   matches a new immutable tag. Dispatch `native-runtime-release.yml` at that
   exact tag with `publish=false`; a checksum alone is not authentication.
3. Retain the publisher-authenticated archive, provenance, SBOM and actual
   rootless/systemd VM receipts for both supported profiles. An initial native
   foundation without a genuine predecessor is not completed upgrade evidence.
4. Commit one explicit compatible predecessor identity into the next selected
   version, review and validate it, and qualify actual installed upgrade,
   reboot, key/configuration/state preservation and unsupported-path refusal.
5. Publish only when complete VM acceptance, archive authentication and the
   required reviewer on `native-runtime-publish` all pass. Do not self-approve,
   weaken protection, substitute workspace binaries, or fabricate a predecessor.

The [native promotion runbook](../operations/native-release-promotion.md)
defines exact commands and the retained evidence boundary. Native distribution
and end-user installation do not require a container runtime.

## Security commissioning

Registration on the default branch does not prove that manual or scheduled
monitoring ran. Execute and retain the existing coordinator's separate results
for the exact maintained `development` and `release` refs, including unchanged
lockfile advisory checks. Inventory actual required checks, permissions,
secret/push-protection settings and any external prerequisites independently.
The [security monitoring runbook](../operations/maintained-security-monitoring.md)
distinguishes settings, registration and executed evidence.

## Remaining Phase 3 gates

The SDK matrix, Angular reference application, integrated adversarial and
resource evidence, complete Docusaurus learning paths, protected Pages/Wiki
cutover and final native publication remain separately reviewed deliveries.
This promotion must not close #201, #240, #345, #282 or #308 by association.
