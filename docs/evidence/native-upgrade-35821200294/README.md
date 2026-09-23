# Native alpha.4 compatible-upgrade rehearsal

[Release run 35821200294](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35821200294)
completed successfully on September 23, 2026 with `publish=false`. The immutable
`0.1.0-alpha.4` tag, source and harness all identify
`193d52c37635026de416feffd4a2dfd57d082451`. Its
[exact-source CI 35818046307](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35818046307)
passed before tag selection. These are complete VM qualification results for
this rehearsal archive; protected publication remains pending.

| Recorded input | Identity |
| --- | --- |
| Final archive | `lsf-0.1.0-alpha.4-x86_64-unknown-linux-gnu.tar.gz`, 28,950,166 bytes |
| Final archive SHA-256 | `1340b9b2d3e30ee9b0b563da62f1f99f74ff592b07db0c58dc0f7b6b8cdd09d2` |
| Exact predecessor | `0.1.0-alpha.4-rc.2`, source `a53b7b219a46f6ca91ae7bc7830669f8aa4bbe2e` |
| Predecessor SHA-256 | `3479b32fb3181066572d61cc6a65abb38bafb2311188b358fac7e7e365195ee3` |
| Predecessor run | [35811188306](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35811188306) |

Both [local](local-experimental-v1.json) and
[external-capsule](external-capsule-v1.json) receipts report `passed:true`,
`acceptanceComplete:true` and empty `gaps`. They record different real boot IDs,
successful initial/retained/upgrade phases, the genuine rc.2-to-alpha.4 pair,
retained publication identity and rejected unsupported downgrade. The local
receipt also records successful non-root foreground evaluation. The VM harness
exercises authenticated readiness, retained invocation, backup/full-set restore,
removal/reinstall and separately confirmed purge. Its exact source and scope
remain part of the [native release contract](../../development/native-release-gate.md).

The [summary](summary.json) binds those original receipt hashes and the result of
independent `gh attestation verify` using separately obtained Sigstore roots,
the exact repository/workflow/tag certificate, OIDC issuer, source/signing
commit and GitHub-hosted runner requirement. The
[verifier output](publisher-verification.json), [signed checksum inventory](SHA256SUMS),
[attestation](SHA256SUMS.sigstore.json), [release manifest](release.json),
[release decision](native-release-decision.json) and
[artifact identities](artifact-identities.json) retain the observed inputs and
results. The original files are copied byte-for-byte; the summary is a separate
review record. No trust root is supplied by these evidence files.

The narrow host matrix is Ubuntu Server 24.04/x86_64. This evidence does not
claim reproducible builds, broader host support, hostile multitenancy or a
published binary. Publication rebuilds and qualifies its own exact bytes before
the protected maintainer review; its archive digest must be observed separately.
The foundation's original incomplete acceptance and earlier failed candidates
remain unchanged. Current-format rc.2 compatibility requires no obsolete reader.
